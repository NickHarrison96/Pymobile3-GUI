# Pymobile3-GUI

**Standalone iOS forensic & developer toolkit for Windows**

A native-feel PySide6 desktop application for Windows 10/11 with Mica/Acrylic backdrop, full-page workspaces, and real-time operation telemetry. Extracted from [RootForgeKit](https://github.com/NickHarrison96/RootForgeKit).

Built for forensic examiners, independent repair technicians, and security researchers who need practical, local tools for iOS device inspection, acquisition, and developer workflows.

> **Status:** Actively developed pre-alpha. Features are landing quickly — expect occasional breaking changes. Tested on real hardware; always work on devices you can afford to experiment with and keep backups.

---

### Key Capabilities

- **Device Overview** — Hardware specs, battery, activation state, developer mode status + lockdown control panel (rename, AssistiveTouch, Wi-Fi connections, battery detail)
- **Files & Applications** — AFC file browser, installed apps inspector, DCIM media quick access, crash reports explorer (browse, parse, export, pull)
- **Forensic Acquisition** — Logical, Logical+, and PRFS modes with live progress, case metadata, and TAR archiving
- **Developer Tools** — Progressive readiness pipeline (Dev Mode → DDI → RSD Tunnel) + DVT instruments (process monitor with search/kill/launch, bundle-id lookup, system monitor, screenshot, GPS simulation)
- **Recovery & Restore** — IPSW firmware flashing via `idevicerestore`, iTunes-style backup restore (encrypted backups supported), interactive Recovery/DFU hardware guides
- **Live Syslog** — Streaming console with filtering, pause/resume, and export
- **SSH Ramdisk** — checkm8 ramdisk create/boot for A7–A11 & T2 devices, device erase, on-board SHSH dump, SSH console
- **A12/A13 Ramdisk (experimental)** — usbliter8 SSH ramdisk support; fetch + patch the bootchain, load from Recovery

---

## Requirements

- Python 3.10+
- Physical iOS device (iOS 17+ requires an RSD tunnel)
- Administrator privileges for tunnel interface creation on iOS 17+

## Quick Start

```bash
git clone https://github.com/NickHarrison96/Pymobile3-GUI.git
cd Pymobile3-GUI
python -m venv .venv
.venv\Scripts\activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m pymobile3_gui.main
```

## Building a Standalone Executable (Windows)

```bash
pip install pyinstaller
python -m PyInstaller pymobile3_gui.spec --noconfirm
```

Produces `dist_pymobile3/Pymobile3-GUI/Pymobile3-GUI.exe` (onedir bundle).

---

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
│       ├── ramdisk_manager.py # SSH ramdisk tool (SSHRD_Script port)
│       └── resource_manager.py# Thread pool, subprocess, crash handler
├── views/                     # Full-page workspaces (6 views)
├── ui/                        # Reusable widgets (sidebar, dock, drawer, theme)
└── assets/                    # Fonts, SVG icons
```

---

## iOS 17+ Developer Services

iOS 17+ moved all developer services (DVT instruments, process list, screenshot, location simulation, app launch) behind RemoteXPC. These are only reachable through an RSD tunnel.

**Developer view readiness pipeline:**

1. **Enable Dev Mode** — `amfi enable-developer-mode` (device reboots)
2. **Mount DDI** — `mounter auto-mount` (Developer Disk Image)
3. **Start Tunnel** — Launches `pymobiledevice3 remote tunneld` elevated

When "Developer services" reads green, the DVT tabs become functional.

---

## SSH Ramdisk (checkm8 Devices)

The **SSH Ramdisk** tab in Recovery & Restore ports [SSHRD_Script](https://github.com/verygenericname/SSHRD_Script) into the GUI for A7–A11 and T2 devices (CPID `0x8960` / `0x7000` / `0x7001` / `0x8000` / `0x8003` / `0x8010` / `0x8011` / `0x8012` / `0x8015`):

- **Create** — Build a ramdisk from a signed IPSW (ipsw.me version lookup, partial downloads via `pzb`)
- **Boot / Erase / Reboot** — checkm8 pwn via gaster, bootchain delivery via irecovery
- **Dump SHSH Blobs** — Read on-board blobs over SSH (iproxy + paramiko)
- **Open SSH Console** — Root shell at `localhost:2222` while the ramdisk runs

**Requirements for SSH Ramdisk:**

- **WSL (Ubuntu)** — Build steps run the bundled Linux tools (`img4`, `img4tool`, `hfsplus`, `pzb`, `iBoot64Patcher`, …) inside WSL; DFU/USB steps run natively on Windows through the vendored executables in `assets/sshrd/win/`
- **DFU mode** with a WinUSB/libusbk driver (Zadig) on the Apple DFU device
- iOS **16.0 or older** for the build step (upstream `sshrd.sh` Linux branch refuses 16.1+)

All binaries, SHSH blobs, and payload tars are vendored in `pymobile3_gui/assets/sshrd/` — only IPSW firmware parts are downloaded on first build. Run the offline test suite with `pytest`.

---

## Roadmap

### Done & verified

- Lockdown control panel (rename, AssistiveTouch, Wi-Fi, battery)
- Crash reports explorer (browse, parse, export, pull)
- Backup restore-to-device (encrypted backups supported)
- DVT instruments — process monitor, kill/launch, system monitor, screenshot, GPS (power assertion unavailable on iOS 26.5)
- `keep_intermediate` acquisition option
- **SSH Ramdisk (checkm8)** — create + boot verified live on an iPhone 8 (iPhone10,4 / iOS 16.0.3); erase, SHSH dump and clean still unverified on hardware

### Legacy iOS Kit parity — groundwork landed (2026-10-05)

- `docs/REFERENCES.md` — reference list plus the GPL-3.0/MIT licensing boundary
- `docs/TODO.md` §6 — the phase-by-phase roadmap and an explicit not-porting list
- `pymobile3_gui/assets/legacy/` — 28 Apple `BuildManifest.plist` (signed-OTA matrix: 6.1.3 / 8.4.1 / 10.3.3) + 81 bsdiff bootchain/kernelcache patches (incl. iOS 8), with provenance recorded per file
- `core/backend/legacy_assets.py` — frozen-aware loader for manifests, exact IPSW component paths + SHA1 digests, and patches
- `scripts/legacy_inventory.py` + 27 offline tests in `tests/test_legacy_assets.py`

### In progress / experimental

- **A12/A13 Ramdisk tab** — experimental, unverified on hardware. Ports the A12-A13-Ramdisk (ICHA12A13) flow; the APFS ramdisk expand/inject and the usbliter8 handoff are macOS-only and fail closed (the tab takes a pre-injected ramdisk and starts from Recovery)

### Next — Legacy iOS Kit parity, in order (`docs/TODO.md` §6)

1. **Capability database** (`device_db.py`) — model↔ProductType, processor generation, signed-target/latest/baseband tables, activation-record and powdersn0w/DRA-v6 eligibility. Gates every restore/jailbreak menu.
2. **DFU/Recovery plumbing** — kDFU, pwnDFU, send pwned iBSS, exit recovery, just boot, per-device DFU helper.
3. **SSH ramdisk gaps** — 32-bit and iOS 8 ramdisks, baseband/activation dump, NVRAM clear, exploit toggle, bootstrap/untether/OpenSSH install, TrollStore.
4. **SHSH blobs** — OTA save, Cydia blobs, raw-dump conversion, deverser.
5. **Restore/downgrade** — signed-OTA, SHSH-blob, latest, powdersn0w, DRA v6, tethered, set-nonce, DFU IPSW, custom IPSW creation.
6. **App/data management** — IPA install/dump, sideload, mount, backup encryption toggles, pairing, activation/hacktivation, info export.
7. **32-bit jailbreak payloads** — g1lbertJB, greenpois0n, evasi0n, pangu, p0sixspwn, daibutsu, Aquila.

**Not porting** (recorded in `docs/TODO.md` §6.8): FourThree dualboot, turdus merula/kurouta dori pwning, macOS-only restore paths.

### Known gaps (not regressions)

- **Mounting `/var/mobile` in the SSH ramdisk** — the checkm8 ramdisk boots and SSH works, but the NAND data volume is not exposed. Candidate fix: `mount_ich` from the A12-A13-Ramdisk payload (`docs/TODO.md` §6.3)
- **Frozen-binary verification** — the PyInstaller build has not been tested end-to-end

---

## License

MIT — see [LICENSE](LICENSE) file.
