"""
Offline tests for assets/legacy and the loader that reads it.

No device, no network, no WSL. These assert three things:

  * the vendored tree is exactly what PROVENANCE.md says it is (so a resource
    that gets added, dropped or silently replaced fails here rather than
    during a restore);
  * the BuildManifest loader returns Apple's own values, not plausible-looking
    ones — the digests and IPSW-internal paths are checked against literals, so
    a mis-parse cannot pass;
  * every failure path names what was asked for and what exists, because a
    bare "not found" here costs a device round-trip to diagnose.
"""

from __future__ import annotations

import os
import plistlib

import pytest

from pymobile3_gui.core.backend import legacy_assets as la
from pymobile3_gui.core.backend.paths import app_dir

LEGACY_DIR = os.path.join(app_dir(), "assets", "legacy")

# Counts and tree digests as published in assets/legacy/PROVENANCE.md.
EXPECTED = {
    "manifests": (28, 1_116_579, "3008ac7c905ddee4"),
    "patches": (49, 12_934, "7d1371342102a8ad"),
    os.path.join("patches", "ios8"): (32, 7_360, "0a721e06b832c144"),
}


# -----------------------------------------------------------------------------
# Inventory
# -----------------------------------------------------------------------------

def _tree_digest(directory: str) -> tuple[int, int, str]:
    import hashlib

    agg = hashlib.sha256()
    count = 0
    total = 0
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as fh:
            data = fh.read()
        agg.update(data)
        total += len(data)
        count += 1
    return count, total, agg.hexdigest()[:16]


@pytest.mark.parametrize("rel", sorted(EXPECTED))
def test_tree_matches_provenance(rel):
    count, total, digest = _tree_digest(os.path.join(LEGACY_DIR, rel))
    want_count, want_total, want_digest = EXPECTED[rel]
    assert count == want_count, f"{rel}: file count drifted from PROVENANCE.md"
    assert total == want_total, f"{rel}: byte total drifted from PROVENANCE.md"
    assert digest == want_digest, f"{rel}: contents changed without a PROVENANCE.md update"


def test_docs_ship_with_the_tree():
    for name in ("README.md", "PROVENANCE.md"):
        assert os.path.isfile(os.path.join(LEGACY_DIR, name)), f"{name} missing"
    assert os.path.isfile(os.path.join(LEGACY_DIR, "licenses", "NOTICE.txt"))


# -----------------------------------------------------------------------------
# Manifest resolution
# -----------------------------------------------------------------------------

def test_available_manifests_is_the_signed_ota_matrix():
    pairs = la.available_manifests()
    assert len(pairs) == 28
    assert set(pairs) == set(la.available_manifests()), "ordering must be stable"
    versions = {v for _, v in pairs}
    assert versions == {"6.1.3", "8.4.1", "10.3.3"}


def test_manifest_name_prefers_the_longest_version_match():
    # '8.4' is not a real version we ship, but the prefix rule is what stops
    # '8.4.1' being shadowed by a future '8.4.1.1' entry.
    assert la.manifest_name("iPhone4,1", "8.4.1") == "BuildManifest_iPhone4,1_8.4.1.plist"
    assert la.manifest_name("iPhone4,1", "8.4") == "BuildManifest_iPhone4,1_8.4.1.plist"


def test_manifest_name_keeps_the_comma_in_producttype():
    assert la.manifest_name("iPhone6,1", "10.3.3").endswith("iPhone6,1_10.3.3.plist")


def test_manifest_name_rejects_an_uncached_version_clearly():
    with pytest.raises(la.LegacyAssetError) as excinfo:
        la.manifest_name("iPhone6,1", "16.7.16")
    message = str(excinfo.value)
    assert "iPhone6,1" in message
    assert "16.7.16" in message
    # Must point at the supported route, not just say no.
    assert "api.ipsw.me" in message


def test_manifest_field_values_are_apples_own():
    # Literals, not computed values — a mis-parse must not pass.
    assert la.manifest_field("iPhone6,1", "10.3.3", "ApChipID") == "0x8960"
    assert la.manifest_field("iPhone6,1", "10.3.3", "ApBoardID") == "0x00"
    assert la.manifest_field("iPad2,3", "6.1.3", "ApChipID") == "0x8940"
    assert la.manifest_field("iPad2,3", "6.1.3", "ApBoardID") == "0x02"
    assert la.manifest_field("iPhone5,2", "8.4.1", "ApChipID") == "0x8950"


