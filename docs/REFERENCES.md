# Reference Implementations & Upstream Projects

Everything Pymobile3-GUI is built from, ported from, or vendors binaries of.
Kept in one place so nobody re-investigates a provenance question.

---

## 1. Primary reference implementations

Codebases this project was extracted from, or whose behaviour it re-implements
in a GUI. Listed newest-first.

| Reference | Path | License | Role | Status |
|---|---|---|---|---|
| **Legacy iOS Kit** | `C:\Users\nick\Documents\GitHub\Legacy-iOS-Kit` | **GPL-3.0** | Behavioural reference for the legacy/checkm8 side of the toolkit: firmware restore & downgrade, jailbreak, SSH ramdisk (32-bit *and* 64-bit), SHSH blob saving, custom IPSW creation, baseband/activation dumping, sideloading, app dumping. Roadmap: `docs/TODO.md` §6 | **Feature parity in progress** |
| **RootForgeKit** | `RootForgeKit-main/` | (internal) | The pre-split codebase this project came out of. Every `pymobile3_gui` workspace descends from it. Paths in `docs/TODO.md` §1 are relative to its root. | Largely ported |

### Legacy iOS Kit — what it actually is

- Upstream: <https://github.com/LukeZGD/Legacy-iOS-Kit>
- One 12,600-line Bash script (`restore.sh`, 534 KB) + vendored binaries +
  ~2,000 firmware/jailbreak payload resources. 200 shell functions.
- **Supports Linux and macOS only. There are no Windows binaries.** Anything
  ported from it has to run through WSL, the same way the SSH Ramdisk tab
  already does (`wsl_tool()` in `core/backend/ramdisk_manager.py`).
- Defines *legacy devices* as everything vulnerable to a bootrom exploit
  (checkm8 and older): all 32-bit iOS devices plus A7/A8/A9/A10/A11.

### Licensing constraint — read before porting anything

`Legacy-iOS-Kit` is **GPL-3.0**. This project is MIT (`README.md`) and has no
`LICENSE` file yet (see `docs/TODO.md` §3). Therefore:

- **Do not copy `restore.sh` code, comments, or structure into this tree.** A
  verbatim or lightly-reworded port is still a GPL derivative and would
  contaminate the whole project.
- **Do re-implement from behaviour.** The wiki documents every feature, and
  each operation is a thin orchestration over third-party tools whose own
  licenses apply independently. That is the same position `ramdisk_manager.py`
  already takes with `SSHRD_Script` (GPL) — reimplemented, not copied.
- **Vendor binaries from their own upstream repos, not from this repo.** The
  `bin/linux/*` and `bin/macos/*` trees here are redistributed collections; pull
  each tool from its project instead and record its license under
  `pymobile3_gui/assets/sshrd/licenses/` (the pattern already used there for
  img4tool, libirecovery, sshpass, kerneldiff, KPlooshFinder, jq, gtar,
  xcbuild, libdmg-hfsplus, partialZipBrowser).
