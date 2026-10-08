# Pymobile3-GUI — Implementation TODO

Work remaining after the split from RootForgeKit. The original implementation
plan (Tasks 1–12, all complete) lives in the NixFix repo at
`docs/superpowers/plans/2026-09-09-pymobile3-gui.md`; this file continues from
there and is the active list.

**Reference implementation:** `RootForgeKit-main/` — the pre-split codebase where
all of this worked. Paths below are relative to its root. The full provenance
table (including Legacy iOS Kit, added 2026-10-05) lives in
`docs/REFERENCES.md`.

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
- [x] **No `LICENSE` file.** Done — MIT text added at `LICENSE` (B0), so the
      grant `README.md` and `pyproject.toml` both promise actually exists.

---

## 4. Full-project code review & hardening (2026-10-05, merged to master)

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

---

## 6. Roadmap — Legacy iOS Kit feature parity

Added 2026-10-05. Source: `C:\Users\nick\Documents\GitHub\Legacy-iOS-Kit`
(`restore.sh`, 11,907 lines / 200 functions / GPL-3.0). Provenance, licensing
constraints and the per-tool binary inventory are in `docs/REFERENCES.md` —
**read that section before touching anything here.**

### 6.0 Ground rules

- **Re-implement, never copy.** LIK is GPL-3.0; this project is MIT. Every item
  below is reimplemented from documented behaviour over third-party tools.
  Verbatim or reworded `restore.sh` code is a GPL derivative.
- **Everything runs through WSL.** LIK ships Linux + macOS binaries only —
  there is no `bin/windows`. Linux tools go through `wsl_tool()`
  (`core/backend/ramdisk_manager.py`); DFU/USB steps go through `native_tool()`
  with the vendored `assets/sshrd/win/*.exe`. Both already exist — reuse them
  rather than building a third execution path.
- **Vendor binaries from their own upstream**, into
  `pymobile3_gui/assets/legacy/` (new tree, own `licenses/` dir), with a
  negation in `.gitignore` and a `datas` entry in `pymobile3_gui.spec`.
- **New backend module per phase**, `core/backend/legacy_*.py`, each exposing
  `op_*` functions with `progress_cb` / `log_cb` / `is_cancelled_cb` exactly
  like `ramdisk_manager.py`. New views go in `views/`, new widgets in `ui/`.
- **Nothing destructive gets a one-click path.** LIK's prompts are deliberately
  scary (`warn` + `select_yesno`) around activation, erase, NVRAM and flashing.
  Keep that: `Toast`/dialog confirmations with the same plain-language warnings.
- Step lists live next to the ops (`CREATE_STEPS`, `BOOT_STEPS`, ...) and the
  worker's `step=` strings must match exactly — see AGENTS.md.

### 6.0.1 The block contract

Every block below is executed in the same loop: **implement → offline tests →
`pytest` green → update status → one commit → push.** Precisely:

1. Put logic in the right module (`device_db.py` / `legacy_*.py`), a reusable
   widget in `ui/`, a page or tab in `views/`.
2. Add **offline** tests in `tests/` — assert *constructed argv* with the runner
   stubbed; never a device, network, or WSL. This is the pattern that caught the
   `wsl_arg` and `paths.app_dir()` bugs.
3. Run `python -m pytest -q` — must be green (baseline: 231 passed at 2026-10-05).
4. Tick this block's `[x]` and update its status line; touch `AGENTS.md` only
   when a whole phase's status changes.
5. One commit, imperative subject (e.g. `Add device_db HardwareModel↔ProductType
   map`), then push. Move to the next block.
6. Blocks marked **HW** additionally need a manual gate before closing:
   "verified on `<model>` / iOS `<ver>`".

### 6.0.2 Block index (execution order)

Prefix a block's number with `[x]` once it is committed.

