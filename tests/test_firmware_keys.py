"""Tests for firmware key lookup and bootchain decryption.

Network access is stubbed: these assert on parsing and on how the build reacts
to missing or malformed keys, since the failure mode that matters is "the wiki
has no keys for this build" and it must surface as a clear error rather than a
traceback or a silently undecrypted image.
"""

import pytest

from pymobile3_gui.core.backend import firmware_keys as fk
from pymobile3_gui.core.backend import ramdisk_manager as ram
from pymobile3_gui.core.backend.firmware_keys import FirmwareKeyError

SAMPLE_KEY_PAGE = """{{keys
 | Version                       = 16.0.3
 | Build                         = 20A392
 | Device                        = iPhone10,4
 | Codename                      = Sydney
 | iBSS                          = iBSS.d20.RELEASE.im4p
 | iBSSIV                        = 0b62971cc8919dcd6d0a6eb4dfee7214
 | iBSSKey                       = 694237258aee5ef5b061a13c47ac16afd74ccc6af4fa17ec13797bc1932da469
 | iBEC                          = iBEC.d20.RELEASE.im4p
 | iBECIV                        = 5307baa5fb11c3e8ff9cf4a751130336
 | iBECKey                       = aee730477da08582f9e06681a6f4c0843c400149f018ac4aee0c8ee1fa8c7048
}}
"""

FIRMWARE_PAGE = """
| 20A362
| [[Keys:Sydney 20A362 (iPhone10,1)|iPhone10,1]]<br/>[[Keys:Sydney 20A362 (iPhone10,4)|iPhone10,4]]
| 20A392
| [[Keys:Sydney 20A392 (iPhone10,1)|iPhone10,1]]<br/>[[Keys:Sydney 20A392 (iPhone10,4)|iPhone10,4]]
"""


def test_parse_component_keys_pairs_iv_and_key():
    keys = fk.parse_component_keys(SAMPLE_KEY_PAGE)
    assert set(keys) == {"iBSS.d20.RELEASE.im4p", "iBEC.d20.RELEASE.im4p"}
    ibss = keys["iBSS.d20.RELEASE.im4p"]
    assert ibss.component == "iBSS"
    assert len(ibss.iv) == 16
    assert len(ibss.key) == 32


def test_parse_component_keys_rejects_wrong_length_material():
    # A short IV or key must be dropped, not handed to AES as-is.
    page = SAMPLE_KEY_PAGE.replace(
        "0b62971cc8919dcd6d0a6eb4dfee7214", "0b6297")
    assert "iBSS.d20.RELEASE.im4p" not in fk.parse_component_keys(page)


def test_parse_component_keys_ignores_non_hex():
    page = SAMPLE_KEY_PAGE.replace("5307baa5fb11c3e8ff9cf4a751130336", "nothex")
    keys = fk.parse_component_keys(page)
    assert "iBEC.d20.RELEASE.im4p" not in keys
    assert "iBSS.d20.RELEASE.im4p" in keys


def test_resolve_key_page_matches_build_and_device(monkeypatch):
    monkeypatch.setattr(fk, "_page_wikitext", lambda title: FIRMWARE_PAGE)
    assert fk.resolve_key_page("20A392", "iPhone10,4", 16) == \
        "Keys:Sydney 20A392 (iPhone10,4)"
    # A different build on the same page must not be substituted.
    assert fk.resolve_key_page("20A362", "iPhone10,4", 16) == \
        "Keys:Sydney 20A362 (iPhone10,4)"


def test_resolve_key_page_raises_when_absent(monkeypatch):
    monkeypatch.setattr(fk, "_page_wikitext", lambda title: FIRMWARE_PAGE)
    with pytest.raises(FirmwareKeyError, match="20A999"):
        fk.resolve_key_page("20A999", "iPhone10,4", 16)


def test_resolve_key_page_requires_the_right_device(monkeypatch):
    monkeypatch.setattr(fk, "_page_wikitext", lambda title: FIRMWARE_PAGE)
    with pytest.raises(FirmwareKeyError):
        fk.resolve_key_page("20A392", "iPhone12,1", 16)


