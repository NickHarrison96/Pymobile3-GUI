# Pymobile3-GUI

**Standalone iOS forensic & developer toolkit** — extracted from RootForgeKit.

A native-feel PySide6 desktop application for Windows 10/11 with Mica/Acrylic backdrop, full-page workspaces, and real-time operation telemetry.

## Features

- **Device Overview** — Hardware specs, battery, activation state, developer mode status + lockdown control panel (rename, assistive touch, Wi-Fi connections, battery detail)
- **Files & Applications** — AFC file browser, installed apps inspector, DCIM media quick access, crash reports explorer (browse, parse, export, pull)
- **Forensic Acquisition** — Logical, Logical+, PRFS modes with live progress, case metadata, TAR archiving
- **Developer Tools** — Progressive readiness pipeline (Dev Mode → DDI → RSD Tunnel) + DVT instruments (process monitor with search/kill/launch, bundle-id lookup, system monitor, screenshot, GPS simulation)
- **Recovery & Restore** — IPSW firmware flashing via `idevicerestore` + interactive Recovery/DFU hardware guides
- **Live Syslog** — Streaming console with filtering, pause/resume, export
- **SSH Ramdisk** *(in development)* — checkm8 ramdisk creation and boot for A7-A11 devices

## Requirements

- Python 3.10+
- Physical iOS device (iOS 17+ needs RSD tunnel)
- Administrator/root for tunnel interface creation (iOS 17+)

## Quick Start

```bash
git clone <repo-url>
cd Pymobile3-GUI
python -m venv .venv
.venv\Scripts\activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m pymobile3_gui.main
```

## Building Standalone Executable (Windows)

```bash
pip install pyinstaller
python -m PyInstaller pymobile3_gui.spec --noconfirm
```

Produces `dist/Pymobile3-GUI/Pymobile3-GUI.exe` (onedir bundle).

## Architecture

```
pymobile3_gui/
├── main.py                    # Entry point, NativeFramelessWindow
├── core/
│   ├── device_poller.py       # Async usbmux/lockdown device discovery
│   ├── task_manager.py        # Centralized long-running task orchestration
│   ├── process_manager.py     # Single-instance enforcement + child process cleanup
│   └── backend/
│       ├── backup_engine.py   # Forensic acquisition (Logical/Logical+/PRFS)
│       ├── tunnel_manager.py  # iOS 17+ RSD tunnel (tunneld lifecycle)
│       ├── file_system.py     # AFC wrapper (thread-safe)
│       ├── paths.py           # Frozen-aware path resolution
│       ├── elevation.py       # UAC/admin helpers
│       ├── process_runner.py  # QProcess streaming runner
│       └── resource_manager.py# Thread pool, subprocess, crash handler
├── views/                     # Full-page workspaces (6 views)
├── ui/                        # Reusable widgets (sidebar, dock, drawer, theme)
└── assets/                    # Fonts, SVG icons
```

## iOS 17+ Developer Services

iOS 17+ moved all developer services (DVT instruments, proclist, screenshot, location simulation, app launch) behind RemoteXPC, reachable only through an RSD tunnel.

**Developer view readiness pipeline:**
1. **Enable Dev Mode** — `amfi enable-developer-mode` (device reboots)
2. **Mount DDI** — `mounter auto-mount` (Developer Disk Image)
3. **Start Tunnel** — Launches `pymobiledevice3 remote tunneld` elevated

When "Developer services" reads green, DVT tabs are functional.

## SSH Ramdisk (checkm8 Devices)

The SSH Ramdisk feature (in development on `feature/sshrd-ramdisk`) ports [SSHRD_Script](https://github.com/verygenericname/SSHRD_Script) into the GUI. It supports A7-A11 devices and provides:

- Ramdisk creation from IPSW firmware
- DFU pwn + boot via gaster/irecovery
- SSH access to the device filesystem
- SHSH blob dumping

## License

MIT — see LICENSE file.
