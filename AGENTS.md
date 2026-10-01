# AGENTS.md

Guidance for AI coding assistants working in this repository.

## Project Overview

Pymobile3-GUI is a PySide6 (Qt) desktop application for Windows 10/11 that serves as an iOS forensic & developer toolkit. It communicates with iOS devices via `pymobiledevice3` (pinned to 10.x). Extracted from a larger project called RootForgeKit.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python -m pymobile3_gui.main

# Build standalone executable
pip install pyinstaller
python -m PyInstaller pymobile3_gui.spec --noconfirm

# Run tests (when present)
pytest
```

## Architecture

```
pymobile3_gui/
├── main.py                    # Entry point, NativeFramelessWindow, signal wiring
├── core/
│   ├── device_poller.py       # Async usbmux/lockdown device discovery (QThread)
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
│   ├── device_view.py
│   ├── files_apps_view.py
│   ├── acquisition_view.py
│   ├── developer_view.py
│   ├── restore_view.py
│   └── syslog_view.py
├── ui/                        # Reusable widgets
│   ├── theme.py               # Colors palette + QSS stylesheet
│   ├── native_window.py       # DWM Mica/Acrylic backdrop, frameless shell
│   ├── title_bar.py           # Custom Apple-style title bar with traffic lights
│   ├── sidebar.py             # Navigation sidebar + device status card
│   ├── operation_dock.py      # Bottom progress dock
│   ├── operation_drawer.py    # Expandable log/progress drawer
│   ├── toast.py               # Overlay notifications
│   └── assets.py              # Font loading
└── assets/                    # Fonts, SVG icons
```

## Key Conventions

### Threading & Qt
- **Never touch widgets from non-GUI threads.** Use signals with queued connections. See `LogBridge` in `main.py` for the pattern.
- `DevicePoller` runs in a `QThread` and communicates via signals.
- `TaskManager` runs `WorkerThread` instances and emits progress/log/completion signals.
- Use `QMutex` + `QMutexLocker` when accessing shared state from multiple threads.

### Task System
- All long-running operations go through `TaskManager.instance().start_task(...)`.
- Worker functions receive `progress_cb`, `log_cb`, and `is_cancelled_cb` callbacks.
- Progress percentages are 0-100; negative values mean "indeterminate, leave the bar alone."
- Step names must match the declared `steps` list exactly or they are treated as free-form status text.

### pymobiledevice3 Integration
- **Pinned to 10.x** — command names drift between majors and breakages are silent at import time.
- The app can act as a pymobiledevice3 CLI dispatcher when re-entered with `--run-pymobiledevice3` (see `_dispatch_pymobiledevice3` in `main.py`).
- iOS 17+ developer services require an RSD tunnel (elevated). The tunnel lifecycle is managed by `TunneldManager`.

### UI/UX Patterns
- Dark theme only. Colors are defined in `ui/theme.py` as `Colors` class constants.
- All styling via QSS (Qt Stylesheets). No hardcoded colors in widgets — reference `Colors.*`.
- Views are full-page workspaces switched via `QStackedWidget` index.
- The sidebar emits `workspace_changed(int)` to switch views.
- Use `Toast` for transient notifications with optional action buttons.

### Windows-Specific
- The app relaunches itself elevated on startup for iOS 17+ tunnel support (see `_ensure_elevated`).
- `NativeFramelessWindow` handles DWM glass, resize borders, and title bar drag via `nativeEvent`.
- Single-instance enforcement via `process_manager.py`.

## Active Development

### SSH Ramdisk Integration (branch: `feature/sshrd-ramdisk`)
- Porting SSHRD_Script (checkm8 SSH ramdisk tool) into the GUI
- Target: new `core/backend/ramdisk_manager.py` + integration into Recovery & Restore view
- Uses bundled/downloaded Linux binaries (gaster, irecovery, img4, etc.)
- Orchestrated via `TaskManager` with progress reporting

## Known Gaps (from docs/TODO.md)

These features exist in RootForgeKit but have not been ported yet:
- Lockdown control panel (~970 lines) — device settings read/write
- Crash reports explorer — browse/read/export crash logs
- DVT instruments: kill/launch app, sysmon, power assertion
- Backup restore-to-device (restore path, not just IPSW flashing)
- `keep_intermediate` option exposure in acquisition UI
- Frozen binary verification (PyInstaller build not yet tested end-to-end)

## Code Style

- Python 3.10+, type hints where clear
- Docstrings on all modules and public classes/functions
- No comments in code unless the "why" is non-obvious (existing code has some explanatory comments for subtle Qt/pymobiledevice3 behavior)
- Follow existing patterns: new views go in `views/`, new backend services in `core/backend/ new widgets in `ui/`