| # | Block | Phase | HW |
|---|---|---|---|
| [x] B0 | Add MIT `LICENSE` | §3 | no |
| [x] B1a | HardwareModel ↔ ProductType map | 6.1 | no |
| B1b | Processor generation (`device_proc` 1–11) | 6.1 | no |
| B1c | Signed-target + latest version matrix | 6.1 | no |
| B1d | Baseband name + SHA1 | 6.1 | no |
| B1e | Activation / powdersn0w / DRA-v6 eligibility | 6.1 | no |
| B1f | `device_get_info` ECID/UDID/build/mode parsers | 6.1 | no |
| B2 | Version-update check | 6.6 | no |
| B3 | App list user/system/all | 6.6 | no |
| B4 | Install IPA | 6.6 | no |
| B5 | Backup encryption on/off/change | 6.6 | no |
| B6 | Erase all content and settings | 6.6 | no |
| B7 | Pair device | 6.6 | no |
| B8 | Activate via `ideviceactivation` | 6.6 | no |
| B9 | Export device / battery info | 6.6 | no |
| B10 | Data management (uicache; sshfs vs SFTP) | 6.6 | no* |
| B11 | Save OTA blobs | 6.4 | no |
| B12 | Onboard raw dump + convert | 6.4 | maybe |
| B13 | Cydia blobs / 64-bit deverser | 6.4 | HW |
| B14 | Exit recovery + Just Boot/history | 6.2 | HW |
| B15 | Enter kDFU / pwnDFU / send pwned iBSS | 6.2 | HW |
| B16 | Per-device DFU helper timer | 6.2 | HW |
| B17 | 32-bit ramdisk | 6.3 | HW |
| B18 | iOS 8 ramdisk | 6.3 | HW |
| B19 | Dump baseband + activation records | 6.3 | HW |
| B20 | Per-version erase recipes | 6.3 | HW |
| B21 | NVRAM clear / exploit toggle / datetime | 6.3 | HW |
| B22 | Bootstrap / untether / OpenSSH | 6.3 | HW |
| B23 | TrollStore install | 6.3 | HW |
| B24 | Mount `/var/mobile` (`mount_ich`) | 6.3 | HW |
| B25+ | Restore / downgrade (split; see §6.5) | 6.5 | HW |
| B-last | 32-bit jailbreak payloads | 6.7 | HW |

`*` B10 needs a human decision (sshfs side vs. SFTP-backed browser) before it
can be specified.

### 6.1 Capability database — prerequisite for everything else (`B1a–B1f`)

Every menu in `restore.sh` is gated on device type / processor / mode / iOS
version. None of that gating exists here, so **this lands first.** Landing spot:
new `core/backend/device_db.py` — pure data + lookup helpers, with offline unit
tests in `tests/test_device_db.py`. It keys on **ProductType / HardwareModel**;
chip/processor *labels* come from the existing `core/backend/device_ident.py`
(CPID-keyed) — do **not** duplicate that table.

| # | Goal | LIK source | Notes |
|---|---|---|---|
| B1a | HardwareModel → ProductType, both directions | `device_get_info` :1367–1529 | ~70 entries. Two quirks port verbatim as *data*: iPod touch 4 on iOS 7 reports as `iPhone3,1/3,3` (N81AP override); iPad2,1 is force-mapped to `k93`. |
| B1b | Processor generation (`device_proc` 1–11) + `device_checkm8ipad` | :1536–1558 | S5L8900=1, A4=4, A5=5, A6=6, A7=7, A8=8, A9=9, A10/A11=10, else 11. `checkm8ipad` for iPad6/7. |
| B1c | Signed-target version/build per device + latest-known | :1595–1657 | The OTA-downgrade matrix (3.1.3/7E18 … 10.3.3/14G60). Latest is hardcoded with an ipsw.me fallback — model the fallback behind a seam the tests stub. |
| B1d | Baseband to use + SHA1 | :1673–1703 | Per-device `bbfw` name and digest; `Trek`/`Mav5`/`Mav7Mav8` families. |
| B1e | Activation candidacy + powdersn0w / DRA-v6 eligibility | :1709–1750 | `9900candidate` (iPhone4,1 / iPhone5,2 / iPad2,7 / iPad3,[26]) and `activationissue` sets + the auto-enable ladder; `device_can_powder`, `device_can_drav6`. |
| B1f | ECID (hex→dec), UDID, build, mode detection | `device_get_info` :1225–1320, `device_entry` :887, `..._s5l8900` :929 | Pure parsers only (Recovery/DFU/WTF/Normal split from `irecovery -q` + `ideviceinfo` text). Manual entry covers devices where lockdown reports nothing (iOS ≤2.x). Reuse `ramdisk_manager.parse_device_info`. |

