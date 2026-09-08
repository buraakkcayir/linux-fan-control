#!/usr/bin/env python3
import sys
import os
import glob
import time
import subprocess
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QSlider, QProgressBar, QFrame,
                             QSystemTrayIcon, QMenu)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

SOCKET_NAME = f"nitrosense_{os.getuid()}_ipc_socket"

LAST_GPU_QUERY_TIME = 0
CACHED_GPU_TEMP = None

# ----------------- Hardware Communication Functions -----------------

def get_profile_path():
    paths = glob.glob("/sys/devices/platform/acer-wmi/platform-profile/platform-profile-*/profile")
    if paths:
        return paths[0]
    if os.path.exists("/sys/devices/platform/acer-wmi/nitro_sense/thermal_profile"):
        return "/sys/devices/platform/acer-wmi/nitro_sense/thermal_profile"
    return None

def get_fan_speed_path():
    for p in ["/sys/devices/platform/acer-wmi/nitro_sense/fan_speed",
              "/sys/devices/platform/acer-wmi/predator_sense/fan_speed"]:
        if os.path.exists(p):
            return p
    return None

def read_current_profile():
    p = get_profile_path()
    if p and os.path.exists(p):
        try:
            with open(p, "r") as f:
                val = f.read().strip()
                if val in ["balanced-performance", "performance"]:
                    return "performance"
                return val
        except Exception:
            pass
    return "balanced"

def write_fan_speed(cpu_val, gpu_val):
    p = get_fan_speed_path()
    if p and os.path.exists(p):
        try:
            with open(p, "w") as f:
                f.write(f"{cpu_val},{gpu_val}\n")
        except Exception:
            pass

def detect_cpu_name():
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if "model name" in line:
                    raw = line.split(":", 1)[1].strip()
                    clean = raw.replace("AMD Ryzen ", "R").replace("Intel(R) Core(TM) ", "")
                    return f"CPU • {clean.split(' with')[0]}"
    except Exception:
        pass
    return "CPU • AMD Ryzen"

def detect_gpu_name():
    # 1. Try lspci first (Works even when dGPU is in runtime suspend / sleeping)
    try:
        out = subprocess.check_output(["lspci"], timeout=1, text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            if "VGA" in line or "3D" in line or "Display" in line:
                if "NVIDIA" in line:
                    if "[" in line and "]" in line:
                        bracket = line.split("[")[1].split("]")[0]
                        clean = bracket.replace("GeForce ", "").replace("Laptop", "").strip()
                        return f"GPU • {clean}"
                    else:
                        parts = line.split("NVIDIA Corporation")
                        if len(parts) > 1:
                            clean = parts[1].strip().split("(")[0].replace("GeForce", "").strip()
                            return f"GPU • {clean}"
    except Exception:
        pass

    # 2. Fallback to nvidia-smi if active
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            timeout=1, text=True, stderr=subprocess.DEVNULL
        )
        name = out.strip().replace("NVIDIA GeForce ", "").replace(" Laptop GPU", "").strip()
        if name:
            return f"GPU • {name}"
    except Exception:
        pass

    return "GPU • NVIDIA GPU"

def get_cpu_temperature():
    try:
        for hwmon in glob.glob("/sys/class/hwmon/hwmon*"):
            name_path = os.path.join(hwmon, "name")
            if os.path.exists(name_path):
                with open(name_path, "r") as f:
                    if "k10temp" in f.read():
                        temp_path = os.path.join(hwmon, "temp1_input")
                        if os.path.exists(temp_path):
                            with open(temp_path, "r") as tf:
                                return float(tf.read().strip()) / 1000.0
    except Exception:
        pass
    return None

def get_nvidia_pci_path():
    for dev in glob.glob("/sys/bus/pci/devices/*"):
        vendor_file = os.path.join(dev, "vendor")
        if os.path.exists(vendor_file):
            try:
                with open(vendor_file, "r") as f:
                    if f.read().strip() == "0x10de":
                        class_file = os.path.join(dev, "class")
                        if os.path.exists(class_file):
                            with open(class_file, "r") as cf:
                                if cf.read().strip().startswith("0x03"):
                                    return dev
            except Exception:
                pass
    return None

