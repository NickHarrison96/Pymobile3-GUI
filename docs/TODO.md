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

### 1.4 Backup restore

`views/restore_view.py` is IPSW-only (`idevicerestore`). Restoring an
iTunes-style backup **to** the device is absent.

| Operation | Command | Original handler |
|---|---|---|
| Restore backup | `backup2 restore <dir>` | `_start_restore` (:248) |

Source: `components/ios/backup_restore_dialog.py` (281 lines) — the "Create
Backup / Restore Backup" mode switch at `_on_mode_changed` (:192).

The backup half is already ported and improved here (`backup_engine.py`); only
the restore path is missing. It should route through `TaskManager` like
acquisition does, not the original's inline runner.

---

## 2. Verification still owed

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

## 4. Known-inherited, not regressions

Recorded so nobody re-investigates them as extraction bugs:

- The empty `PYMOBILEDEVICE3_TUNNEL` bug (click discards empty env vars, so no
  developer command routed through tunneld) existed byte-identically in
  `utils/ios_core/tunnel_manager.py:112-118` of the original. Fixed here; the
  original still has it.