def test_lookup_key_matches_by_basename():
    keys = fk.parse_component_keys(SAMPLE_KEY_PAGE)
    assert fk.lookup_key(keys, "iBSS.d20.RELEASE.im4p").component == "iBSS"
    # Callers hold repo-relative paths, so a full path must still match.
    assert fk.lookup_key(keys, "work/iBEC.d20.RELEASE.im4p").component == "iBEC"
    assert fk.lookup_key(keys, "kernelcache.release.iphone10") is None


def test_fetch_component_keys_requires_usable_pairs(monkeypatch):
    def fake_page(title):
        # The firmware table resolves; the key page itself is useless.
        return FIRMWARE_PAGE if title.startswith("Firmware/") else "nothing"

    monkeypatch.setattr(fk, "_page_wikitext", fake_page)
    with pytest.raises(FirmwareKeyError, match="no usable"):
        fk.fetch_component_keys("20A392", "iPhone10,4", 16)


def test_ivkey_is_iv_then_key():
    keys = fk.parse_component_keys(SAMPLE_KEY_PAGE)
    ibss = keys["iBSS.d20.RELEASE.im4p"]
    assert fk.ivkey(ibss) == (
        "0b62971cc8919dcd6d0a6eb4dfee7214"
        "694237258aee5ef5b061a13c47ac16afd74ccc6af4fa17ec13797bc1932da469")
    assert len(fk.ivkey(ibss)) == 96  # 16-byte IV + 32-byte key, hex


def test_decrypt_bootchain_image_uses_img4_with_key(monkeypatch):
    keys = fk.parse_component_keys(SAMPLE_KEY_PAGE)
    calls = []

    def fake_wsl(tool, args, **kwargs):
        calls.append((tool, list(args), kwargs))
        return 0

    monkeypatch.setattr(ram, "wsl_tool", fake_wsl)
    logs = []
    ram._decrypt_bootchain_image(
        "work/iBSS.d20.RELEASE.im4p", "work/iBSS.dec", keys,
        "C:/root", logs.append, lambda: False)

    assert len(calls) == 1
    tool, args, kwargs = calls[0]
    assert tool == "img4"
    assert args[:2] == ["-i", "work/iBSS.d20.RELEASE.im4p"]
    assert args[2:4] == ["-o", "work/iBSS.dec"]
    # The key must travel as img4's -k ivkey, not some other mechanism.
    assert args[4] == "-k"
    assert args[5] == fk.ivkey(keys["iBSS.d20.RELEASE.im4p"])
    assert kwargs["context"] == "img4 -k (iBSS.d20.RELEASE.im4p)"


def test_decrypt_bootchain_image_reports_missing_key(tmp_path, monkeypatch):
    keys = fk.parse_component_keys(SAMPLE_KEY_PAGE)
    monkeypatch.setattr(
        ram, "wsl_tool",
        lambda *a, **k: pytest.fail("must not run img4 without a key"))
    logs = []
    # iBoot has no key in the fixture, so lookup must fail before any I/O.
    with pytest.raises(ram.RamdiskError, match="publishes no keys"):
        ram._decrypt_bootchain_image(
            "work/iBoot.d20.RELEASE.im4p", "work/iBoot.dec", keys,
            str(tmp_path), logs.append, lambda: False)
    assert not logs


def test_build_number_from_ipsw_url():
    url = ("https://updates.cdn-apple.com/2022FallFCS/fullrestores/012-73379/"
           "0418E94A-C9E6-48E5-9FDF-E61EC6E79312/"
           "iPhone_4.7_P3_16.0.3_20A392_Restore.ipsw")
    assert ram.build_number_from_ipsw_url(url) == "20A392"


def test_build_number_from_ipsw_url_rejects_unexpected_name():
    with pytest.raises(ram.RamdiskError, match="build number"):
        ram.build_number_from_ipsw_url("https://example.com/something.ipsw")