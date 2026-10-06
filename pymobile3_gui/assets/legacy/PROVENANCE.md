# Provenance — `assets/legacy`

What each file in this tree is, where it came from, and why it is allowed to
be here. Read `README.md` first for the rule this file exists to enforce.

Last updated 2026-10-05. Regenerate the size/tree-hash footer with
`scripts/legacy_inventory.py`.

---

## 1. `manifests/` — 28 files, 1,116,579 bytes

**What they are.** Apple's `BuildManifest.plist`, lifted verbatim out of public
signed IPSWs. Not authored by Legacy iOS Kit and not authored by us — Apple
publishes them inside every firmware package.

**Why here.** Pure device facts in a documented serialisation (Apple plist
DTD). No author, no license grant needed on our side; the same reasoning that
lets any restore tool read them out of an IPSW at runtime.

**Where they came from.** `Legacy-iOS-Kit/resources/manifest/`. That
directory is a convenience cache so the script does not re-download a 3 GB
IPSW just to read 40 KB of metadata. Ours serves the same purpose — with the
difference that our loader reads the *device's own* manifest whenever one is
available and only falls back to this table for the signed-OTA matrix.

**Per-file contents.** `ProductType`, build, `DeviceClass` (hardware model),
`ApChipID` / `ApBoardID`, `RestoreBehavior`, and component count:

| ProductType | Build | DeviceClass | ApChipID / ApBoardID | RestoreBehavior | Components | Bytes |
|---|---|---|---|---|---|---|
| `iPad2,1` | 10B329 | `k93ap` | 0x8940 / 0x04 | Update | 20 | 9,915 |
| `iPad2,1` | 12H321 | `k93ap` | 0x8940 / 0x04 | Update | 19 | 41,619 |
| `iPad2,2` | 10B329 | `k94ap` | 0x8940 / 0x06 | Update | 21 | 11,147 |
| `iPad2,2` | 12H321 | `k94ap` | 0x8940 / 0x06 | Update | 20 | 42,851 |
| `iPad2,3` | 10B329 | `k95ap` | 0x8940 / 0x02 | Update | 21 | 11,332 |
| `iPad2,3` | 12H321 | `k95ap` | 0x8940 / 0x02 | Update | 20 | 43,036 |
| `iPad2,4` | 12H321 | `k93aap` | 0x8942 / 0x06 | Update | 19 | 41,529 |
| `iPad2,5` | 12H321 | `p105ap` | 0x8942 / 0x0A | Update | 19 | 41,537 |
| `iPad2,6` | 12H321 | `p106ap` | 0x8942 / 0x0C | Update | 20 | 43,522 |
| `iPad2,7` | 12H321 | `p107ap` | 0x8942 / 0x0E | Update | 20 | 43,522 |
| `iPad3,1` | 12H321 | `j1ap` | 0x8945 / 0x00 | Update | 19 | 41,532 |
| `iPad3,2` | 12H321 | `j2ap` | 0x8945 / 0x02 | Update | 20 | 43,344 |
| `iPad3,3` | 12H321 | `j2aap` | 0x8945 / 0x04 | Update | 20 | 43,366 |
| `iPad3,4` | 12H321 | `p101ap` | 0x8955 / 0x00 | Update | 19 | 41,536 |
| `iPad3,5` | 12H321 | `p102ap` | 0x8955 / 0x02 | Update | 20 | 43,521 |
| `iPad3,6` | 12H321 | `p103ap` | 0x8955 / 0x04 | Update | 20 | 43,521 |
| `iPad4,1` | 14G60 | `j71ap` | 0x8960 / 0x10 | Erase | 21 | 48,225 |
| `iPad4,2` | 14G60 | `j72ap` | 0x8960 / 0x12 | Erase | 22 | 50,114 |
| `iPad4,3` | 14G60 | `j73ap` | 0x8960 / 0x14 | Erase | 22 | 50,114 |
| `iPad4,4` | 14G60 | `j85ap` | 0x8960 / 0x0A | Erase | 21 | 48,231 |
| `iPad4,5` | 14G60 | `j86ap` | 0x8960 / 0x0C | Erase | 22 | 50,120 |
| `iPhone4,1` | 10B329 | `n94ap` | 0x8940 / 0x08 | Update | 21 | 11,124 |
| `iPhone4,1` | 12H321 | `n94ap` | 0x8940 / 0x08 | Update | 20 | 42,861 |
| `iPhone5,1` | 12H321 | `n41ap` | 0x8950 / 0x00 | Update | 20 | 43,571 |
| `iPhone5,2` | 12H321 | `n42ap` | 0x8950 / 0x02 | Update | 20 | 43,571 |
| `iPhone6,1` | 14G60 | `n51ap` | 0x8960 / 0x00 | Erase | 22 | 50,117 |
| `iPhone6,2` | 14G60 | `n53ap` | 0x8960 / 0x02 | Erase | 22 | 50,117 |
| `iPod5,1` | 12H321 | `n78ap` | 0x8942 / 0x00 | Update | 19 | 41,584 |