NVIDIA_PCI_PATH = get_nvidia_pci_path()

def is_gpu_suspended():
    if not NVIDIA_PCI_PATH:
        return False
    status_file = os.path.join(NVIDIA_PCI_PATH, "power/runtime_status")
    if os.path.exists(status_file):
        try:
            with open(status_file, "r") as f:
                return f.read().strip() == "suspended"
        except Exception:
            pass
    return False

def get_gpu_temperature():
    global LAST_GPU_QUERY_TIME, CACHED_GPU_TEMP

    if is_gpu_suspended():
        CACHED_GPU_TEMP = None
        return "suspended"

    current_time = time.time()
    if current_time - LAST_GPU_QUERY_TIME < 6 and CACHED_GPU_TEMP is not None:
        return CACHED_GPU_TEMP

    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            timeout=1, text=True, stderr=subprocess.DEVNULL
        )
        LAST_GPU_QUERY_TIME = current_time
        CACHED_GPU_TEMP = float(out.strip())
        return CACHED_GPU_TEMP
    except Exception:
        pass
    return None

def get_fan_rpms(last_cpu=0, last_gpu=0):
    cpu_rpm, gpu_rpm = last_cpu, last_gpu
    try:
        for hwmon in glob.glob("/sys/devices/platform/acer-wmi/hwmon/hwmon*"):
            f1 = os.path.join(hwmon, "fan1_input")
            f2 = os.path.join(hwmon, "fan2_input")
            if os.path.exists(f1):
                try:
                    with open(f1, "r") as f:
                        val = int(f.read().strip())
                        if val >= 0: cpu_rpm = val
                except Exception:
                    pass
            if os.path.exists(f2):
                try:
                    with open(f2, "r") as f:
                        val = int(f.read().strip())
                        if val >= 0: gpu_rpm = val
                except Exception:
                    pass
    except Exception:
        pass
    return cpu_rpm, gpu_rpm

# ----------------- UI Class -----------------

