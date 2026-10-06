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
- [ ] **No `LICENSE` file.** `README.md` says "MIT — see LICENSE file" but the
      file was never committed. It matters more now that `docs/REFERENCES.md`
      documents a GPL-3.0 boundary we intend to keep — the MIT grant has to
      actually exist. Add the MIT text.

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
(`restore.sh`, 12,600 lines / 200 functions / GPL-3.0). Provenance, licensing
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

### 6.1 Capability database — prerequisite for everything else

Every menu in `restore.sh` is gated on device type / processor / mode / iOS
version. None of that gating exists here, so **this lands first**.

| Data | LIK source | Notes |
|---|---|---|
| HardwareModel → ProductType, both directions | `device_get_info` :1367–1529 | ~70 entries. Includes two quirks worth porting verbatim as *data*: iPod touch 4 on iOS 7 reports as `iPhone3,1/3,3` (N81AP override), and iPad2,1 is force-mapped to `k93`. |
| Processor generation (`device_proc` 1–11) | :1537–1556 | S5L8900=1, A4=4, A5=5, A6=6, A7=7, A8=8, A9=9, A10/A11=10, anything else=11. Also `device_checkm8ipad` for iPad6/7. |
| Signed-target version per device (`device_use_vers`/`_build`) | :1598–1635 | The OTA-downgrade matrix: 3.1.3/7E18 for iPhone1,1 … 10.3.3/14G60 for A7. |
| Latest-known version per device | :1636–1657 | Hardcoded, with an ipsw.me fallback. |
| Baseband to use + its SHA1 | :1673–1703 | Per-device `bbfw` name and digest; `Trek`/`Mav5`/`Mav7Mav8` families. |
| Activation-record candidacy | :1709–1726 | `9900candidate` (iPhone4,1 / iPhone5,2 / iPad2,7 / iPad3,[26]) and `activationissue` sets, with the auto-enable ladder. |
| powdersn0w / DRA v6 eligibility | :1734–1750 | `device_can_powder`, `device_can_drav6`. |
| Manual device entry | `device_entry` :887, `..._s5l8900` :929 | Needed for devices where lockdown reports nothing (iOS 2.x and lower). |
| ECID (hex→dec), UDID, build, mode detection | `device_get_info` :1225–1320 | Recovery/DFU/ WTF/Normal mode split via `irecovery -q` + `ideviceinfo`. |

Landing spot: a new `core/backend/device_db.py` — a pure-data table plus
lookup helpers, with **offline unit tests in `tests/test_device_db.py`** (no
device needed). This is the highest-value, lowest-risk item in the whole
roadmap: it is pure data, it is what the UI needs to decide which buttons to
enable, and every later phase queries it.

### 6.2 Phase 1 — DFU / Recovery mode plumbing

Everything else assumes the device can be *put into* a mode. Today the app only
polls for a DFU device; it cannot move one there.

| Feature | LIK | What we have | Needed |
|---|---|---|---|
| Enter kDFU (32-bit) | `device_enter_mode` :2051 | — | Button in Recovery/DFU guides tab; timed button-press sequence per model |
| Enter pwnDFU (32-bit, A6+) | same + `device_send_unpacked_ibss` :2395 | `gaster_pwn()` exists but is only called from `op_boot`/`op_reset` | Expose as its own op; needs an unpacked+pwned iBSS artifact |
| Send Pwned iBSS (A5/A6) | `device_enter_mode` pwnDFU | — | New op; reuse `op_create`'s iBSS output |
| kDFU send (`iBSS`/`iBEC` to DFU) | `device_send_unpacked_ibss` :2395 | `op_boot` does this for 64-bit | Generalize |
| Exit Recovery (`irecovery -n`) | `main` case `exitrecovery` | — | Trivial op + warning that tethered devices need Just Boot instead |
| Just Boot + history | `menu_justboot` :11554, `..._history` :11674, `device_justboot` :11797 | — | Menu of `all_flash`/restore-mode images with a persisted "last used" list |
| DFU Mode Helper (animated, per-device) | `device_dfuhelper` :1887 | Static text guide in `restore_view` | Replace/augment with a real per-device timer; this is a UX win, not just parity |
| Pwnage 2.0 / WTF mode (S5L8900) | `device_s5l8900xall` :1192, `device_entry_s5l8900` :929 | — | Only meaningful for iPhone1,1/iPod1,1 — low priority |

### 6.3 Phase 2 — SSH ramdisk gaps

The existing SSH Ramdisk tab covers `op_create`/`op_boot`/`op_reset`/
`op_reboot`/`op_dump_blobs`/`op_clean`/`open_ssh_console` for A7–A11 + T2.
`restore.sh` has substantially more, and `device_ramdisk` (:7159, 32-bit) vs
`device_ramdisk64` (:6949) is a whole second implementation we do not have.