### 6.2 DFU / Recovery mode plumbing (`B14–B16`)

Everything else assumes the device can be *put into* a mode. Today the app only
polls for a DFU device; it cannot move one there.

| # | Feature | LIK | What we have | Needed |
|---|---|---|---|---|
| B14 | Exit Recovery (`irecovery -n`) + Just Boot + history | `main` case `exitrecovery`; `menu_justboot` :11554, `..._history` :11674, `device_justboot` :11797 | — | Exit op + warning that tethered devices need Just Boot; a persisted "last used" list of `all_flash`/restore-mode images |
| B15 | Enter kDFU (32-bit) / pwnDFU (A6+) / send pwned iBSS (A5/A6) | `device_enter_mode` :2051, `device_send_unpacked_ibss` :2395 | `gaster_pwn()` exists but is only called from `op_boot`/`op_reset` | Expose as ops; needs an unpacked+pwned iBSS artifact (reuse `op_create` output) |
| B16 | DFU Mode Helper (animated, per-device) | `device_dfuhelper` :1887 | Static text guide in `restore_view` | Replace/augment with a real per-device timer; a UX win, not just parity |
| — | Pwnage 2.0 / WTF mode (S5L8900) | `device_s5l8900xall` :1192, `device_entry_s5l8900` :929 | — | Only meaningful for iPhone1,1/iPod1,1 — low priority, fold into B14 if cheap |

### 6.3 SSH ramdisk gaps (`B17–B24`)

The existing SSH Ramdisk tab covers `op_create`/`op_boot`/`op_reset`/
`op_reboot`/`op_dump_blobs`/`op_clean`/`open_ssh_console` for A7–A11 + T2.
`restore.sh` has substantially more; `device_ramdisk` (:7159, 32-bit) vs
`device_ramdisk64` (:6949) is a whole second implementation we do not have.

| # | Feature | LIK | Gap |
|---|---|---|---|
| B17 | **32-bit ramdisk** (A4–A6, incl. A5-only `kdfu` path) | `device_ramdisk` :7159, `device_ramdisk_ios3exploit` :7715 | Nothing. Needs 32-bit iBSS/iBEC (no KBAG on 32-bit → different decrypt path than `firmware_keys.py`), exploit ramdisks per device/build, `nand-enable-reformat` bootargs for A4/A5/A6 |
| B18 | **iOS 8 ramdisks** (64-bit) | `resources/sshrd/ios8/*.patch`, `device_ramdisk_ios8` | Our port has no iOS 8 support; `linux_build_blocked()` refuses 16.1+ but nothing covers 8.x |
| B19 | Dump baseband + activation records | `device_dump` :11021, `device_dumprd` :11197, `device_dumpbb` :11150, `device_dumpactivation` :11115 | Per-iOS-version path divergence: `/usr/local/standalone` → `Baseband/<Mav5\|Mav7Mav8\|Trek>/…`; activation records move `root/Library/Lockdown` → `mobile/Library/mad` (iOS 8/9.0–9.2) → `containers/…/activation_records` + `data_ark.plist` (9.3+) |
| B20 | Per-version erase recipes (iOS 7/8 `nvram obliterate=1`, iOS 9+ `oblit-inprogress=5`) | `menu_ramdisk` :7803–7807 | `op_reset` does data erase; the two distinct nvram recipes per version are not modelled |
| B21 | Clear NVRAM / exploit enable-disable / DateTime | `device_ramdisk_setnvram` :7680, `menu_remove4` :6915, `device_send_rdtar` :6938, `device_datetime_cmd` :7748 | `LockdownOps.sync_time()` exists for Normal mode; the SSH-ramdisk variants do not |
| B22 | Install Bootstrap (iOS 7/8/9) / Untether (iOS 7) / OpenSSH (≤iOS 10) | `menu_ramdisk` :7812–7817 | — |
| B23 | Install TrollStore | `device_trollrestore` :12377, `resources/sshrd/trollstore.sh` | `restore_view` has the boot-arg injection UI; the **install** step (trollstore.py + venv + `pymobiledevice3<=6.2.0`) is missing |
| B24 | **Mount `/var/mobile`** (iOS 17+) | — | Not in LIK. `usr/bin/mount_ich` from `A12-A13-Ramdisk`'s `resources/ssh.tar.gz` mounts System/Preboot/xART/Data on iOS 17→27+ and is the candidate fix. Drop it into `assets/sshrd/sshtars/`, add its CDHash to the trustcache, test on hardware. `ich_ramdisk.op_mount` already calls whichever helper exists |

