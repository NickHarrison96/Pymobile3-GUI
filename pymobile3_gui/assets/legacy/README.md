# `assets/legacy` — Legacy iOS Kit static resources

Shipped, read-only data for the Legacy iOS Kit feature-parity work
(`docs/TODO.md` §6). Resolved at runtime by
`core/backend/legacy_assets.py` — never hardcode a path into this folder.

```
assets/legacy/
├── README.md         ← you are here
├── PROVENANCE.md     ← what each file is and where it came from
├── licenses/         ← per-item upstream license texts
├── manifests/        ← Apple BuildManifest.plist, 28 files
├── patches/          ← bsdiff patches, 49 files
│   └── ios8/         ← iOS 8 64-bit ramdisk patches, 32 files
```

## What belongs here, and what does not

This tree exists to hold **data, not code**. The distinction is a licensing
requirement, not a style preference: Legacy iOS Kit is GPL-3.0 and this project
is MIT, so no part of that project can be copied here — see
`docs/REFERENCES.md` §1.

**Allowed** — facts about Apple devices and firmware:

- Apple's own metadata (`BuildManifest.plist`, extracted from public IPSWs).
- Binary diffs in a documented public container format (BSDIFF40/407 patches).
- Configuration plists whose contents are device facts.

**Not allowed** — anything with an author:

- Shell scripts, Python, or any source from `restore.sh` or its helpers.
  Reimplement. `firmware/src/partition` is a good example: 3 KB of obvious
  `rm`/`mv` commands that run inside a device-side ramdisk, and still cheaper
  to rewrite (10 lines) than to license.
- Prebuilt executables from LIK's `bin/linux/*`, `bin/macos/*`, `appdump/*`
  or `kloader/*`. Vendor those from their own upstream repos instead and drop
  the license in `licenses/`.
- The jailbreak payload tars in `resources/jailbreak/` (36 MB, mixed
  provenance — Cydia Substrate, OpenSSL, evasi0n, Pangu, g1lbertJB,
  greenpois0n, debs). Deferred until §6.7 and re-vendored per-tool.
- Firmware bundles under `resources/firmware/FirmwareBundles/` (320 `.patch`
  files). Provenance is OdysseusOTA / alitek12 / gjest / selfisht / Ralph0045 —
  all third parties with their own terms. Re-fetch per-bundle when §6.5 needs
  them rather than inheriting a GPL collection wholesale.

**When in doubt, do not add the file.** Add a note to `PROVENANCE.md` saying
where it has to come from instead, and the loader can raise a clear error.

## Why `manifests/` matters

`BuildManifest.plist` is the file a restore is validated against. Each one here
gives, for one (device, iOS version) pair:

- `ApChipID` / `ApBoardID` / `ApSecurityDomain` — the identity a restore request
  is signed for.
- `Info.DeviceClass` (e.g. `n51ap`) and `Info.RestoreBehavior`
  (`Update` for 32-bit, `Erase` for A7) — the model↔ProductType mapping and the
  restore-kind gate, as data.
- `Manifest.<component>.Info.Path` — the **exact path inside the IPSW** for
  `iBoot`, `iBEC`, `iBSS`, `KernelCache`, `DeviceTree`, `RestoreRamDisk`
  (a build-named `.dmg`, not `restore.dmg`) and the rest.
- `Manifest.<component>.Digest` — SHA1, so a partial download can be verified
  before anything is flashed.

That last pair is why this is the first thing copied. Guessing member paths is
exactly the class of silent failure recorded in `AGENTS.md` under "Asset paths
and WSL argv".

## Coverage and its limits

28 manifests cover the signed-OTA-downgrade matrix only: iOS 6.1.3 (3 devices),
8.4.1 (19) and 10.3.3 (6). That is deliberately the same narrow set — these are
the versions Apple still signs, so they are the only ones a 32-bit/A7 device can
restore to without blobs. There is no manifest for iOS 16+ and there will not
be; those come from the device's own `BuildManifest` or from
`api.ipsw.me/v4/device/<product>`.