| Feature | LIK | Gap |
|---|---|---|
| **32-bit ramdisk** (A4–A6, incl. A5-only `kdfu` path) | `device_ramdisk` :7159, `device_ramdisk_ios3exploit` :7715 | Nothing. Needs 32-bit iBSS/iBEC (no KBAG on 32-bit → different decrypt path than `firmware_keys.py`), exploit ramdisks per device/build, and `nand-enable-reformat` bootargs for A4/A5/A6 |
| **iOS 8 ramdisks** (64-bit) | `resources/sshrd/ios8/*.patch`, `device_ramdisk_ios8` | Our port has no iOS 8 support; `linux_build_blocked()` refuses 16.1+ but nothing covers 8.x |
| Dump baseband + activation records | `device_dump` :11021, `device_dumprd` :11197, `device_dumpbb` :11150, `device_dumpactivation` :11115 | Nothing. Note the per-iOS-version path divergence: `/usr/local/standalone` → `Baseband/<Mav5\|Mav7Mav8\|Trek>/…`; activation records move from `root/Library/Lockdown` → `mobile/Library/mad` (iOS 8/9.0–9.2) → `containers/…/activation_records` + `data_ark.plist` (iOS 9.3+) |
| Erase (iOS 7/8) `nvram obliterate=1`, erase (iOS 9+) `oblit-inprogress=5` | `menu_ramdisk` :7803–7807 | `op_reset` does data erase; the two distinct nvram recipes per version are not modelled |
| Clear NVRAM `nvram -c` | `device_ramdisk_setnvram` :7680 | — |
| Enable/disable exploit (`nvram remove4` toggle) | `menu_remove4` :6915, `device_send_rdtar` :6938 | — |
| Get iOS version over SSH | `device_ramdisk_iosvers` :7757 | `op_dump_blobs` already does this as step 2 — extract it |
| Update DateTime (`device_datetime_cmd`) | `device_datetime_cmd` :7748, `device_update_datetime` :10795 | `LockdownOps.sync_time()` exists for Normal mode; the SSH-ramdisk variant does not |
| Install Bootstrap (iOS 7/8/9) | `menu_ramdisk` :7812 | — |
| Install Untether (iOS 7) | :7815 | — |
| Install OpenSSH (iOS 10 and lower) | :7817 | — |
| Install TrollStore | `device_trollrestore` :12377, `resources/sshrd/trollstore.sh` | `restore_view` already has the boot-arg injection UI; the **install** step (trollstore.py + venv + `pymobiledevice3<=6.2.0`) is missing |
| **Mount `/var/mobile`** (iOS 17+) | — | Not in LIK. Our payload only has `mount_filesystems`; `usr/bin/mount_ich` from `A12-A13-Ramdisk`'s `resources/ssh.tar.gz` mounts System/Preboot/xART/Data on iOS 17→27+ and is the candidate fix. Next: drop it into `assets/sshrd/sshtars/`, add its CDHash to the trustcache, test on hardware. `ich_ramdisk.op_mount` already calls whichever helper exists |

### 6.4 Phase 3 — SHSH blobs

| Feature | LIK | Gap |
|---|---|---|
| Save OTA blobs for a chosen version | `shsh_save` :3093, `menu_shsh` :8910 | We only dump *on-board* blobs (`op_dump_blobs`). This is the ipsw.me/Apple API path, a completely different mechanism |
| Latest-version baseband compatibility check | `shsh_save bbcheck` :8974 | — |
| Cydia server blobs (32-bit) | `shsh_save_cydia` :8260 | — |
| Onboard raw dump + convert to usable | `shsh_save_onboard dump` :8170, `shsh_convert_onboard` :8215, `menu_shsh_convert` :9042 | `op_dump_blobs` converts in-memory via `img4tool`; no raw-dump artifact, no 32-bit path (which needs the IPSW selected first, `menu_shsh_onboard` :9004) |
| Onboard blobs for jailbroken 64-bit (deverser) | `shsh_save_onboard64` :8094 | — |
| Cryptex seed + APTicket (x8A4, iOS 16+) | `shsh_save_onboard64` :8094 | — |
| ECID → device name mapping for blob filenames | `device_get_name` :948 | — |

### 6.5 Phase 4 — Restore / downgrade

The heaviest phase, and the one with the most upstream dependencies. Split it;
do not attempt it as one piece.