def test_restore_behavior_flips_at_the_a7_boundary():
    # Every 32-bit manifest says Update, every A7 manifest says Erase. This is
    # Apple's own statement and it is data-destructive, so it is asserted per
    # version rather than sampled.
    for product, version in la.available_manifests():
        behaviour = la.manifest_restore_behavior(product, version)
        assert behaviour in ("Update", "Erase")
        if version == "10.3.3":
            assert behaviour == "Erase", f"{product} {version} is A7, expected Erase"
        else:
            assert behaviour == "Update", f"{product} {version} is 32-bit, expected Update"


def test_model_tag_strips_only_the_ap_suffix():
    assert la.manifest_device_class("iPhone6,1", "10.3.3") == "n51ap"
    assert la.manifest_model_tag("iPhone6,1", "10.3.3") == "n51"
    assert la.manifest_device_class("iPad4,1", "10.3.3") == "j71ap"
    assert la.manifest_model_tag("iPad4,1", "10.3.3") == "j71"
    # 'aap' must survive intact — a naive rstrip('ap') would leave 'j71'.
    assert la.manifest_model_tag("iPad2,4", "8.4.1") == "k93a"


def test_identity_count_is_enforced():
    manifest = la.load_manifest("iPhone6,1", "10.3.3")
    assert len(manifest["BuildIdentities"]) == 1
    with pytest.raises(la.LegacyAssetError, match="exactly 1 BuildIdentity"):
        la.manifest_identity({"BuildIdentities": []})
    with pytest.raises(la.LegacyAssetError, match="exactly 1 BuildIdentity"):
        la.manifest_identity({"BuildIdentities": [{}, {}]})


# -----------------------------------------------------------------------------
# Component paths and digests
# -----------------------------------------------------------------------------

def test_component_paths_match_the_ipsw_layout():
    assert la.component_path("iPhone6,1", "10.3.3", "iBSS") == \
        "Firmware/dfu/iBSS.iphone6.RELEASE.im4p"
    assert la.component_path("iPhone6,1", "10.3.3", "iBEC") == \
        "Firmware/dfu/iBEC.iphone6.RELEASE.im4p"
    assert la.component_path("iPhone6,1", "10.3.3", "iBoot") == \
        "Firmware/all_flash/iBoot.iphone6.RELEASE.im4p"
    assert la.component_path("iPhone6,1", "10.3.3", "DeviceTree") == \
        "Firmware/all_flash/DeviceTree.n51ap.im4p"
    assert la.component_path("iPhone6,1", "10.3.3", "KernelCache") == \
        "kernelcache.release.iphone6"


def test_restore_ramdisk_is_a_build_named_dmg_not_restore_dmg():
    # The whole reason component_path() exists: hand-assembling this name is
    # how a partial download requests a member that is not in the IPSW and
    # produces an empty file instead of an error.
    path = la.component_path("iPhone6,1", "10.3.3", "RestoreRamDisk")
    assert path.endswith(".dmg")
    assert path != "restore.dmg"
    assert path == "058-75383-068.dmg"


def test_component_digest_is_a_sha1_of_the_real_file(tmp_path):
    import hashlib

    digest = la.component_digest("iPhone6,1", "10.3.3", "iBSS")
    assert len(digest) == 20

    payload = b"not the real iBSS, but a known body"
    target = tmp_path / "iBSS.im4p"
    target.write_bytes(payload)

    assert la.verify_component(str(target), "iPhone6,1", "10.3.3", "iBSS") is False

    # Rewrite the manifest's digest so it matches, proving verify_component
    # compares content rather than returning a constant.
    manifest = la.load_manifest("iPhone6,1", "10.3.3")
    manifest["BuildIdentities"][0]["Manifest"]["iBSS"]["Digest"] = hashlib.sha1(payload).digest()
    original_load_manifest = la.load_manifest
    la.load_manifest = lambda *a, **k: manifest  # type: ignore[assignment]
    try:
        assert la.verify_component(str(target), "iPhone6,1", "10.3.3", "iBSS") is True
    finally:
        la.load_manifest = original_load_manifest


def test_missing_component_reports_what_is_available():
    with pytest.raises(la.LegacyAssetError) as excinfo:
        la.component_path("iPhone6,1", "10.3.3", "WTFirmware")
    assert "WTFirmware" in str(excinfo.value)
    assert "iBSS" in str(excinfo.value)


