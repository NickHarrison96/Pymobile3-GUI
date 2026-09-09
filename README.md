---


<img width="1920" height="1040" alt="asd" src="https://github.com/user-attachments/assets/666cd9dd-d229-4176-8178-755cfe724b8f" />


---

# Pymobile3-GUI

**Standalone iOS forensic & developer toolkit** — extracted from RootForgeKit.

A native-feel PySide6 desktop application for Windows 10/11 with Mica/Acrylic backdrop, full-page workspaces, and real-time operation telemetry.

## Features

- **Device Overview** — Hardware specs, battery, activation state, developer mode status
- **Files & Applications** — AFC file browser, installed apps inspector, DCIM media quick access
- **Forensic Acquisition** — Logical, Logical+, PRFS modes with live progress, case metadata, TAR archiving
- **Developer Tools** — Progressive readiness pipeline (Dev Mode → DDI → RSD Tunnel) + DVT instruments (Process Monitor, Screenshot, GPS Simulation)
- **Recovery & Restore** — IPSW firmware flashing via `idevicerestore` + interactive Recovery/DFU hardware guides
- **Live Syslog** — Streaming console with filtering, pause/resume, export

## Requirements

- Python 3.10+
- Physical iOS device (iOS 17+ needs RSD tunnel)
- Administrator/root for tunnel interface creation (iOS 17+)

## Quick Start

```bash
git clone <repo-url>
cd pymobile3_gui
python -m venv .venv
.venv\Scripts\activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python main.py
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

## License

MIT — see LICENSE file.
