"""
Regenerate the inventory tables in `pymobile3_gui/assets/legacy/PROVENANCE.md`.

Run from the project root:

    python scripts/legacy_inventory.py

The manifest table and the tree hashes in PROVENANCE.md are generated from
what is actually on disk, so a resource that gets added, removed or silently
replaced shows up as a diff in that file rather than as a mismatch discovered
during a restore. `tests/test_legacy_assets.py` asserts the same numbers.
"""

from __future__ import annotations

import glob
import hashlib
import os
import plistlib
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY = os.path.join(REPO, "pymobile3_gui", "assets", "legacy")


def files(rel: str) -> list[str]:
    return sorted(
        p for p in glob.glob(os.path.join(LEGACY, rel, "*")) if os.path.isfile(p)
    )


def tree_digest(paths: list[str]) -> str:
    agg = hashlib.sha256()
    for path in paths:
        with open(path, "rb") as fh:
            agg.update(fh.read())
    return agg.hexdigest()[:16]


def manifest_rows() -> list[str]:
    rows = []
    for path in files("manifests"):
        with open(path, "rb") as fh:
            identity = plistlib.load(fh)["BuildIdentities"][0]
        info = identity["Info"]
        name = os.path.basename(path)
        product = name[len("BuildManifest_"):-len(".plist")]
        product, _, version = product.rpartition("_")
        rows.append(
            f"| `{product}` | {info.get('BuildNumber')} | "
            f"`{info.get('DeviceClass')}` | "
            f"{identity.get('ApChipID')} / {identity.get('ApBoardID')} | "
            f"{info.get('RestoreBehavior')} | {len(identity['Manifest'])} | "
            f"{os.path.getsize(path):,} |"
        )
    return rows


def patch_rows(rel: str) -> list[str]:
    rows = []
    for path in files(rel):
        with open(path, "rb") as fh:
            head = fh.read(9)
        variant = "BSDIFF407" if head.startswith(b"BSDIFF407") else "BSDIFF40"
        rows.append(f"| `{os.path.basename(path)}` | {variant} | {os.path.getsize(path):,} |")
    return rows


def main() -> int:
    if not os.path.isdir(LEGACY):
        print(f"No such directory: {LEGACY}", file=sys.stderr)
        return 1

    print("## manifests\n")
    print("| ProductType | Build | DeviceClass | ApChipID / ApBoardID | "
          "RestoreBehavior | Components | Bytes |")
    print("|---|---|---|---|---|---|---|")
    for row in manifest_rows():
        print(row)

    for rel, title in (("patches", "patches"), (os.path.join("patches", "ios8"), "patches/ios8")):
        print(f"\n## {title}\n")
        print("| File | Format | Bytes |")
        print("|---|---|---|")
        for row in patch_rows(rel):
            print(row)

    print("\n## totals\n")
    print("```")
    for rel in ("manifests", "patches", os.path.join("patches", "ios8")):
        fs = files(rel)
        total = sum(os.path.getsize(f) for f in fs)
        print(f"{rel.replace(os.sep, '/'):<14} {len(fs):>3} files {total:>10,} bytes"
              f"   tree sha256 {tree_digest(fs)}...")
    print("```")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