`0x8960` is T8010 (A7) — which is why `RestoreBehavior` flips to `Erase` at
exactly the A7 boundary and nowhere earlier. That is a useful cross-check on
the table: it agrees with the processor generation derived independently from
ProductType, so a bad row is easy to spot.

**Not here.** iOS 16+ manifests. Apple's BuildManifest schema gained fields
after iOS 10 and those are not cached; `fetch_firmware_versions()` covers them.

---

## 2. `patches/` — 49 files, 12,934 bytes

**What they are.** bsdiff binary diffs (`BSDIFF40` / `BSDIFF407` header,
followed by bzip2-compressed control/diff/extra blocks). Applied with
`bspatch`. Two families:

| Family | Count | Bytes each | Applies to | Effect |
|---|---|---|---|---|
| `iBSS.<model>.RELEASE.im4p.patch` | 18 | 169–189 | `Firmware/dfu/iBSS.<model>.RELEASE.im4p` | Swaps the AMFI check so the patched iBSS will pwn/boot |
| `iBEC.<model>.RELEASE.im4p.patch` | 18 | 309–367 | `Firmware/dfu/iBEC.<model>.RELEASE.im4p` | Companion iBEC patch — iBEC validates what iBoot hands it |
| `kernelcache.release.<model>.bpatch` | 13 | 278 | `kernelcache.release.<model>` | AMFI / code-signing bypass in the kernel |

`<model>` values are the Apple hardware-model tags, not ProductTypes:
`d10`/`d11` (A9 iPhone8,x), `ipad4`/`ipad4b`/`ipad4bm`, `ipad5`/`ipad5b`,
`iphone6`, `n56`/`n61` (A7), `n66`/`n66m` (A8), `n69`/`n69u` (A8 SE),
`n71`/`n71m` (A9), `n102` (A10 iPod7,1), `n112` (A11 iPod9,1).

**Why here.** A bsdiff patch is a list of byte ranges. It is data in a format
published by Colin Percival, not an authored work — the same category as a
`.sha1` file or a unified diff of a config value.

