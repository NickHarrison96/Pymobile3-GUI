# Pymobile3-GUI

**Standalone iOS forensic & developer toolkit** — extracted from RootForgeKit.

A native-feel PySide6 desktop application for Windows 10/11 with Mica/Acrylic backdrop, full-page workspaces, and real-time operation telemetry.

## Features

- **Device Overview** — Hardware specs, battery, activation state, developer mode status + lockdown control panel (rename, assistive touch, Wi-Fi connections, battery detail)
- **Files & Applications** — AFC file browser, installed apps inspector, DCIM media quick access, crash reports explorer (browse, parse, export, pull)
- **Forensic Acquisition** — Logical, Logical+, PRFS modes with live progress, case metadata, TAR archiving
- **Developer Tools** — Progressive readiness pipeline (Dev Mode → DDI → RSD Tunnel) + DVT instruments (process monitor with search/kill/launch, bundle-id lookup, system monitor, screenshot, GPS simulation)
- **Recovery & Restore** — IPSW firmware flashing via `idevicerestore`, iTunes-style backup restore (with encrypted-backup password support), interactive Recovery/DFU hardware guides
- **Live Syslog** — Streaming console with filtering, pause/resume, export
- **SSH Ramdisk** — checkm8 ramdisk create/boot for A7-A11 & T2 devices, device erase, on-board SHSH dump, SSH console

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

The **SSH Ramdisk** tab in Recovery & Restore ports [SSHRD_Script](https://github.com/verygenericname/SSHRD_Script) into the GUI for A7-A11 and T2 devices (CPID `0x8960`/`0x7000`/`0x7001`/`0x8000`/`0x8003`/`0x8010`/`0x8011`/`0x8012`/`0x8015`):

- **Create** — build a ramdisk from a signed IPSW (ipsw.me version lookup, partial downloads via `pzb`)
- **Boot / Erase / Reboot** — checkm8 pwn via gaster, bootchain delivery via irecovery
- **Dump SHSH Blobs** — read on-board blobs over SSH (iproxy + paramiko)
- **Open SSH Console** — root shell at `localhost:2222` while the ramdisk runs

Requirements:

- **WSL (Ubuntu)** — build steps run the bundled Linux tools (`img4`, `img4tool`, `hfsplus`, `pzb`, `iBoot64Patcher`, ...) inside WSL; DFU/USB steps run natively on Windows through the vendored exes in `assets/sshrd/win/`
- **DFU mode** with a WinUSB/libusbk driver (Zadig) on the Apple DFU device
- iOS **16.0 or older** for the build step (upstream `sshrd.sh` Linux branch refuses 16.1+)

All binaries, SHSH blobs and payload tars are vendored in `pymobile3_gui/assets/sshrd/` — only IPSW firmware parts are downloaded, on first build. Run the offline test suite with `pytest`.

## License

MIT — see LICENSE file.
