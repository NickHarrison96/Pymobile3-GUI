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
│       ├── ramdisk_manager.py # SSH ramdisk tool (SSHRD_Script port)
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
└── assets/                    # Fonts, SVG icons, SSH ramdisk tools (sshrd/)
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

## Learned Pitfalls

### Emoji & console encoding (source of recurring errors)
- **The Windows console is cp1252.** Printing emoji (or any non-cp1252 char) to
  stdout/stderr raises `UnicodeEncodeError: 'charmap' codec can't encode
  character ...`. This has caused multiple "mysterious" crashes that had nothing
  to do with the code under test — e.g. a `print(tabText(i))` smoke test failed
  only because a tab label was `🔥 Crash Reports`.
- **Prevention:**
  - Never `print()` emoji, device names, or other raw device/user strings to the
    console — they may contain Unicode (device was named
    `Built/Hacked by: NïćĦäřřïšøň`). Log via Qt signals/`Toast` instead, or open
    files explicitly with `encoding='utf-8'`.
  - When writing test/smoke scripts, avoid printing strings that may contain
    emoji; print counts/booleans instead (`print('tabs:', n)`). This applies
    to GUI widget text too — a test that printed a warning label blew up on
    its leading `⚠`, not on any emoji.
  - If a subprocess output must be captured, decode with
    `errors='replace'` or read bytes and open with `encoding='utf-8'`.
  - Emoji **are fine** inside the GUI (tab labels, buttons) — Qt renders them
    as long as the source file itself is saved UTF-8. The problem is only
    console I/O.
  - User-facing strings from the device must not be concatenated into
    `print`/`traceback`/`subprocess` shell arguments without escaping.

### pymobiledevice3 exit codes lie
- **Many pymobiledevice3 commands exit 0 even on failure** — errors are logged
  to stderr (`mounter auto-mount` with Developer Mode off returned `rc=0` with
  `ERROR Developer Mode is disabled...` only on stderr). `safe_run_command`
  discards stderr on success by default, so a failed command looked successful
  and surfaced later as a confusing "verification unclear" dialog.
- **Prevention:**
  - Pass `include_stderr=True` to `safe_run_command` for commands whose
    failures matter, and inspect the text — do not trust `ok` alone.
  - Log lines are prefixed (`timestamp host pid LEVEL message`), so match
    `\bERROR\b` anywhere in the line; `startswith("ERROR")` never fires.
  - When verifying device state, prefer a second-opinion query
    (e.g. `mounter lookup <type>`) over one command's silence.

### Long-running device operations must not be killed mid-cycle
- **`amfi enable-developer-mode` takes ~50s end-to-end** (ENABLE → device
  reboots → usbmux reconnect → auto-confirm the post-restart prompt). The GUI
  used `timeout=30`, so it always killed the command after the reboot but
  before the confirmation — device rebooted, Developer Mode stayed off. Same
  class of bug as the old 60s DDI-mount timeout.
- **Prevention:** give lifecycle-aware timeouts, not round numbers:
  `DEV_MODE_ENABLE_TIMEOUT = 240` and `DDI_MOUNT_TIMEOUT = 900` (both in
  `views/developer_view.py`). When adding a command that triggers a reboot,
  download, or mount, size the timeout for the whole cycle and say so in the
  busy message.

### Asset paths and WSL argv (SSHRD integration)
- **`paths.app_dir()` used one `dirname` too few from source.** The double
  dirname was inherited from RootForgeKit, where `paths.py` sat two levels
  down; here it resolves to `pymobile3_gui/core`, so every `resource_path()`
  silently pointed inside `core/` and returned nothing (harmless only because
  `ui/assets.py` resolves its own paths). Fixed to three dirnames; frozen
  (`_MEIPASS`) is unchanged and matches the spec's `datas`.
- **WSL rewrites cwd but never argv.** A raw `C:\...` argument handed to
  `wsl_tool()` reaches the Linux binary as a relative filename with
  backslashes and fails as "file not found" — deep into the build, after the
  IPSW download. `wsl_arg()` translates any drive-prefixed arg to
  `/mnt/<drive>/...`; relative args, URLs and hex bags pass through.
- **Prevention:** both bugs were caught by `tests/test_ramdisk_manager.py`
  asserting the *constructed command* rather than running it. For anything
  that shells out, stub the runner and assert argv.