**Where they came from.** `Legacy-iOS-Kit/resources/sshrd/`. LIK itself
credits [Nathan's SSHRD_Script](https://github.com/verygenericname/SSHRD_Script)
for the 64-bit ramdisk work; our existing `assets/sshrd/` came from there.
Copying the *same* patches from the *same* lineage into a second tree is a
rearrangement, not a new grant — but it is still recorded here so the
provenance chain is auditable rather than assumed.

**Also here.** `kernelcache.release.iphone7.bpatch` and
`...iphone8b.bpatch` and `...iphone9.bpatch` do not follow the `<model>`
convention — they are iPhone marketing names, and there is no
`iBSS`/`iBEC` counterpart for them. Carried over unreviewed; **verify before
use** and expect them to be unused.

---

## 3. `patches/ios8/` — 32 files, 7,360 bytes

**What they are.** The same two families as §2, for iOS **8.x** ramdisks:
`iBSS.j71…n61.RELEASE.im4p.patch` (16) and `iBEC.j71…n61.RELEASE.im4p.patch`
(16). Models span A7 (`j71`–`j73`, `n51`–`n61`) and A8 (`j81`–`j87m`, `n102`).

**Why here.** Same argument as §2.

**Why it matters.** Our existing SSH ramdisk port has no iOS 8 support at all —
`linux_build_blocked()` in `ramdisk_manager.py` only guards the 16.1+ upper
bound. These 32 patches plus the matching `kernelcache.release.*.bpatch` are
what closing that gap looks like at the data layer, and they are the reason §6.3
of the roadmap lists "iOS 8 ramdisks" separately from "32-bit ramdisk".

**Where they came from.** `Legacy-iOS-Kit/resources/sshrd/ios8/`. LIK credits
exploit3dguy's iArchive ramdisk tar for the iOS 8 base; the patches themselves
sit alongside it in that directory.

---

## 4. Deliberately **not** copied

Listed so nobody re-derives the decision. Full reasoning in `README.md`.

| LIK path | Size | Why not |
|---|---|---|
| `resources/firmware/src/partition`, `partition_iphone5` | 6.5 KB | Bash scripts. Rewrite — they are ~10 lines of `rm`/`mv` against a mounted `/mnt1`. |
| `resources/firmware/src/{bin,bin4,ios9}.tar`, `reboot4`, `reboot4_nbr` | 3.9 MB | Device-side payload bundles with no clear upstream. Re-derive when §6.2/§6.3 needs them, sourcing from the named community repos. |
| `resources/firmware/src/scab_template.img3`, `sshrd/IM4M7\|8\|9\|10` | 24 KB | IMG3/IMG4 manifest blobs of unclear authorship, and the `IM4M*` files carry per-component `EKEY`/`EPRO`/`ESEC` structures whose provenance we cannot account for. Do not ship unattributable crypto material. |
| `resources/firmware/src/target/*/exploit` | 12 MB | 512 KB exploit-ramdisk payloads × 23, from OdysseusOTA / Pingzi610 / Ralph0045 / m1zole. Re-fetch per exploit when §6.3 lands, with attribution. |
| `resources/firmware/FirmwareBundles/**/*.patch` | 26 MB | 320 files from OdysseusOTA, alitek12, gjest, selfisht, Ralph0045. Third-party, individually licensed. §6.5 needs them — pull per-bundle then. |
| `resources/patch/{asr,re,WTF…}` | varies | `asr` is a patched Mach-O (`CE FA ED FE`), not a diff. Needs its own provenance. |
| `resources/patch/{fourthree,odysseus,old,touch4-ios7,1033}` | ~7 MB | Same as FirmwareBundles — third-party patch collections. |
| `resources/jailbreak/**` | 36 MB | Cydia Substrate, OpenSSL/OpenSSH, evasi0n, Pangu, p0sixspwn, g1lbertJB, greenpois0n, Aquila, DaibutsuCFW, `.deb` packages. Genuinely needed for §6.7, but 148 files and ~15 distinct upstreams — vendor per-tool, not as a block. |
| `resources/appdump/*` | 2.4 MB | Clutch / ipainstaller binaries (rcky844 forks). Upstream LIK itself prints "not actively maintained". Last or never. |
| `resources/kloader/*` | 0.2 MB | kloader for iOS 4/5, from three different sources. §6.8 marks the iOS 4/5 route out of scope. |
| `resources/payload`, `resources/ssh_config`, `resources/trollrestore-oldpy_requirements.txt` | <1 KB | Project-specific config for a Linux shell script. Nothing to port. |
| `bin/linux/**`, `bin/macos/**` | ~200 MB | Redistributed collections of ~50 tools. Vendor per-tool from upstream with its own license in `licenses/` — the pattern `assets/sshrd/licenses/` already uses. |

---

## 5. Inventory footer

Regenerate with `scripts/legacy_inventory.py`; `tests/test_legacy_assets.py`
asserts these, so drift fails CI rather than shipping silently.

```
manifests      28 files   1,116,579 bytes   tree sha256 3008ac7c905ddee4…
patches        49 files      12,934 bytes   tree sha256 7d1371342102a8ad…
patches/ios8   32 files       7,360 bytes   tree sha256 0a721e06b832c144…
```