| Feature | LIK | Gap |
|---|---|---|
| Signed-OTA downgrade (6.1.3 / 8.4.1 / 10.3.3) | `restore_futurerestore` :6155, `ipsw_prepare_1033` :3278 | `restore_view`'s IPSW Restore is a plain `idevicerestore` flash. No SHSH/BB handling, no version matrix |
| Restore with SHSH blobs | `ipsw_get_url` :2692 + `restore_futurerestore` | Needs blob selection + futurerestore (`futurerestore_new`/`futurerestore_old`, both LIK-built) |
| Latest iOS restore (64-bit, `--use-dev`, `--use-pwndfu`) | `restore_latest` :6286, `restore_pwned64` :6697, `restore_notpwned64` :6713, `restore_prepare_pwnrec64` :6350 | — |
| powdersn0w restore | `ipsw_prepare_powder` :5652, `ipsw_prepare_powder_exploit` :5100 | Needs `powdersn0w_pub`, 32-bit bundles, `baseband`/`partitions` assets |
| DRA v6 restore | `ipsw_prepare_patchcomp` :5775 | — |
| Tethered restore | `ipsw_prepare_tethered` :5479 | — |
| Set Nonce Only (A7–A10) | `menu_restore` :9157 | — |
| DFU IPSW | `device_dfuipsw` :11442 | — |
| **Custom IPSW creation** (30+ steps) | `ipsw_prepare*` :2878–6011, `ipsw_prepare_bundle` :3870, `ipsw_prepare_config` :3811, `ipsw_prepare_keys` :3631, `ipsw_bbdigest` :4304, `patch_iboot` :4436 | The single biggest item in LIK. `DeviceTree`/`RestoreDeviceTree`, `asr`, `iBoot`, `kernelcache`, `LLB`, `WTF` patch selection; `scab_template.img3`; logo conversion; `bspatch` diffs |
| Multipatch / gas-gauge (error 29) | `ipsw_prepare_multipatch` :5159 | Flag-driven; bundles 4.3–6.1.3 components |
| disable-bbupdate + stitch dumped baseband | `ipsw_bbreplace` :4338, `restore_download_bbsep` :6024 | Pairs with §6.3's baseband dump |
| Stitch dumped activation records | `ipsw_prepare_config` :3811, `device_actrec` | iOS ≤ 9.2.1 only |
| Jailbreak-in-IPSW option | `ipsw_prepare_jailbreak` :3415 | — |
| IPSW Downloader (standalone, no device) | `menu_ipsw_downloader` :9211 | Genuinely useful forensically — partial-ZIP the members you need |
| Device-supported-version gating and warnings | `menu_restore` :9097, `ipsw_print_warnings` :9925 | iPad2,4 / iPhone5,[34] exceptions, "no blobs" warnings |

### 6.6 Phase 5 — App & data management

Cheap relative to phase 4, and much of it maps onto existing pymobiledevice3
services rather than new binaries.

| Feature | LIK | Gap |
|---|---|---|
| Install IPA | `device_appinst` :11902, `menu_ipa` :8705 | — |
| List user / system / all apps | `menu_appmanage` :8525–8527 | `files_apps_view` has an installed-apps inspector; needs the user/system/all split |
| Dump app / all apps as IPA | `device_dumpapp` :12018 | Needs `resources/appdump/{clutch,clutch13,clutch204,ipainstaller,ipainstaller_legacy}` + rcky844 forks. Upstream marks it unmaintained — port last, or skip |
| Sideload IPA | `device_altserver` :11925 (AltServer-Linux + anisette-server), `device_plumesign` :11992, `menu_plumesign_accounts` :8820 | AltServer-Linux and PlumeSign are **Linux/macOS** → WSL. anisette on Windows needs extra work; check before promising |
| Mount device over SSH (sshfs) / raw FS / Cydia AutoInstall drop | `menu_datamanage` :8573–8599 | Needs sshfs on the Windows side, or SFTP-backed file browser instead. The Cydia variant is iOS-only (pre-9) |
| Backup / Restore | `device_backup_create` :12343, `device_backup_restore` :12354 | Done (`restore_view` "Backup Restore") |
| Backup encryption on/off/change password | `menu_backup_encryption` :8649 | Not present — `idevicebackup2 -i encryption …` equivalent |
| Erase all content and settings | `device_erase` :12364 | — |
| Pair device | `device_pair` :10809 | — |
| Attempt activation (`ideviceactivation`) | `device_activate` :11263 | `get_activation_state()` exists; the *activate* call does not. Very useful for iOS ≤ 4 |
| Hacktivate / revert hacktivation | `device_hacktivate` :11280, `device_reverthacktivation` :11337 | Patches lockdownd. iOS 3.0–7.1.2 |
| Export device info / battery info | `menu_miscutilities` :10634, :10645 | `get_battery_info()` exists; the *export to file* action does not |
| Run uicache over SSH | `device_uicache` :12333 | — |
| Live console (`idevicesyslog`) | :10788 | Done (`syslog_view`) |
| (Re-)install dependencies | `install_depends` :668 | N/A — our deps are `requirements.txt` / `pyproject.toml`. The *version-update check* (`version_get` :807, `version_update` :764) is worth porting |

### 6.7 Phase 6 — 32-bit jailbreak payloads

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

1. **§6.1** capability database (`device_db.py` + tests) — unblocks all of it.
2. **§6.6** app/data management — cheapest wins, mostly existing pymobiledevice3
   services, no new binaries.
3. **§6.2** DFU/Recovery plumbing + **§6.3** 32-bit & iOS 8 ramdisk — the
   highest-risk hardware work; needs real checkm8 hardware (still owed per §2).
4. **§6.4** SHSH suite — self-contained once §6.1 exists.
5. **§6.5** restore/downgrade, split per row; custom IPSW last.
6. **§6.7** 32-bit jailbreak payloads, once the ramdisk work is proven.

Every phase adds offline tests to `tests/` asserting *constructed argv* with the
runner stubbed — the approach that caught the `wsl_arg` and `paths.app_dir()`
bugs (AGENTS.md, "Asset paths and WSL argv").
