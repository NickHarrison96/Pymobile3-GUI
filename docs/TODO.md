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

### 1.2 Crash reports explorer

Currently crash reports are only pulled as an acquisition step
(`backup_engine._step_crash`). There is no way to browse or read one.

Source: `components/ios/crash_reports_dialog.py` (167 lines).

| Operation | Command | Original handler |
|---|---|---|
| List reports | `crash ls` | `_load_crash_logs` (:117) |
| View one report | `crash show <name>` | `_on_log_selected` (:136) |
| Export selected | — (local write) | `_export_selected_log` (:146) |
| Bulk download all | `crash pull` | `_export_all_logs` (:159) |

Natural home: a tab in `views/files_apps_view.py`, or a seventh workspace.

### 1.3 DVT instruments — missing tools

`views/developer_view.py` has proclist, screenshot and simulate-location. The
original also had:

| Operation | Command | Original handler |
|---|---|---|
| Kill process | `developer dvt kill <pid>` | `_kill_app` (:506) |
| Launch app | `developer dvt launch <bundle-id>` | `_launch_app` (:495) |
| System monitor | `developer dvt sysmon` | `_fetch_sysmon` (:401) |
| Power assertion (hold device awake) | `developer arbitration check-in <name> --force` | `_start_power_assertion` (:421) |

Source: `components/ios/dvt_kit_dialog.py` (515 lines).

Power assertion is the subtle one: `arbitration check-in` holds the assertion
only while its process runs, so the original spawns it **detached** and keeps
the handle, releasing it via `_stop_power_assertion` (:469). It is not a
fire-and-forget command. Genuinely useful during long acquisitions — it keeps
the device awake.

Kill/launch pair naturally with the existing process table: add a context menu
on `developer_view`'s proclist rows.

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
- [ ] **DDI mount on iOS 17+.** The 60s→900s timeout fix addresses the most
      likely cause of the reported "cannot detect iOS version" failure, but the
      exact error text was never captured. Re-test and record it verbatim if it
      still fails.

---

## 3. Smaller items

- [ ] **Expose `keep_intermediate`.** It exists in `backup_engine.DEFAULT_OPTIONS`
      but no UI sets it. Acquisition stages the collection then tars it, so peak
      disk use is ~2× the pulled size (27.5 GB of camera media needs ~55 GB). A
      "skip archiving" checkbox would let large acquisitions run in 1× space.
- [ ] **Tunnel recovery policy is provisional.** `TunneldManager._on_tunnel_lost`
      notifies after 3 failed probes and never auto-restarts, which is correct
      while the app may be unelevated. Revisit if the app becomes
      always-elevated: an auto-reconnect would then be safe.
- [ ] **`restore_view` step names don't match its checklist.** It emits
      `"Initializing Restore"` while declaring `["Preparing Firmware", ...]`.
      Harmless since TaskManager now ignores unmatched names, but the checklist
      never advances. Same fix as acquisition: emit real step names, or build
      the list from what the worker emits.
- [ ] **Mixed line endings.** Some files are LF, some CRLF (e.g.
      `backup_engine.py`). A `.gitattributes` with `* text=auto` would settle
      it, but do it as one deliberate commit — it will touch every file.

---

## 4. Known-inherited, not regressions

Recorded so nobody re-investigates them as extraction bugs:

- The empty `PYMOBILEDEVICE3_TUNNEL` bug (click discards empty env vars, so no
  developer command routed through tunneld) existed byte-identically in
  `utils/ios_core/tunnel_manager.py:112-118` of the original. Fixed here; the
  original still has it.
