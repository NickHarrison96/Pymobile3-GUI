"""
Pymobile3-GUI — Legacy iOS Kit static resource access

Read-only access to `assets/legacy/` — the data files vendored for the
Legacy iOS Kit feature-parity work (`docs/TODO.md` §6). Nothing here executes
anything; it resolves paths and parses Apple's own metadata.

Three responsibilities:

  1. Locate the tree. Frozen, `assets/legacy` is unpacked under `_MEIPASS`;
     from source it sits beside `core/`. `resource_path()` already handles
     both, and `paths.app_dir()` had a bug that pointed one directory too
     deep (AGENTS.md, "Asset paths and WSL argv") — hence no `__file__` walk
     of our own here.

  2. Answer device questions from `manifests/`. `BuildManifest.plist` is the
     file a restore is validated against: it names the exact IPSW-internal
     path of every bootchain component and carries the SHA1 of each. That
     removes the guesswork from partial downloads, which is the failure mode
     recorded twice in AGENTS.md.

  3. Resolve bsdiff patches from `patches/`. These are applied by the WSL
     `bspatch` binary, so this module only hands over a path.

Scope note: this is deliberately *not* the capability database from §6.1. That
is `device_db.py` — processor generation, signed-target matrix, powdersn0w /
DRA-v6 eligibility — and it is data we author, sourced from ipsw.me and the
device rather than from Apple's manifests. What lives here is only what
`assets/legacy/` actually contains.

Provenance rules for everything under `assets/legacy/` are in that directory's
README.md and PROVENANCE.md. Read them before adding a file.
"""

from __future__ import annotations

import os
import plistlib
import re
from typing import Iterable, Optional

from pymobile3_gui.core.backend.paths import resource_path

# Manifest filenames are BuildManifest_<ProductType>_<version>.plist, e.g.
# BuildManifest_iPhone6,1_10.3.3.plist.
#
# The ProductType group excludes "_" and must not be greedy. A greedy ".+"
# backtracks to product="iPhone6,1_10" / version="3.3" on that filename, which
# parses cleanly and then resolves to nothing — so the separator is pinned
# rather than left to the engine.
_MANIFEST_NAME_RE = re.compile(
    r"^BuildManifest_(?P<product>[^_]+)_(?P<version>\d+(?:\.\d+)*)\.plist$"
)

# Patch filenames use the Apple hardware-model tag, not ProductType:
#   iBSS.n71.RELEASE.im4p.patch       -> iBSS for the A9 iPhone8,x
#   kernelcache.release.n71.bpatch    -> kernelcache for the same board
#
# Note the two suffixes end in ".patch"/".bpatch" — an im4p diff is not the
# im4p itself — and "kernelcache" drops the ".release" into the middle segment
# rather than into the component name, so the component group stays uniform.
_PATCH_NAME_RE = re.compile(
    r"^(?P<component>iBSS|iBEC|kernelcache)"
    r"\.(?:release\.)?(?P<model>[a-z0-9]+)"
    r"\.(?:RELEASE\.im4p\.patch|bpatch)$"
)


class LegacyAssetError(Exception):
    """A required legacy resource is missing or unusable."""


# -----------------------------------------------------------------------------
# Locations
# -----------------------------------------------------------------------------

def legacy_root() -> str:
    """Root of the vendored legacy data tree."""
    return resource_path("assets", "legacy")


def manifests_dir() -> str:
    return os.path.join(legacy_root(), "manifests")


def patches_dir(ios8: bool = False) -> str:
    """bsdiff patches. iOS 8 lives in its own subdirectory."""
    base = os.path.join(legacy_root(), "patches")
    return os.path.join(base, "ios8") if ios8 else base


def patch_path(component: str, model: str, *, ios8: bool = False) -> str:
    """
    Absolute path to a bsdiff patch for a bootchain component.

    `component` is "iBSS", "iBEC" or "kernelcache". `model` is the Apple
    hardware-model tag without the "ap" suffix — "n71", "ipad5b", "j87m" —
    which is what the filenames use, not ProductType.

    Raises LegacyAssetError naming both the requested and the available tags:
    the model list is the thing a caller gets wrong, so an error that just
    said "not found" would cost more time than it saves.
    """
    if component == "kernelcache":
        filename = f"kernelcache.release.{model}.bpatch"
    elif component in ("iBSS", "iBEC"):
        filename = f"{component}.{model}.RELEASE.im4p.patch"
    else:
        raise LegacyAssetError(
            f"Unknown patch component {component!r} — expected iBSS, iBEC or kernelcache."
        )

    path = os.path.join(patches_dir(ios8), filename)
    if not os.path.isfile(path):
        raise LegacyAssetError(
            f"No {component} patch for model {model!r}"
            f"{' (iOS 8)' if ios8 else ''}: expected {filename}.\n"
            f"Available models: {', '.join(patch_models(component, ios8=ios8)) or 'none'}"
        )
    return path