def test_fetch_plan_covers_a_bootchain():
    plan = la.fetch_plan(
        "iPhone6,1", "10.3.3",
        ("iBSS", "iBEC", "KernelCache", "DeviceTree", "RestoreRamDisk"),
    )
    assert plan == {
        "iBSS": "Firmware/dfu/iBSS.iphone6.RELEASE.im4p",
        "iBEC": "Firmware/dfu/iBEC.iphone6.RELEASE.im4p",
        "KernelCache": "kernelcache.release.iphone6",
        "DeviceTree": "Firmware/all_flash/DeviceTree.n51ap.im4p",
        "RestoreRamDisk": "058-75383-068.dmg",
    }


def test_fetch_plan_reports_missing_components_instead_of_skipping():
    with pytest.raises(la.LegacyAssetError) as excinfo:
        la.fetch_plan("iPhone6,1", "10.3.3", ("iBSS", "NotAThing"))
    assert "NotAThing" in str(excinfo.value)


# -----------------------------------------------------------------------------
# Patch resolution
# -----------------------------------------------------------------------------

def test_patch_path_for_each_family():
    assert os.path.isfile(la.patch_path("iBSS", "n71"))
    assert os.path.isfile(la.patch_path("iBEC", "n71"))
    assert os.path.isfile(la.patch_path("kernelcache", "n71"))
    assert la.patch_path("iBSS", "n71").endswith(
        os.path.join("patches", "iBSS.n71.RELEASE.im4p.patch"))


def test_patch_and_ios8_patch_are_separate_trees():
    assert la.patches_dir() != la.patches_dir(ios8=True)
    assert os.path.basename(la.patches_dir(ios8=True)) == "ios8"


def test_ios8_models_differ_from_the_main_set():
    main = set(la.patch_models("iBSS"))
    ios8 = set(la.patch_models("iBSS", ios8=True))
    assert main and ios8
    assert ios8 != main
    # A8 iPads (j71) only have an iOS 8 patch; A9 (n71) only a main-tree one.
    assert "j71" in ios8 and "j71" not in main
    assert "n71" in main and "n71" not in ios8
    # A7 (n56) straddles both trees — an iOS 8 and an iOS 10/11 ramdisk exist.
    assert "n56" in main and "n56" in ios8


def test_kernelcache_patches_have_no_ibss_counterpart_for_marketing_names():
    kc = set(la.patch_models("kernelcache"))
    ibss = set(la.patch_models("iBSS"))
    # Marketing-name entries carry over unreviewed; PROVENANCE.md flags them
    # precisely because there is no iBSS/iBEC patch for those boards.
    assert {"iphone7", "iphone8b", "iphone9"} <= kc
    assert {"iphone7", "iphone8b", "iphone9"}.isdisjoint(ibss)
    # Every hardware-model kernelcache patch has a bootchain counterpart.
    real = kc - {"iphone7", "iphone8b", "iphone9"}
    assert real and real <= ibss


def test_missing_patch_names_the_request_and_the_alternatives():
    with pytest.raises(la.LegacyAssetError) as excinfo:
        la.patch_path("iBSS", "nope")
    message = str(excinfo.value)
    assert "nope" in message
    assert "Available models" in message
    assert "n71" in message


def test_unknown_component_is_rejected_up_front():
    with pytest.raises(la.LegacyAssetError, match="Unknown patch component"):
        la.patch_path("logo", "n71")


# -----------------------------------------------------------------------------
# Path resolution
# -----------------------------------------------------------------------------

def test_paths_resolve_under_the_bundle_root():
    # The asset-path bug in AGENTS.md walked one dirname too deep and silently
    # pointed resource_path() inside core/. Anchor on app_dir(), not __file__.
    assert la.legacy_root() == os.path.join(app_dir(), "assets", "legacy")
    assert la.manifests_dir().startswith(app_dir())
    assert os.path.isdir(la.manifests_dir())


def test_loader_works_without_any_device_or_network(monkeypatch):
    # Guard against a future import of requests/subprocess creeping in here.
    import socket

    def no_network(*args, **kwargs):
        raise AssertionError("legacy_assets must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    assert la.manifest_restore_behavior("iPhone6,1", "10.3.3") == "Erase"


def test_manifest_files_are_valid_plists():
    for product, version in la.available_manifests():
        path = la.manifest_path(product, version)
        with open(path, "rb") as fh:
            data = plistlib.load(fh)
        # Apple's own top-level keys. ProductVersion/BuildVersion must agree
        # with the filename's version segment — a mislabelled manifest is the
        # whole class of bug this table exists to prevent.
        assert data["BuildIdentities"], f"{path} has no BuildIdentities"
        assert data["ProductVersion"] == version, f"{path} ProductVersion mismatch"
        assert data["ProductBuildVersion"], f"{path} has no ProductBuildVersion"
        assert data["SupportedProductTypes"], f"{path} has no SupportedProductTypes"
