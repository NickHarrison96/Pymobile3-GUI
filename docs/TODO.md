# Pymobile3-GUI — Implementation TODO

Work remaining after the split from RootForgeKit. The original implementation
plan (Tasks 1–12, all complete) lives in the NixFix repo at
`docs/superpowers/plans/2026-09-09-pymobile3-gui.md`; this file continues from
there and is the active list.

**Reference implementation:** `RootForgeKit-main/` — the pre-split codebase where
all of this worked. Paths below are relative to its root.

---

## 1. Feature gap vs RootForgeKit

Extracting the iOS toolkit into this repo carried over six workspaces but left
20 device operations behind. Established by diffing every `pymobiledevice3`
invocation in both trees.

### 1.1 Lockdown control panel — **largest gap (~970 lines)**

No equivalent exists here. `views/device_view.py` shows specs and three power
buttons; the original also exposed read/write control over device settings.

Source: `components/ios/lockdown_panel.py` (427 lines, embeddable) and
`components/ios/lockdown_dialog.py` (544 lines, standalone dialog with
Inspector/Control tabs). The panel is the better port target — it was designed
to embed in a page, which matches this app's full-page workspaces.

| Operation | Command | Original handler |
|---|---|---|
| Read device name | `lockdown device-name` | `_handle_device_name` (:276) |
| Rename device | `lockdown device-name --new-name <n>` | `_set_device_name` (:294) |
| Read date | `lockdown date` | `_handle_date` (:285) |
| Read language | `lockdown language` | `_handle_language` (:288) |
| Read locale | `lockdown locale` | `_handle_locale` (:291) |
| Assistive Touch toggle | `lockdown assistive-touch` | `_set_toggle` (:387), wired at :174 |
| WiFi Connections toggle | `lockdown wifi-connections` | `_set_toggle` (:387), wired at :183 |
| Read toggle states | `lockdown get --domain com.apple.mobile.wireless_lockdown --key EnableWifiConnections` | `read_toggle_states` (:230) |
| Battery info | `lockdown get --domain com.apple.mobile.battery` | `lockdown_panel.py:319` |
| Activation check | `lockdown info` | "Check Activation" button |
| Sleep | `diagnostics sleep` | `_power_action` (:245) |

Notes:
- `lockdown wifi-connections` prints nothing when reading, so the toggle state
  cannot be read back the obvious way. The original queries the keyed domain
  instead — and that key only exists once the value has been set at least once,
  returning "No such value" otherwise. See `lockdown_panel.py:233-239`; both
  halves of that are easy to get wrong.
- `lockdown_dialog.py:412` uses `lockdown info --domain com.apple.mobile.battery`
  for the same data, with a comment on why that domain beats the raw key.
- Restart/shutdown already exist here via `DiagnosticsService`; **sleep** does
  not. The original drove all three through `["diagnostics", action]`.

### 1.2 Crash reports explorer — **done**

A "Crash Reports" tab now lives in `views/files_apps_view.py`: lists reports
(`crash ls`), views one in an embedded viewer (`crash parse`), exports the
viewer text locally, pulls one or all reports (`crash pull [--remote-file]`),
plus Flush Pending and Clear All buttons. All device calls run on QThreads.

Notes for whoever touches this next:
- `crash parse` (not `crash show` — that subcommand doesn't exist in
  pymobiledevice3 10.x) emits ANSI color codes; they are stripped before
  display.
- `crash pull` takes the output directory as its only positional arg; a
  specific report goes in via `--remote-file <path>`.

### 1.3 DVT instruments — **done**

Added to `views/developer_view.py`, all verified live against the test device:

