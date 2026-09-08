# NitroSense Linux & SCX Auto-Profile Suite

A comprehensive, low-overhead hardware management suite engineered for **Acer Nitro laptops running Linux (specifically optimized for CachyOS and Arch Linux)**.

This project pairs a modern **PyQt6 NitroSense GUI** with an automated **SCX (sched-ext) scheduler and hardware daemon** to provide Windows-level fan and power control on Linux.

---

## Architecture & Integration

```text
[NitroSense GUI (PyQt6)] 
       │
       ▼ (Changes profile: Quiet / Balanced / Performance)
[power-profiles-daemon]
       │
       ▼ (D-Bus signal: /net/hadess/PowerProfiles)
[SCX Auto-Profile Daemon (scx-auto-profile.sh)]
       ├── Sched-Ext Schedulers (scx_bpfland / scx_lavd / BORE default)
       ├── AMD CPU Turbo Boost (Toggled OFF in Quiet mode)
       ├── AMD EPP (Energy Performance Preference)
       ├── PCIe ASPM Power Management
       └── Acer WMI Thermal Profiles (/sys/devices/platform/acer-wmi)
```

---

## ✨ Features

- **PyQt6 Dark Interface:** Modern dark-themed telemetry dashboard with CPU & GPU temperatures, live fan RPM meters, and system tray integration.
- **Dynamic Hardware Detection:** Automatically detects CPU and NVIDIA GPU models; intelligently tracks GPU sleep/runtime power status to prevent unnecessary wakeups.
- **Synchronized & Custom Fan Sliders:** Supports Auto, Maximum, and Linked/Independent custom fan speeds.
- **SCX Scheduler Automation:**
  - **Performance:** Engages `scx_bpfland` for high-throughput gaming.
  - **Power-Saver:** Engages `scx_lavd -m powersave` and disables CPU Boost for absolute quiet and cool operation.
  - **Balanced:** Reverts to the default kernel scheduler (e.g., BORE).
- **Single Instance Toggle:** Pressing the shortcut again toggles the window via local IPC sockets without launching duplicate instances.

---

## 📦 Prerequisites

Install dependencies (Arch Linux / CachyOS):
```bash
paru -S python-pyqt6 power-profiles-daemon scx-scheds
```

---

## 🚀 Installation & Usage

### 1. Run NitroSense GUI
```bash
./nitrosense-gui.py
```
*(Bind this to your desired hotkey, e.g. dedicated NitroSense button or global shortcut).*

### 2. Enable Background Auto-Profile Daemon (systemd)
```bash
mkdir -p ~/.config/systemd/user
cp scx-auto-profile.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now scx-auto-profile.service
```

---

## 📜 License
MIT License