### 6.4 SHSH blobs (`B11–B13`)

| # | Feature | LIK | Gap |
|---|---|---|---|
| B11 | Save OTA blobs for a chosen version | `shsh_save` :3093, `menu_shsh` :8910 | We only dump *on-board* blobs (`op_dump_blobs`). This is the ipsw.me/Apple API path — a different mechanism. Also latest-version baseband compatibility check (`shsh_save bbcheck` :8974) |
| B12 | Onboard raw dump + convert to usable | `shsh_save_onboard dump` :8170, `shsh_convert_onboard` :8215, `menu_shsh_convert` :9042 | `op_dump_blobs` converts in-memory via `img4tool`; no raw-dump artifact, no 32-bit path (needs the IPSW selected first, `menu_shsh_onboard` :9004) |
| B13 | Cydia server blobs (32-bit) + 64-bit deverser + Cryptex/APTicket (x8A4, iOS 16+) | `shsh_save_cydia` :8260, `shsh_save_onboard64` :8094 | Also ECID → device-name mapping for blob filenames (`device_get_name` :948) |

### 6.5 Restore / downgrade (`B25+`)

The heaviest phase, and the one with the most upstream dependencies. Split it;
do not attempt it as one piece.

| # | Feature | LIK | Gap |
|---|---|---|---|
| B25 | Signed-OTA downgrade (6.1.3 / 8.4.1 / 10.3.3) | `restore_futurerestore` :6155, `ipsw_prepare_1033` :3278 | `restore_view`'s IPSW Restore is a plain `idevicerestore` flash. No SHSH/BB handling, no version matrix |
| B26 | Restore with SHSH blobs | `ipsw_get_url` :2692 + `restore_futurerestore` | Needs blob selection + futurerestore (`futurerestore_new`/`futurerestore_old`, both LIK-built) |
| B27 | Latest iOS restore (64-bit, `--use-dev`, `--use-pwndfu`) | `restore_latest` :6286, `restore_pwned64` :6697, `restore_notpwned64` :6713, `restore_prepare_pwnrec64` :6350 | — |
| B28 | powdersn0w restore | `ipsw_prepare_powder` :5652, `ipsw_prepare_powder_exploit` :5100 | Needs `powdersn0w_pub`, 32-bit bundles, `baseband`/`partitions` assets |
| B29 | DRA v6 restore | `ipsw_prepare_patchcomp` :5775 | — |
| B30 | Tethered restore | `ipsw_prepare_tethered` :5479 | — |
| B31 | Set Nonce Only (A7–A10) | `menu_restore` :9157 | — |
| B32 | DFU IPSW | `device_dfuipsw` :11442 | — |
| B33+ | **Custom IPSW creation** (30+ steps) | `ipsw_prepare*` :2878–6011, `ipsw_prepare_bundle` :3870, `ipsw_prepare_config` :3811, `ipsw_prepare_keys` :3631, `ipsw_bbdigest` :4304, `patch_iboot` :4436 | The single biggest item in LIK — its own multi-block project. `DeviceTree`/`RestoreDeviceTree`, `asr`, `iBoot`, `kernelcache`, `LLB`, `WTF` patch selection; `scab_template.img3`; logo conversion; `bspatch` diffs |
| B- | Multipatch / gas-gauge (error 29) | `ipsw_prepare_multipatch` :5159 | Flag-driven; bundles 4.3–6.1.3 components |
| B- | disable-bbupdate + stitch dumped baseband | `ipsw_bbreplace` :4338, `restore_download_bbsep` :6024 | Pairs with B19 |
| B- | Stitch dumped activation records | `ipsw_prepare_config` :3811, `device_actrec` | iOS ≤ 9.2.1 only |
| B- | Jailbreak-in-IPSW option | `ipsw_prepare_jailbreak` :3415 | — |
| B- | IPSW Downloader (standalone, no device) | `menu_ipsw_downloader` :9211 | Genuinely useful forensically — partial-ZIP the members you need |
| B- | Device-supported-version gating and warnings | `menu_restore` :9097, `ipsw_print_warnings` :9925 | iPad2,4 / iPhone5,[34] exceptions, "no blobs" warnings |