def patch_models(component: str, *, ios8: bool = False) -> list[str]:
    """Hardware-model tags that have a patch for `component`, sorted."""
    directory = patches_dir(ios8)
    if not os.path.isdir(directory):
        return []
    prefix = "kernelcache.release." if component == "kernelcache" else f"{component}."
    out = []
    for name in os.listdir(directory):
        if not name.startswith(prefix):
            continue
        match = _PATCH_NAME_RE.match(name)
        if match and match.group("component") == component:
            out.append(match.group("model"))
    return sorted(set(out))


# -----------------------------------------------------------------------------
# BuildManifest
# -----------------------------------------------------------------------------

def manifest_name(product: str, version: str) -> str:
    """
    Filename for a (ProductType, iOS version) pair.

    `version` may be a full "8.4.1" or just a major/minor "8.4"; the longest
    matching manifest wins, so a caller that only knows the minor version
    still resolves. ProductType keeps its comma — do not normalise it away.
    """
    directory = manifests_dir()
    if not os.path.isdir(directory):
        raise LegacyAssetError(f"Vendored manifests directory is missing: {directory}")

    prefix = f"BuildManifest_{product}_"
    candidates = []
    for name in os.listdir(directory):
        if not name.startswith(prefix) or not name.endswith(".plist"):
            continue
        have = name[len(prefix):-len(".plist")]
        if have == version or have.startswith(version + "."):
            candidates.append(name)

    if not candidates:
        raise LegacyAssetError(
            f"No vendored BuildManifest for {product} iOS {version}.\n"
            f"Only the signed-OTA matrix is cached (6.1.3 / 8.4.1 / 10.3.3); "
            f"for any other version read the manifest out of the IPSW or query "
            f"api.ipsw.me."
        )
    return max(candidates, key=len)


def manifest_path(product: str, version: str) -> str:
    """Absolute path to the BuildManifest.plist for a device and version."""
    return os.path.join(manifests_dir(), manifest_name(product, version))


def available_manifests() -> list[tuple[str, str]]:
    """Every (ProductType, version) pair shipped in assets/legacy."""
    directory = manifests_dir()
    if not os.path.isdir(directory):
        return []
    out = []
    for name in sorted(os.listdir(directory)):
        match = _MANIFEST_NAME_RE.match(name)
        if match:
            out.append((match.group("product"), match.group("version")))
    return out


def load_manifest(product: str, version: str) -> dict:
    """
    Parse the BuildManifest.plist for a device and version.

    Returns the raw dict so callers can reach anything Apple put in it; the
    typed accessors below cover the fields the restore flow actually needs.
    """
    path = manifest_path(product, version)
    try:
        with open(path, "rb") as fh:
            return plistlib.load(fh)
    except OSError as exc:
        raise LegacyAssetError(f"Cannot read {path}: {exc}") from exc


def manifest_identity(manifest: dict) -> dict:
    """
    The single BuildIdentity from a parsed manifest.

    Every manifest in assets/legacy has exactly one identity — the per-device
    signed IPSWs these came from are single-target. A manifest with zero or
    several is from somewhere else (an OTA package, say) and must not be
    resolved by guessing, so raise rather than return the first entry.
    """
    identities = manifest.get("BuildIdentities") or []
    if len(identities) != 1:
        raise LegacyAssetError(
            f"Expected exactly 1 BuildIdentity, found {len(identities)}. "
            f"This manifest is not a per-device signed IPSW manifest."
        )
    return identities[0]


def manifest_field(product: str, version: str, field: str) -> Optional[str]:
    """One top-level BuildIdentity field, e.g. 'ApChipID' or 'ApBoardID'."""
    value = manifest_identity(load_manifest(product, version)).get(field)
    return None if value is None else str(value)