class NitroSenseApp(QWidget):
    def __init__(self):
        super().__init__()
        self.active_profile = read_current_profile()
        self.fan_mode = "auto"

        self.last_cpu_rpm = 0
        self.last_gpu_rpm = 0

        self.saved_sync_fans = True
        self.saved_custom_cpu = 50
        self.saved_custom_gpu = 50

        self.initUI()
        self.initTray()
        self.initServer()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_telemetry)
        self.timer.start(1000)
        self.update_telemetry()

    def initServer(self):
        self.server = QLocalServer(self)
        self.server.removeServer(SOCKET_NAME)
        self.server.listen(SOCKET_NAME)
        self.server.newConnection.connect(self.handle_ipc)

    def handle_ipc(self):
        conn = self.server.nextPendingConnection()
        if conn:
            conn.waitForReadyRead(300)
            self.toggle_window()
            conn.disconnectFromServer()

    def toggle_window(self):
        if self.isVisible() and not self.isMinimized() and self.isActiveWindow():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def initUI(self):
        self.setWindowTitle('NitroSense')
        self.setFixedSize(490, 560)

        icon_path = os.path.expanduser("~/.local/share/icons/nitro-fan.svg")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(14)

        # CPU Card
        self.card_cpu = QFrame()
        self.card_cpu.setObjectName("cpuCard")
        cpu_layout = QVBoxLayout(self.card_cpu)
        cpu_layout.setContentsMargins(16, 14, 16, 14)
        cpu_layout.setSpacing(6)
        
        self.lbl_cpu_title = QLabel(detect_cpu_name())
        self.lbl_cpu_title.setObjectName("cpuTitle")
        self.lbl_cpu_temp = QLabel("-- °C")
        self.lbl_cpu_temp.setObjectName("tempVal")
        self.bar_cpu = QProgressBar()
        self.bar_cpu.setObjectName("cpuBar")
        self.bar_cpu.setRange(0, 100)
        self.bar_cpu.setTextVisible(True)
        self.bar_cpu.setFormat("0 RPM (0%)")

        cpu_layout.addWidget(self.lbl_cpu_title)
        cpu_layout.addWidget(self.lbl_cpu_temp)
        cpu_layout.addWidget(self.bar_cpu)
        cards_layout.addWidget(self.card_cpu)

        # GPU Card
        self.card_gpu = QFrame()
        self.card_gpu.setObjectName("gpuCard")
        gpu_layout = QVBoxLayout(self.card_gpu)
        gpu_layout.setContentsMargins(16, 14, 16, 14)
        gpu_layout.setSpacing(6)

        self.lbl_gpu_title = QLabel(detect_gpu_name())
        self.lbl_gpu_title.setObjectName("gpuTitle")
        self.lbl_gpu_temp = QLabel("-- °C")
        self.lbl_gpu_temp.setObjectName("tempVal")
        self.bar_gpu = QProgressBar()
        self.bar_gpu.setObjectName("gpuBar")
        self.bar_gpu.setRange(0, 100)
        self.bar_gpu.setTextVisible(True)
        self.bar_gpu.setFormat("0 RPM (0%)")

        gpu_layout.addWidget(self.lbl_gpu_title)
        gpu_layout.addWidget(self.lbl_gpu_temp)
        gpu_layout.addWidget(self.bar_gpu)
        cards_layout.addWidget(self.card_gpu)

        main_layout.addLayout(cards_layout)

        # Thermal Profiles
        lbl_sec1 = QLabel("THERMAL PERFORMANCE PROFILE")
        lbl_sec1.setObjectName("sectionHeader")
        main_layout.addWidget(lbl_sec1)

        prof_layout = QHBoxLayout()
        prof_layout.setSpacing(10)
        self.btn_quiet = QPushButton("Quiet")
        self.btn_balanced = QPushButton("Balanced")
        self.btn_perf = QPushButton("Performance")

        self.btn_quiet.clicked.connect(lambda: self.set_profile("quiet"))
        self.btn_balanced.clicked.connect(lambda: self.set_profile("balanced"))
        self.btn_perf.clicked.connect(lambda: self.set_profile("performance"))

        prof_layout.addWidget(self.btn_quiet)
        prof_layout.addWidget(self.btn_balanced)
        prof_layout.addWidget(self.btn_perf)
        main_layout.addLayout(prof_layout)

        # Fan Management
        lbl_sec2 = QLabel("FAN SPEED CONTROL")
        lbl_sec2.setObjectName("sectionHeader")
        main_layout.addWidget(lbl_sec2)

        fan_modes_layout = QHBoxLayout()
        fan_modes_layout.setSpacing(10)
        self.btn_fan_auto = QPushButton("Auto")
        self.btn_fan_max = QPushButton("Maximum")
        self.btn_fan_man = QPushButton("Custom")

        self.btn_fan_auto.clicked.connect(self.mode_fan_auto)
        self.btn_fan_max.clicked.connect(self.mode_fan_max)
        self.btn_fan_man.clicked.connect(self.mode_fan_manual)

        fan_modes_layout.addWidget(self.btn_fan_auto)
        fan_modes_layout.addWidget(self.btn_fan_max)
        fan_modes_layout.addWidget(self.btn_fan_man)
        main_layout.addLayout(fan_modes_layout)

        self.lbl_quiet_note = QLabel("")
        self.lbl_quiet_note.setObjectName("quietBadge")
        self.lbl_quiet_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_quiet_note.setFixedHeight(28)
        main_layout.addWidget(self.lbl_quiet_note)

        # Manual Custom Box
        self.man_box = QFrame()
        self.man_box.setObjectName("manBox")
        man_layout = QVBoxLayout(self.man_box)
        man_layout.setContentsMargins(16, 14, 16, 14)
        man_layout.setSpacing(12)

        self.btn_sync = QPushButton("Linked Fan Speeds")
        self.btn_sync.setObjectName("syncBtn")
        self.btn_sync.setCheckable(True)
        self.btn_sync.setChecked(self.saved_sync_fans)
        self.btn_sync.clicked.connect(self.toggle_fan_sync)
        man_layout.addWidget(self.btn_sync)

        cpu_row = QHBoxLayout()
        self.lbl_scpu = QLabel("CPU: 50%")
        self.lbl_scpu.setObjectName("sliderLabel")
        self.lbl_scpu.setFixedWidth(95)
        self.slider_cpu = QSlider(Qt.Orientation.Horizontal)
        self.slider_cpu.setObjectName("cpuSlider")
        self.slider_cpu.setRange(1, 100)
        self.slider_cpu.setValue(self.saved_custom_cpu)
        self.slider_cpu.valueChanged.connect(self.on_cpu_slider_change)
        cpu_row.addWidget(self.lbl_scpu)
        cpu_row.addWidget(self.slider_cpu)
        man_layout.addLayout(cpu_row)

        gpu_row = QHBoxLayout()
        self.lbl_sgpu = QLabel("GPU: 50%")
        self.lbl_sgpu.setObjectName("sliderLabel")
        self.lbl_sgpu.setFixedWidth(95)
        self.slider_gpu = QSlider(Qt.Orientation.Horizontal)
        self.slider_gpu.setObjectName("gpuSlider")
        self.slider_gpu.setRange(1, 100)
        self.slider_gpu.setValue(self.saved_custom_gpu)
        self.slider_gpu.valueChanged.connect(self.on_gpu_slider_change)
        gpu_row.addWidget(self.lbl_sgpu)
        gpu_row.addWidget(self.slider_gpu)
        man_layout.addLayout(gpu_row)

        main_layout.addWidget(self.man_box)

        self.apply_theme()
        self.refresh_ui_state()

    def apply_theme(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #10121a;
                color: #e4e7f2;
                font-family: 'SF Pro Display', 'Inter', -apple-system, sans-serif;
                font-size: 13px;
            }
            QLabel#sectionHeader {
                font-size: 11px;
                font-weight: 800;
                color: #636e88;
                letter-spacing: 0.8px;
                margin-top: 2px;
            }
            QFrame#cpuCard, QFrame#gpuCard {
                background-color: #161924;
                border: 1px solid #23283a;
                border-radius: 12px;
            }
            QLabel#cpuTitle {
                font-weight: 800;
                font-size: 12px;
                color: #ff5252;
                letter-spacing: 0.4px;
            }
            QLabel#gpuTitle {
                font-weight: 800;
                font-size: 12px;
                color: #00e676;
                letter-spacing: 0.4px;
            }
            QLabel#tempVal {
                font-size: 32px;
                font-weight: 900;
                color: #ffffff;
                margin: 2px 0;
            }
            QLabel#quietBadge {
                font-weight: 700;
                font-size: 12px;
                border-radius: 6px;
            }
            QFrame#manBox {
                background-color: #141622;
                border: 1px solid #1f2334;
                border-radius: 12px;
            }
            QLabel#sliderLabel {
                font-weight: 700;
                font-size: 12px;
                color: #b0bad4;
            }
            QPushButton {
                background-color: #1c2132;
                border: 1px solid #2b334a;
                border-radius: 8px;
                padding: 11px 10px;
                font-weight: 700;
                font-size: 13px;
                color: #cfd5e6;
            }
            QPushButton:hover {
                background-color: #252b40;
                border-color: #3f4b6c;
                color: #ffffff;
            }
            QPushButton:disabled {
                background-color: #13151f;
                border: 1px solid #1a1e2b;
                color: #3b4257;
            }
            QPushButton#syncBtn {
                background-color: #1b1f2e;
                border: 1px solid #2c354e;
                padding: 8px;
                font-size: 12px;
                font-weight: 700;
                color: #9ea8c2;
            }
            QPushButton#syncBtn:checked {
                background-color: #2a1c3d;
                border: 1px solid #a55eea;
                color: #e0b0ff;
            }
            QPushButton#syncBtn:disabled {
                background-color: #13151f;
                border: 1px solid #1a1e2b;
                color: #3b4257;
            }
            QLabel:disabled {
                color: #3b4257;
            }
            QProgressBar {
                background-color: #0b0d13;
                border: 1px solid #1c202d;
                border-radius: 5px;
                height: 18px;
                text-align: center;
                font-size: 11px;
                font-weight: 800;
                color: #ffffff;
            }
            QProgressBar::chunk {
                border-radius: 4px;
                margin: 0px;
            }
            QProgressBar#cpuBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #d63031, stop:1 #ff5252);
            }
            QProgressBar#gpuBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00b894, stop:1 #00e676);
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #23293b;
                border-radius: 3px;
            }
            QSlider::groove:horizontal:disabled {
                background: #171a25;
            }
            QSlider::handle:horizontal {
                background: #3b82f6;
                width: 18px;
                margin: -6px 0;
                border-radius: 9px;
            }
            QSlider#cpuSlider::handle:horizontal {
                background: #ff5252;
            }
            QSlider#gpuSlider::handle:horizontal {
                background: #00e676;
            }
            QSlider#cpuSlider::handle:horizontal:disabled,
            QSlider#gpuSlider::handle:horizontal:disabled,
            QSlider::handle:horizontal:disabled {
                background: #282e3f;
            }
        """)

    def set_profile(self, profile):
        self.active_profile = profile

        ppd_map = {
            "quiet": "power-saver",
            "balanced": "balanced",
            "performance": "performance"
        }
        if profile in ppd_map:
            subprocess.Popen(["powerprofilesctl", "set", ppd_map[profile]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if profile == "quiet":
            self.fan_mode = "auto"
            write_fan_speed(0, 0)

        self.refresh_ui_state()

    def mode_fan_auto(self):
        self.fan_mode = "auto"
        write_fan_speed(0, 0)
        self.refresh_ui_state()

    def mode_fan_max(self):
        if self.active_profile != "quiet":
            self.fan_mode = "max"
            write_fan_speed(100, 100)
            self.refresh_ui_state()

    def mode_fan_manual(self):
        if self.active_profile != "quiet":
            self.fan_mode = "manual"
            cpu_spd = self.saved_custom_cpu
            gpu_spd = self.saved_custom_cpu if self.saved_sync_fans else self.saved_custom_gpu
            write_fan_speed(cpu_spd, gpu_spd)
            self.refresh_ui_state()

    def toggle_fan_sync(self, checked):
        self.saved_sync_fans = checked
        self.btn_sync.setText("Linked Fan Speeds" if checked else "Independent Fan Speeds")
        
        if self.fan_mode == "manual":
            if checked:
                self.saved_custom_gpu = self.saved_custom_cpu
                self.slider_gpu.blockSignals(True)
                self.slider_gpu.setValue(self.saved_custom_cpu)
                self.slider_gpu.blockSignals(False)
                self.lbl_sgpu.setText(f"GPU: {self.saved_custom_cpu}% (Linked)")
                write_fan_speed(self.saved_custom_cpu, self.saved_custom_cpu)
            else:
                self.lbl_sgpu.setText(f"GPU: {self.saved_custom_gpu}%")
                write_fan_speed(self.saved_custom_cpu, self.saved_custom_gpu)

        self.slider_gpu.setEnabled(self.fan_mode == "manual" and not checked)
        self.lbl_sgpu.setEnabled(self.fan_mode == "manual" and not checked)

    def on_cpu_slider_change(self, val):
        self.saved_custom_cpu = val
        self.lbl_scpu.setText(f"CPU: {val}%")
        if self.saved_sync_fans:
            self.saved_custom_gpu = val
            self.slider_gpu.blockSignals(True)
            self.slider_gpu.setValue(val)
            self.slider_gpu.blockSignals(False)
            self.lbl_sgpu.setText(f"GPU: {val}% (Linked)")
            if self.fan_mode == "manual":
                write_fan_speed(val, val)
        else:
            if self.fan_mode == "manual":
                write_fan_speed(val, self.saved_custom_gpu)

    def on_gpu_slider_change(self, val):
        if not self.saved_sync_fans:
            self.saved_custom_gpu = val
            self.lbl_sgpu.setText(f"GPU: {val}%")
            if self.fan_mode == "manual":
                write_fan_speed(self.saved_custom_cpu, val)

    def refresh_ui_state(self):
        base_btn = "background-color: #1c2132; border: 1px solid #2b334a; color: #cfd5e6;"
        disabled_btn = "background-color: #13151f; border: 1px solid #1a1e2b; color: #3b4257; font-weight: 700;"
        
        quiet_act = "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0984e3, stop:1 #00cec9); color: #ffffff; border: 1px solid #74b9ff; font-weight: 800;"
        balanced_act = "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2563eb, stop:1 #3b82f6); color: #ffffff; border: 1px solid #60a5fa; font-weight: 800;"
        perf_act = "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #d63031, stop:1 #ff5252); color: #ffffff; border: 1px solid #ff7675; font-weight: 800;"

        self.btn_quiet.setStyleSheet(quiet_act if self.active_profile == "quiet" else base_btn)
        self.btn_balanced.setStyleSheet(balanced_act if self.active_profile == "balanced" else base_btn)
        self.btn_perf.setStyleSheet(perf_act if self.active_profile == "performance" else base_btn)

        is_quiet = (self.active_profile == "quiet")
        if is_quiet:
            self.fan_mode = "auto"
            self.lbl_quiet_note.setText("Fan controls locked for quiet profile")
            self.lbl_quiet_note.setStyleSheet("background-color: #141924; border: 1px solid #1f2738; color: #70a1ff;")
            self.btn_fan_auto.setEnabled(False)
            self.btn_fan_max.setEnabled(False)
            self.btn_fan_man.setEnabled(False)
            
            locked_auto_style = "background-color: #19202e; border: 1px solid #232d40; color: #4e678a; font-weight: 800;"
            self.btn_fan_auto.setStyleSheet(locked_auto_style)
            self.btn_fan_max.setStyleSheet(disabled_btn)
            self.btn_fan_man.setStyleSheet(disabled_btn)
        else:
            self.lbl_quiet_note.setText("")
            self.lbl_quiet_note.setStyleSheet("background: transparent; border: none;")
            self.btn_fan_auto.setEnabled(True)
            self.btn_fan_max.setEnabled(True)
            self.btn_fan_man.setEnabled(True)

            fan_auto_act = "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2563eb, stop:1 #3b82f6); color: #ffffff; border: 1px solid #60a5fa; font-weight: 800;"
            fan_max_act = "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #d63031, stop:1 #ff5252); color: #ffffff; border: 1px solid #ff7675; font-weight: 800;"
            fan_man_act = "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6c5ce7, stop:1 #a29bfe); color: #ffffff; border: 1px solid #dcdde1; font-weight: 800;"

            self.btn_fan_auto.setStyleSheet(fan_auto_act if self.fan_mode == "auto" else base_btn)
            self.btn_fan_max.setStyleSheet(fan_max_act if self.fan_mode == "max" else base_btn)
            self.btn_fan_man.setStyleSheet(fan_man_act if self.fan_mode == "manual" else base_btn)

        is_manual = (self.fan_mode == "manual" and not is_quiet)
        
        self.btn_sync.setEnabled(is_manual)
        self.slider_cpu.setEnabled(is_manual)
        self.lbl_scpu.setEnabled(is_manual)
        
        self.slider_gpu.setEnabled(is_manual and not self.saved_sync_fans)
        self.lbl_sgpu.setEnabled(is_manual and not self.saved_sync_fans)

        if not is_manual:
            self.btn_sync.setChecked(self.saved_sync_fans)
            if self.fan_mode == "auto":
                self.lbl_scpu.setText("CPU: Auto")
                self.lbl_sgpu.setText("GPU: Auto")
            elif self.fan_mode == "max":
                self.lbl_scpu.setText("CPU: 100%")
                self.lbl_sgpu.setText("GPU: 100%")
        else:
            self.lbl_scpu.setText(f"CPU: {self.saved_custom_cpu}%")
            if self.saved_sync_fans:
                self.lbl_sgpu.setText(f"GPU: {self.saved_custom_cpu}% (Linked)")
            else:
                self.lbl_sgpu.setText(f"GPU: {self.saved_custom_gpu}%")

    def initTray(self):
        tray_icon_path = os.path.expanduser("~/.local/share/icons/nitro-tray.svg")
        if not os.path.exists(tray_icon_path):
            tray_icon_path = os.path.expanduser("~/.local/share/icons/nitro-fan.svg")

        self.tray = QSystemTrayIcon(QIcon(tray_icon_path), self)
        self.tray.setToolTip("NitroSense")

        menu = QMenu()
        menu.addAction("Quiet Mode").triggered.connect(lambda: self.set_profile("quiet"))
        menu.addAction("Balanced Mode").triggered.connect(lambda: self.set_profile("balanced"))
        menu.addAction("Performance Mode").triggered.connect(lambda: self.set_profile("performance"))
        menu.addSeparator()
        menu.addAction("Auto Fan").triggered.connect(self.mode_fan_auto)
        menu.addAction("Max Fan").triggered.connect(self.mode_fan_max)
        menu.addSeparator()
        menu.addAction("Show / Hide").triggered.connect(self.toggle_window)
        menu.addAction("Quit").triggered.connect(QApplication.instance().quit)

        self.tray.setContextMenu(menu)
        self.tray.show()

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def update_telemetry(self):
        current_hw_profile = read_current_profile()
        if current_hw_profile != self.active_profile:
            self.active_profile = current_hw_profile
            if current_hw_profile == "quiet":
                self.fan_mode = "auto"
                write_fan_speed(0, 0)
            self.refresh_ui_state()

        cpu_t = get_cpu_temperature()
        gpu_t = get_gpu_temperature()

        self.lbl_cpu_temp.setText(f"{cpu_t:.1f} °C" if cpu_t is not None else "-- °C")

        # GPU Sleep / Active State
        if gpu_t == "suspended":
            self.lbl_gpu_temp.setText("Sleep")
            self.lbl_gpu_temp.setStyleSheet("color: #636e88; font-size: 26px; font-weight: 900; margin: 5px 0;")
            self.lbl_gpu_title.setStyleSheet("color: #636e88; font-weight: 800; font-size: 12px; letter-spacing: 0.4px;")
            self.card_gpu.setStyleSheet("QFrame#gpuCard { background-color: #12141c; border: 1px dashed #23283a; border-radius: 12px; }")
            self.bar_gpu.setValue(0)
            self.bar_gpu.setFormat("GPU Suspended")
        else:
            self.lbl_gpu_temp.setText(f"{gpu_t:.0f} °C" if gpu_t is not None else "-- °C")
            self.lbl_gpu_temp.setStyleSheet("color: #ffffff; font-size: 32px; font-weight: 900; margin: 2px 0;")
            self.lbl_gpu_title.setStyleSheet("color: #00e676; font-weight: 800; font-size: 12px; letter-spacing: 0.4px;")
            self.card_gpu.setStyleSheet("QFrame#gpuCard { background-color: #161924; border: 1px solid #23283a; border-radius: 12px; }")

        # Fan Speeds
        self.last_cpu_rpm, self.last_gpu_rpm = get_fan_rpms(self.last_cpu_rpm, self.last_gpu_rpm)
        cpu_rpm = self.last_cpu_rpm
        gpu_rpm = self.last_gpu_rpm

        cpu_pct = min(100, max(0, int(round((cpu_rpm / 8000.0) * 100)))) if cpu_rpm > 0 else 0
        self.bar_cpu.setValue(cpu_pct)
        self.bar_cpu.setFormat(f"{cpu_rpm} RPM ({cpu_pct}%)" if cpu_rpm > 0 else "0 RPM (0%)")

        if gpu_t != "suspended":
            gpu_pct = min(100, max(0, int(round((gpu_rpm / 8000.0) * 100)))) if gpu_rpm > 0 else 0
            self.bar_gpu.setValue(gpu_pct)
            self.bar_gpu.setFormat(f"{gpu_rpm} RPM ({gpu_pct}%)" if gpu_rpm > 0 else "0 RPM (0%)")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setApplicationName("NitroSense")
    app.setApplicationDisplayName("NitroSense")
    app.setDesktopFileName("nitrosense")

    socket = QLocalSocket()
    socket.connectToServer(SOCKET_NAME)
    if socket.waitForConnected(300):
        socket.write(b"toggle\n")
        socket.waitForBytesWritten(300)
        sys.exit(0)

    app.setQuitOnLastWindowClosed(False)
    ex = NitroSenseApp()
    ex.show()
    sys.exit(app.exec())