### 6.6 App & data management (`B2–B10`)

Cheap relative to §6.5, and much of it maps onto existing pymobiledevice3
services rather than new binaries. Each row is one block (B2–B10 in the index).

| # | Feature | LIK | Gap |
|---|---|---|---|
| B2 | (Re-)install dependency / version-update check | `version_get` :807, `version_update` :764 | Our deps are `requirements.txt`/`pyproject.toml`; port the *version-update check* only |
| B3 | List user / system / all apps | `menu_appmanage` :8525–8527 | `files_apps_view` has an installed-apps inspector; needs the user/system/all split |
| B4 | Install IPA | `device_appinst` :11902, `menu_ipa` :8705 | — |
| B5 | Backup encryption on/off/change password | `menu_backup_encryption` :8649 | Not present — `idevicebackup2 -i encryption …` equivalent |
| B6 | Erase all content and settings | `device_erase` :12364 | — |
| B7 | Pair device | `device_pair` :10809 | — |
| B8 | Attempt activation (`ideviceactivation`) | `device_activate` :11263 | `get_activation_state()` exists; the *activate* call does not. Very useful for iOS ≤ 4 |
| B9 | Export device info / battery info | `menu_miscutilities` :10634, :10645 | `get_battery_info()` exists; the *export to file* action does not |
| B10 | Data management: uicache / mount over SSH / raw FS / Cydia AutoInstall | `device_uicache` :12333, `menu_datamanage` :8573–8599 | `device_uicache` is straightforward (needs ramdisk). The mount rows need a decision: sshfs on Windows vs. an SFTP-backed browser. **Decision-gated.** |
| — | Dump app / all apps as IPA | `device_dumpapp` :12018 | Needs `resources/appdump/{clutch,clutch13,clutch204,ipainstaller,ipainstaller_legacy}` + rcky844 forks. Upstream marks it unmaintained — port last, or skip |
| — | Sideload IPA | `device_altserver` :11925 (AltServer-Linux + anisette-server), `device_plumesign` :11992 | AltServer-Linux and PlumeSign are Linux/macOS → WSL. anisette on Windows needs extra work; check before promising |
| — | Backup / Restore | `device_backup_create` :12343, `device_backup_restore` :12354 | **Done** (`restore_view` "Backup Restore") |
| — | Hacktivate / revert hacktivation | `device_hacktivate` :11280, `device_reverthacktivation` :11337 | Patches lockdownd. iOS 3.0–7.1.2 |
| — | Live console (`idevicesyslog`) | :10788 | **Done** (`syslog_view`) |