def manifest_device_class(product: str, version: str) -> str:
    """
    Hardware model with the "ap" suffix kept, e.g. 'n51ap'.

    This is the join key to assets/legacy/patches/, whose filenames use the
    same tag with the suffix stripped. Going via ProductType instead is the
    mistake to avoid: iPhone8,1 and iPhone8,2 share ProductType-era naming
    pitfalls, and iPad4,x all report as iPad4,1 on iOS 7.
    """
    info = manifest_identity(load_manifest(product, version)).get("Info") or {}
    device_class = info.get("DeviceClass")
    if not device_class:
        raise LegacyAssetError(f"No Info.DeviceClass in manifest for {product} {version}")
    return str(device_class)


def manifest_model_tag(product: str, version: str) -> str:
    """Hardware model without the 'ap' suffix, matching the patch filenames."""
    return re.sub(r"ap$", "", manifest_device_class(product, version))


def manifest_restore_behavior(product: str, version: str) -> str:
    """
    'Update' or 'Erase' — Apple's own statement of how this device restores.

    Worth surfacing in the UI rather than inferring: the 10.3.3 manifests say
    'Erase' for every A7 board while all the 32-bit ones say 'Update', and
    'Erase' is data-destructive.
    """
    info = manifest_identity(load_manifest(product, version)).get("Info") or {}
    behavior = info.get("RestoreBehavior")
    if not behavior:
        raise LegacyAssetError(f"No Info.RestoreBehavior in manifest for {product} {version}")
    return str(behavior)


def component_path(product: str, version: str, component: str) -> str:
    """
    The IPSW-internal path of a component, e.g.

        component_path("iPhone6,1", "10.3.3", "iBSS")
        -> 'Firmware/dfu/iBSS.iphone6.RELEASE.im4p'

    and for the restore ramdisk, which is a build-named dmg rather than
    'restore.dmg':

        component_path("iPhone6,1", "10.3.3", "RestoreRamDisk")
        -> '058-75383-068.dmg'

    Both facts are why this exists. Hand-assembling 'Firmware/dfu/iBSS.<model>'
    is how a partial download silently requests a member that is not there and
    produces an empty file rather than an error.
    """
    manifest = load_manifest(product, version)
    components = manifest_identity(manifest).get("Manifest") or {}
    entry = components.get(component)
    if not entry:
        available = ", ".join(sorted(components)) or "none"
        raise LegacyAssetError(
            f"No {component!r} in the {product} {version} manifest. "
            f"Available: {available}"
        )
    info = entry.get("Info") or {}
    path = info.get("Path")
    if not path:
        raise LegacyAssetError(f"{component} in the {product} {version} manifest has no Info.Path")
    return str(path)


def component_digest(product: str, version: str, component: str) -> bytes:
    """
    SHA1 Apple recorded for a component. Verify a partial download against
    this before anything is flashed.
    """
    manifest = load_manifest(product, version)
    components = manifest_identity(manifest).get("Manifest") or {}
    entry = components.get(component)
    if not entry:
        raise LegacyAssetError(f"No {component!r} in the {product} {version} manifest.")
    digest = entry.get("Digest")
    if not digest:
        raise LegacyAssetError(f"{component} in the {product} {version} manifest has no Digest.")
    return bytes(digest)


def verify_component(path: str, product: str, version: str, component: str) -> bool:
    """True when a downloaded file's SHA1 matches what Apple recorded."""
    import hashlib

    digest = component_digest(product, version, component)
    hasher = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.digest() == digest


def fetch_plan(product: str, version: str, components: Iterable[str]) -> dict[str, str]:
    """
    Map component names to IPSW-internal paths for a partial download.

    The shape `pzb` wants: what to fetch, and the exact member name to ask
    for. Components not present in this manifest are reported rather than
    skipped — a restore that quietly omits iBSS fails much later and much
    more confusingly.
    """
    manifest = load_manifest(product, version)
    available = manifest_identity(manifest).get("Manifest") or {}
    plan: dict[str, str] = {}
    missing = []
    for component in components:
        entry = available.get(component)
        if entry and (entry.get("Info") or {}).get("Path"):
            plan[component] = str(entry["Info"]["Path"])
        else:
            missing.append(component)
    if missing:
        raise LegacyAssetError(
            f"{product} {version} manifest has no path for: {', '.join(missing)}. "
            f"Available: {', '.join(sorted(available))}"
        )
    return plan