| Operation | Implementation |
|---|---|
| Kill process | Right-click context menu on Process Monitor rows → confirm → `dvt kill <pid>` (the CLI takes a **PID**, not a bundle id, despite the original's `_kill_app`) |
| Launch app | Bundle-ID field + Launch button in the Process Monitor tab → `dvt launch <bundle-id>` |
| System monitor | "System Monitor" tab → `dvt sysmon system` |
| Power assertion | "Power Assertion" tab → detached `arbitration check-in <name> --force` with `stdin=PIPE` (the CLI ends in `input()`; an open pipe is what holds the assertion), release = terminate + `check-out` |

Notes:
- **`sysmon system` prints `key: value` lines, not JSON** — the original's
  `json.loads` never worked here; the parser tries JSON first, then falls back
  to the line format.
- **Power assertion is unavailable on iOS 26.5**: Apple no longer exposes
  `com.apple.dt.devicearbitration` (verified — not in the RSD service list;
  direct start gives `InvalidService`). The tab stays for older iOS versions
  and maps that error to a plain explanation instead of the raw dump.
- Text commands (launch/kill/arbitration) run with `include_stderr=True` and
  treat `\bERROR\b` as failure — same exit-0 trap as the mount flow.

### 1.4 Backup restore — **done**

`views/restore_view.py` gained a "Backup Restore" tab (folder picker,
encrypted-backup password field, reboot toggle) routed through TaskManager
like acquisition:

| Operation | Command | Where |
|---|---|---|
| Restore backup | `backup2 restore <parent> [--source udid]` | `restore_backup()` in `core/backend/backup_engine.py` |

Implementation notes:
- `resolve_backup_source()` accepts either the UDID folder itself or its
  parent (pymobiledevice3 wants the parent; users pick the UDID folder) and
  pins `--source` so a folder holding several sets still restores the one
  selected. Missing Manifest.plist → plain-language error, not a stack dump.
- Streams with no timeout (large restores run for a long time), maps tqdm's
  percent bar into the 10–95 slice of the dock, masks `--password` in the
  log, and treats a swallowed traceback as failure even on exit 0.
- Preflight "Connecting to Device" step: `usbmux list` must show a device;
  empty/`[]` fails with an unlock/trust hint before any restore starts.

---

## 2. Verification still owed

- [ ] **SSH Ramdisk on real checkm8 hardware.** The port ships with 64 offline
      tests (`tests/`): sshrd.sh decision tables (darwin mapping, trustcache,
      16.1 build block), BuildManifest parsing, argv construction with the
      runner stubbed, and an offscreen tab smoke — but no A7-A11 device has
      ever run it (the only test phone is an A16). Owed: `gaster pwn` on real
      hardware, a full `Create` against an actual IPSW, `Boot`, the
      erase/obliteration path, and a blob dump. Also confirm the DFU driver
      story (Zadig/WinUSB) on a clean Windows install.
- [ ] **Rebuild and test the frozen binary.** The `sys.executable -m` fix and
      the expanded spec are verified from source and by simulation, but not yet
      against an actual PyInstaller build. Run
      `python -m PyInstaller pymobile3_gui.spec --noconfirm`, then confirm
      `dist_pymobile3/Pymobile3-GUI/Pymobile3-GUI.exe --run-pymobiledevice3 usbmux list`
      prints device JSON. That is the only way to catch a still-missing hidden
      import.
- [x] **DDI mount on iOS 17+ — verified working.** The original symptom was a
      passcode issue, not iOS 26: `mounter auto-mount` failed with

  ```
  ERROR Developer Mode is disabled. You can try to enable it using:
  python3 -m pymobiledevice3 amfi enable-developer-mode
  ```

  The command still exits 0 — pymobiledevice3 logs the failure to stderr — so
  the GUI previously reported success and then showed "verification unclear"
  because `mounter list` returned `[]`. Fixed: `safe_run_command` gained
  `include_stderr=True`, and `_on_ddi_done` now fails on any `ERROR` line
  (matched mid-line: log output is timestamp/host-prefixed). Empty
  `mounter list` now triggers a `mounter lookup Personalized` second opinion
  instead of an instant "unclear". Developer Mode enablement: the passcode
  blocks the programmatic route (`ERROR Cannot enable developer-mode when
  passcode is set`, stderr-only), so the GUI runs `amfi reveal-developer-mode`
  on that error and shows the manual steps (Settings > Privacy & Security >
  Developer Mode > on > reboot > confirm) instead of the old false
  "Command sent." — which is how the device was finally enabled. Verified
  end-to-end: mount reports "DDI Mounted".

---

## 3. Smaller items

- [x] **Expose `keep_intermediate`.** Done — `chk_keep` checkbox in the
      acquisition view, wired into `opts`. (Exists because acquisition stages
      then tars: peak disk use was ~2× the pulled size without it.)
- [ ] **Tunnel recovery policy is provisional.** `TunneldManager._on_tunnel_lost`
      notifies after 3 failed probes and never auto-restarts, which is correct
      while the app may be unelevated. Revisit if the app becomes
      always-elevated: an auto-reconnect would then be safe.
- [x] **`restore_view` step names don't match its checklist.** Done —
      `run_restore` parses idevicerestore output and emits the declared step
      names (`Preparing Firmware`, `Entering Restore Mode`, `Flashing
      Filesystem`, `Flashing Kernel`, `Finalizing`).
- [x] **Mixed line endings.** Done — `.gitattributes` with `* text=auto` plus
      per-extension `eol=lf` (committed separately, as planned).

---

## 4. Full-project code review & hardening (2026-10-05)

A whole-tree review (core, views, main+ui+packaging) turned up stability and
durability defects beyond the feature port. Fixed in one pass:

- **Shutdown path** (`main.py`) — there was no `closeEvent`/`aboutToQuit`, so a
  close mid-acquisition destroyed live `WorkerThread`s, left a half-written
  forensic backup unflushed, and skipped child cleanup (incl. the elevated
  tunneld). Added `MainWindow.shutdown()` + `closeEvent` + `aboutToQuit`.
- **`usb_reset` arbitrary-device reset** (`ramdisk_manager.py`) — the fallback
  probe dropped `idVendor=0x05AC` and could reset a user's mouse/keyboard.
  Vendor filter now never widens.
- **Duplicate-task guard** (`task_manager.py`) — `start_task` overwrote an
  in-flight `task_id`, so double-clicking Start ran two acquisitions into one
  output dir. Now rejects duplicates; `cancel_active_task` cancels all running
  tasks; `active_task_id` only clears when nothing else runs. Start buttons in
  acquisition/restore views disable until their task finishes.
- **False success** (`backup_engine.py`) — restore trusted exit code only, but
  pymobiledevice3 exits 0 on "Backup is encrypted…"; now fails on `\bERROR\b`
  and pre-checks `IsEncrypted`. Logical+/PRFS no longer reports green 100% when
  every step failed.
- **Frozen build** (`ui/assets.py`, `pymobile3_gui.spec`) — icons/fonts resolved
  via a `__file__` walk that pointed at `_MEIPASS/pymobile3_gui/assets` while
  the spec installs at `_MEIPASS/assets`, so every icon silently vanished in the
  bundle. Now `resource_path()`. Also removed the bogus `PIL` exclude
  (webinspector needs it) and added `exclude_binaries=True` (was onefile inside
  onedir — double disk + `%TEMP%` re-extraction every launch).
- **Unreadable dialogs** (`theme.py`, `main.py`) — QMessageBox drew light-on-
  light (Qt reported Dark but palette Window stayed `#f0f0f0`). Added a dark
  `get_application_palette()` + `setColorScheme(Dark)` + `QDialog/QMessageBox`
  QSS. Verified by pixel grab (11% → 97% dark).
- **Title-bar hit test** (`native_window.py`) — everything right of `rx < 60`
  returned `HTCAPTION`, so the Refresh button and device chip never got clicks;
  the drag math also mixed physical and logical pixels. Now `mapFromGlobal` +
  `childAt` (interactive children get the click, empty space drags).
- **Cancellation was largely cosmetic** — `run_streaming` never killed its child
  on cancel (a half-downloaded IPSW kept writing under the next run's `_fresh_dir`);
  IPSW restore used a single 1200 s `subprocess.run` with cancel checked only
  after. Both now stream/kill properly.
- **Hang latching** — `DevicePoller` had no timeout (one stalled usbmux call
  wedged the pane forever); the DFU probe latched `_ram_probe_running` because
  `errorOccurred` was never connected. Both bounded now.
- **Observability & packaging** — `install_global_crash_handler` now also writes
  a timestamped log file and hooks `threading.excepthook` (was stderr-only, i.e.
  invisible with `console=False`); `pyproject.toml` gained `paramiko`/`requests`
  so `pip install .` doesn't ship a broken ramdisk tab; `:focus` outlines added
  (the global `outline: none` had removed keyboard focus indication entirely).

Still owed (unchanged): the frozen build has not been run end-to-end — the spec
and asset-path fixes above are source-verified but the PyInstaller build in
section 2 is the only real proof.

---

## 5. Known-inherited, not regressions

Recorded so nobody re-investigates them as extraction bugs:

- The empty `PYMOBILEDEVICE3_TUNNEL` bug (click discards empty env vars, so no
  developer command routed through tunneld) existed byte-identically in
  `utils/ios_core/tunnel_manager.py:112-118` of the original. Fixed here; the
  original still has it.
