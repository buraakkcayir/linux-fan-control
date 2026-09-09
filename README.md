# NitroSense Linux

NitroSense Linux is a lightweight hardware tuning and power-management utility for supported Acer Nitro laptops running Linux. It combines a PyQt6 desktop dashboard with an SCX auto-profile daemon so the system can automatically switch between quiet, balanced, and performance behavior based on the active power profile.

This project is an independent, unofficial project and is not affiliated with, endorsed by, or sponsored by Acer, AMD, or the sched-ext project maintainers.

## Interface Preview

<p align="center">
  <img src="assets/nitro-active.png" width="45%" alt="NitroSense active profile" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="assets/nitro-sleep.png" width="45%" alt="NitroSense suspended GPU state" />
</p>

## Purpose and Scope

This project is designed for laptop owners who want a simplified, low-overhead way to:

- control thermal profiles and fan behavior,
- synchronize power limits and scheduler policy with the active desktop power profile,
- reduce fan noise while preserving performance,
- maintain a minimal user-space interface without custom kernel patching beyond the Acer WMI support layer.

### Out of Scope

- General-purpose desktop tuning for all laptops,
- support for non-Acer hardware without matching WMI nodes,
- guaranteed compatibility with every Linux distribution or kernel configuration,
- automatic repair of broken or unsupported hardware drivers.

## Architecture

```text
[NitroSense GUI (PyQt6)]
       │
       ▼ (changes mode: Quiet / Balanced / Performance)
[power-profiles-daemon]
       │
       ▼ (D-Bus signal: /net/hadess/PowerProfiles)
[SCX Auto-Profile Daemon (scx-auto-profile.sh)]
       ├── sched-ext scheduler switching (scx_bpfland / scx_lavd / default)
       ├── AMD CPU Boost policy
       ├── AMD EPP tuning
       ├── PCIe ASPM policy control
       └── Acer WMI thermal/fan profile writes
```

## Features

- PyQt6 telemetry dashboard with CPU/GPU temperatures and RPM monitoring
- dynamic detection of laptop hardware and NVIDIA GPU state
- linked or independent fan control
- automatic transitions between quiet, balanced, and performance behavior
- single-instance tray/window toggling using local IPC sockets
- compatibility with power-profile changes from desktop environments

## Supported Hardware and Platforms

### Tested Platforms

- Acer Nitro 5 / Nitro 7 class laptops using Acer WMI support
- AMD Ryzen systems with NVIDIA GPU configurations
- Arch Linux, CachyOS, and other distributions with `power-profiles-daemon` and `scxctl` available

### Required Hardware Support

The project depends on the Linux Acer WMI path exposed by the relevant kernel drivers or a patched module such as `linuwu-sense-dkms` or `facer`.

## Requirements

### System and Kernel Requirements

- Linux kernel with Acer WMI support or a compatible patched driver
- `power-profiles-daemon`
- `scxctl` / `scx-scheds` for sched-ext switching
- Python 3 and PyQt6

### Required Packages

On Arch-based systems:

```bash
sudo pacman -S python-pyqt6 power-profiles-daemon scx-scheds
```

On other distributions, install the equivalent packages using the distro package manager.

## Installation

Use a writable checkout path and avoid hard-coded personal home directories in scripts or service files.

```bash
PROJECT_DIR="/path/to/project"
git clone https://github.com/your-org/nitrosense-linux.git "$PROJECT_DIR"
cd "$PROJECT_DIR"
```

### 1. Install Udev Permissions

Apply the bundled rules so a regular user can access the Acer WMI fan and thermal nodes without root privileges.

```bash
sudo cp 99-nitrosense.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### 2. Run the GUI

```bash
./nitrosense-gui.py
```

You can also bind the launcher to a custom keyboard shortcut from your desktop environment.

### 3. Enable the Background Daemon

```bash
mkdir -p ~/.config/systemd/user
cp scx-auto-profile.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now scx-auto-profile.service
```

If your checkout lives outside the default home directory, update the service file to point to the correct script path before enabling it.

## Configuration

| Variable / File | Purpose | Notes |
| --- | --- | --- |
| `scx-auto-profile.sh` | scheduler and thermal profile switcher | runs on profile changes and startup |
| `scx-auto-profile.service` | systemd user service | uses a portable path or a symlinked install path |
| `99-nitrosense.rules` | udev permissions | grants write access to hardware sysfs nodes |
| `powerprofilesctl` | active power profile source | used to decide quiet / balanced / performance mode |

## Usage Examples

### Start the GUI manually

```bash
./nitrosense-gui.py
```

### Start the daemon in the current user session

```bash
systemctl --user start scx-auto-profile.service
```

### Confirm the active profile

```bash
powerprofilesctl get
```

## Distribution and Environment Notes

- Arch and CachyOS are the primary targets for this project.
- Thin desktop environments usually provide `power-profiles-daemon` integration automatically.
- If `scxctl` is unavailable, the daemon falls back to a safe no-op mode instead of invoking unsupported commands.
- Kernels without the required Acer WMI support will not expose the needed sysfs nodes.

## Troubleshooting

### Fan control or thermal profile changes do not apply

- verify the Acer WMI or patched driver is loaded,
- check `dmesg` and `journalctl -b` for WMI errors,
- reload udev rules and confirm the expected sysfs entries exist,
- confirm the script runs with the same user context as the desktop session.

### `powerprofilesctl` is unavailable

- install `power-profiles-daemon`,
- verify the service is running,
- test the system profile switcher using the distro's power profile interface.

### `scxctl` is unavailable

- install the `scx-scheds` package or the equivalent scheduler bundle,
- check that the `scx` kernel modules are available,
- keep the daemon enabled only on systems that support sched-ext.

## Security Notes

- the project does not log credentials or secrets,
- all sysfs writes are limited to the hardware control paths required by Acer WMI and the CPU governor interfaces,
- shell command execution is intentionally constrained to a fixed set of allowed scheduler actions,
- avoid running the daemon as root unless you explicitly need hardware access at the system level.

## Uninstall

Remove the installed udev rule and disable the user service:

```bash
sudo rm -f /etc/udev/rules.d/99-nitrosense.rules
systemctl --user disable --now scx-auto-profile.service
rm -f ~/.config/systemd/user/scx-auto-profile.service
```

## License

MIT License

Copyright (c) 2026 buraakkcayir

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Third-Party Dependencies

- PyQt6
- power-profiles-daemon
- scx-scheds / scxctl
- Acer WMI kernel driver support from the platform vendor or a compatible patched module
- platform-specific Linux sysfs interfaces exposed by the kernel and hardware drivers