- Resources worth mining for *reference* (rebuild, don't copy): the firmware
  bundles and `.patch` sets under `resources/patch/`, `resources/firmware/`,
  `resources/sshrd/ios8/` (which covers iOS 8 64-bit ramdisks our current
  port does not), and the jailbreak payload tars under `resources/jailbreak/`.

---

## 2. Upstream toolkits we port behaviour from

| Project | Used for | How we use it |
|---|---|---|
| [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) (pinned **10.x**) | Lockdown, AFC, DVT instruments, syslog, backups, RSD tunnel | Dispatched as a CLI subprocess via `--run-pymobiledevice3`; also imported for lockdown (`core/backend/lockdown_ops.py`). Command names drift between majors — the pin is load-bearing. |
| [SSHRD_Script](https://github.com/verygenericname/SSHRD_Script) | checkm8 SSH ramdisk, A7–A11 + T2 | Reimplemented in `core/backend/ramdisk_manager.py` (`op_create`/`op_boot`/`op_reset`/`op_reboot`/`op_dump_blobs`/`op_clean`, `open_ssh_console`). GPL — same constraint as above. |
| [The Apple Wiki](https://theapplewiki.com/) | Published iBSS/iBEC IV+Key per build | `core/backend/firmware_keys.py` fetches and decrypts locally, so the bootchain never needs the device's GID0 key over USB. |
| [ipsw.me API](https://api.ipsw.me/v4/device) | Signed firmware list + download URLs | `fetch_firmware_versions()` / `resolve_ipsw_url()` in `ramdisk_manager.py`. |
| `A12-A13-Ramdisk` (ICHA12A13) | usbliter8 SSH ramdisk, A12 + A13 | Behaviour port in `core/backend/ich_ramdisk.py` (experimental). See §2.1 — this one is *executed in place*, not vendored. |
| [usbliter8](https://github.com/prdgmshift/usbliter8) / [usbliter8ra1n](https://github.com/Leeksov/usbliter8ra1n) | The pwn that puts an A12/A13 into pwned DFU | **Not integrated.** Requires RP2350 hardware; no Windows host build exists, so the DFU → Recovery handoff stays outside this app. |

### 2.1 `A12-A13-Ramdisk` — executed in place, never vendored

A local checkout at `%USERPROFILE%\Desktop\A12-A13-Ramdisk` (override with the
`PMD3_ICH_TOOLKIT` env var, or the field on the tab). `ich_ramdisk.py` runs its
`patch/*.py` patchers with WSL's interpreter, and reads `resources/IM4M_<cpid>`
for the per-chip APTicket.

**Why it is not vendored:** the project ships no `LICENSE` file and the patchers
carry no license headers. This repo is MIT, so copying them in would be an
undocumented derivative. Executing a user's own checkout is not. Everything the
app itself owns — the orchestration, the manifest/component resolution, the boot
sequence — is reimplemented in `ich_ramdisk.py`.

**Two steps are macOS-only and are deliberately absent** (both fail closed in
the UI, see the tab banner):

- **APFS ramdisk expand + inject.** An A12+ `RestoreRamDisk` is an APFS
  container; upstream does this with `hdiutil attach` /
  `diskutil apfs resizeContainer` / `hdiutil create -srcfolder`. No Windows or
  WSL equivalent can write into an APFS volume: Ubuntu's `apfsprogs` provides
  only `mkapfs`/`apfsck`/`apfs-snap` (no srcfolder import), `apfs-fuse` is
  read-only, and `libfsapfs-utils` adds no file injection. The tab therefore
  takes an already-expanded, SSH-injected ramdisk image as input.
- **The usbliter8 handoff.** `usbliter8_boot` is a Mach-O binary. The tab
  starts at Recovery and refuses a device still in pwned DFU rather than
  pretending the chain loaded.

Worth mining from its `resources/ssh.tar.gz` regardless: `usr/bin/mount_ich`,
which mounts System / Preboot / xART / Data on iOS 17 → 27+. That is the piece
the checkm8 `/var/mobile` Known Gap needs.

---

## 3. Vendored binaries

All under `pymobile3_gui/assets/sshrd/`, shipped through `pymobile3_gui.spec`'s
`datas`. Licenses recorded in `assets/sshrd/licenses/`.

| Tool | Where | Role |
|---|---|---|
| `img4`, `img4tool`, `iBoot64Patcher`, `hfsplus`, `dmg`, `kerneldiff`, `KPlooshFinder`, `PlistBuddy`, `jq`, `gtar`, `xcbuild`, `partialZipBrowser` | `Linux/` | IPSW/bootchain unpack, repack, sign, diff — all run in WSL |
| `pzb` | `Linux/` | Partial-zip fetch of individual IPSW members |
| `irecovery`, `iproxy`, `sshpass` | `Linux/` + `win/` | Bootchain send, USB port forward, SSH auth |
| `gaster`, `irecovery`, `iproxy` (+ `libusb`/`libimobiledevice` DLLs) | `win/` | Native Windows DFU/USB steps |

Known Windows-specific constraints are recorded in `AGENTS.md` under
"DFU over USB on Windows" — `gaster` needs `USB_TIMEOUT=30000`, its Windows
build never exits after a successful `pwn`, and Apple's DFU driver binds the
interface exclusively (`ensure_dfu_driver()` re-applies libusbK before each pwn).

---

## 4. Background reading

Maintainer-facing, not code dependencies:

- [Legacy iOS Kit wiki](https://github.com/LukeZGD/Legacy-iOS-Kit/wiki) —
  "How to Use", "Restore-Downgrade", "Saving SHSH blobs", "Jailbreaking",
  "App Management", "Data Management", "Misc Utilities", "powdersn0w",
  "DRA v6", "TrollStore", "Troubleshooting". This is the functional spec for
  `docs/TODO.md` §6.
- [The Apple Wiki](https://theapplewiki.com/wiki/IBoot_(Bootloader)) — mapping
  a raw on-board dump back to an iBoot version.
- [sep.lol/legacy](https://sep.lol/legacy/index.html) — SEP compatibility for
  A6(X) (`turdus merula`); removes the SEP/BB constraint on A9(X)/A10(X).