- **pzb exits 0 on failure** — `_pzb_fetch()` checks the output file exists
  and is non-empty before believing it; keep that check if you add fetches.

### Hardening pass (2026-10-05) — defects a whole-tree review surfaced
- **Qt on Windows 10 does not install a dark palette.** `colorScheme()` reports
  `Dark` while `palette().Window` stays `#f0f0f0`, so a `QMessageBox` draws a
  light background under light QSS text (invisible). The fix in `main()` is all
  three of: `styleHints().setColorScheme(Dark)`, `setPalette(get_application_palette())`,
  and `QDialog, QMessageBox { background-color: ... }` in the stylesheet.
- **No `closeEvent`/`aboutToQuit` = closing destroys live threads.** A half-written
  forensic backup is lost and children (incl. the elevated tunneld) are orphaned.
  `MainWindow.shutdown()` cancels and waits for tasks, the poller and the tunnel.
- **`usb_reset` must never drop `idVendor=0x05AC`.** The "any Apple device"
  fallback used to clear the vendor filter and could reset a user's own mouse.
  Widen product ids, never the vendor.
- **The spec built onefile *inside* onedir** (`EXE` without
  `exclude_binaries=True`) — double disk use plus full `%TEMP%` re-extraction
  every launch. Keep `exclude_binaries=True` on `EXE`.
- **A `QProcess` must not run inside a TaskManager worker thread** — that thread
  has no event loop, so queued `finished`/`readyRead` never arrive. Long ops that
  stream output use `subprocess.Popen` directly (`restore_backup`, `run_restore`,
  `run_streaming`); `StreamingProcessRunner` is only for event-loop threads.

## Active Development

### SSH Ramdisk — implemented, merged to `master`, untested on hardware
- Ports SSHRD_Script (checkm8, A7-A11/T2) into the GUI:
  - `core/backend/ramdisk_manager.py` — `op_create`, `op_boot`, `op_reset`,
    `op_reboot`, `op_dump_blobs`, `op_clean`, `open_ssh_console`; failures
    raise `RamdiskError` (the TaskManager shows its message). Step lists live
    next to the ops (`CREATE_STEPS`, `BOOT_STEPS`, ...) and the worker's
    `step=` strings must match them exactly.
  - **Hybrid execution:** file/patch steps run vendored Linux tools in WSL
    (`wsl_tool`); DFU/USB steps run vendored Windows exes (`native_tool`:
    gaster, irecovery, iproxy). No usbipd/usb passthrough.
  - `gaster reset` does not exist in any Windows gaster build — `usb_reset()`
    issues libusb `reset_device` via pyusb instead (vendored
    `assets/sshrd/win/libusb-1.0.dll`).
  - Assets vendored at `pymobile3_gui/assets/sshrd/` (`Linux/`, `win/`,
    `shsh/`, `sshtars/`, `bootlogo.im4p`), shipped via the spec's `datas`;
    `.gitignore` carries a negation for `sshtars/*.tar.gz`.
  - UI: "SSH Ramdisk" tab at index 2 of the Recovery & Restore view —
    `irecovery -q` DFU poll (QProcess, only while the tab is visible),
    ipsw.me version combo fetched off-thread, iOS 16.1+ build-block warning,
    busy-state disables all seven action buttons.
  - Tests: `tests/` — 64 offline tests (sshrd.sh decision tables, manifest
    parsing, argv construction with `run_streaming` stubbed, offscreen tab
    smoke). **No checkm8 device has ever run it** — the only test phone is
    an A16, so pwn/boot/erase/dump all remain unverified live.

## Known Gaps (from docs/TODO.md)

One feature gap from RootForgeKit remains unported:
- Frozen binary verification (PyInstaller build not yet tested end-to-end)

Ported and verified: lockdown control panel, crash reports explorer, backup
restore-to-device, DVT instruments (kill/launch/sysmon/power assertion — the
last is unavailable on iOS 26.5, which no longer exposes the arbitration
service), `keep_intermediate`.

## Code Style

- Python 3.10+, type hints where clear
- Docstrings on all modules and public classes/functions
- No comments in code unless the "why" is non-obvious (existing code has some explanatory comments for subtle Qt/pymobiledevice3 behavior)
- Follow existing patterns: new views go in `views/`, new backend services in `core/backend/ new widgets in `ui/`