### 6.7 Phase 6 — 32-bit jailbreak payloads (`B-last`)

Only reachable once §6.1 and §6.2 exist. Assets live in `resources/jailbreak/`:
`g1lbertJB` (payload + per-device tars + `debs/`), `greenpois0n` per-device
tars, `aquila_4..7`, `evasi0n6/7-untether`, `daibutsu` (`untether.tar` +
`move.sh`), `fourothree`, `LukeZGD.tar`, `nopatcyh.tar`, `panguaxe.tar`,
`p0sixspwn.tar`, `everuntether.tar`, `zebra.tar`, `freeze.tar.gz`,
`dualbootstuff.tar`, `cydiasubstrate.tar`, `cydiahttpatch.tar`, plus
`fstab_{new,old,rw,7,8}` variants. Driver: `device_jailbreak` :10990,
`device_jailbreak_gilbert` :10994, `ipsw_prepare_jailbreak` :3415.

Version coverage worth encoding as a table (from the README): iPhone2G/touch1 →
3.1.3 only; iPhone3G/touch2 → 4.2.1/4.1/3.1.3; iPhone3GS → 3.0–6.1.6;
everything else 3.1.3–9.3.4 with exceptions.

### 6.8 Not porting (recorded so it isn't re-litigated)

- **FourThree Utility** (dualboot iPad 2 to iOS 4.3.x, `menu_fourthree` :8671) —
  upstream prints "Support … is no longer provided". Niche and long-dead.
- **`kdfu` for A7+ / `kurouta dori` (turdus merula)** — A6(X) pwning path;
  checkm8 covers the same ground for every device we support.
- **`iBoot32Patcher`-era rootless/rootful bootstrap for 32-bit** beyond §6.7's
  payload list — will follow if §6.7 lands.
- **`--debug`, `--old-menu`, `--no-finder`, `--enable-sudoloop`, `--use-usbmuxd2`,
  `usbmuxd2`, `--no-internet-check`, `--run-as-root`** — Linux/macOS scripting
  affordances with no GUI equivalent and no meaning on Windows.
- **macOS-only restore paths** — "restoring to latest iOS for 64-bit devices is
  not supported on macOS" upstream; on Windows we use native `idevicerestore`
  from pymobiledevice3 instead.

### 6.9 Sequencing summary

Execution follows the block index (§6.0.2): **B0 → B1a–B1f → B2–B10 → B11–B13
→ B14–B16 → B17–B24 → B25+ → B-last**. Rationale:
1. **B0/B1*** — the capability DB unblocks every later gate; pure data, no device.
2. **B2–B10** — cheapest wins, mostly existing pymobiledevice3 services, no new
   binaries; independent of the capability DB.
3. **B11–B13** (SHSH) — self-contained once B1 exists.
4. **B14–B16 / B17–B24** — highest-risk hardware work; needs real checkm8
   hardware (still owed, see §6.10).
5. **B25+** — restore/downgrade, split per row; custom IPSW last.
6. **B-last** — 32-bit jailbreak once the ramdisk work is proven.

Every block adds offline tests to `tests/` asserting *constructed argv* with the
runner stubbed — the approach that caught the `wsl_arg` and `paths.app_dir()`
bugs (AGENTS.md, "Asset paths and WSL argv").

### 6.10 Standing hardware gates

Slot these between blocks whenever a real device is available; each closes part
of §2.

- **G1 — SSH ramdisk on real checkm8.** `gaster pwn`, a full `Create` against an
  actual IPSW, `Boot`, the erase path, `op_dump_blobs`/`op_reset`/`op_clean` on
  A7–A11; confirm the DFU driver story (Zadig/WinUSB) on a clean Windows install.
- **G2 — whole A12/A13 usbliter8 tab on hardware** (currently unverified).
- **G3 — frozen PyInstaller build end-to-end.** Build, then confirm
  `dist_pymobile3/Pymobile3-GUI/Pymobile3-GUI.exe --run-pymobiledevice3 usbmux list`
  prints device JSON.