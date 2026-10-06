"""Unit tests for the SSH ramdisk manager (SSHRD_Script port).

Everything here runs offline: device USB access, WSL tool execution and the
ipsw.me API are either pure logic or stubbed. The boot-sequence test replays
sshrd.sh's decision table (go / trustcache / nand-reformat) without hardware.
"""

import os
import plistlib
import sys

import pytest

from pymobile3_gui.core.backend import ramdisk_manager as ram
from pymobile3_gui.core.backend.ramdisk_manager import RamdiskError


# -----------------------------------------------------------------------------
# Path / quoting helpers
# -----------------------------------------------------------------------------

def test_win_to_wsl_basic():
    assert ram.win_to_wsl(r"C:\Users\nick\work") == "/mnt/c/Users/nick/work"


def test_win_to_wsl_forward_slashes_and_other_drive():
    assert ram.win_to_wsl("D:/tools/bin") == "/mnt/d/tools/bin"


def test_win_to_wsl_rejects_relative_path():
    with pytest.raises(RamdiskError):
        ram.win_to_wsl("relative/path")


def test_sh_quote_escapes_single_quotes_and_spaces():
    assert ram.sh_quote("plain") == "'plain'"
    assert ram.sh_quote("has space") == "'has space'"
    assert ram.sh_quote("it's") == "'it'\\''s'"


# -----------------------------------------------------------------------------
# irecovery output parsing
# -----------------------------------------------------------------------------

SAMPLE_IRECOVERY = (
    "CPID: 0x8010\n"
    "CPID: 0x8010\n"  # duplicate lines must not break anything
    "MODE: DFU\n"
    "PRODUCT: iPhone10,3\n"
    "MODEL: d221ap\n"
    "ECID: 0x1122334455667788\n"
)

# Older irecovery builds omit NAME, so the CPID table has to cover for them.
SAMPLE_IRECOVERY_NO_NAME = (
    "CPID: 0x8015\n"
    "MODE: DFU\n"
    "PRODUCT: iPhone10,4\n"
    "MODEL: d201ap\n"
)


def test_parse_device_info_full():
    dev = ram.parse_device_info(SAMPLE_IRECOVERY)
    assert dev is not None
    assert dev["cpid"] == "0x8010"
    assert dev["product"] == "iPhone10,3"
    assert dev["model"] == "d221ap"
    assert dev["mode"] == "DFU"


def test_parse_device_info_reads_name_when_present():
    dev = ram.parse_device_info("CPID: 0x8015\nNAME: iPhone 8 (GSM)\n")
    assert dev["name"] == "iPhone 8 (GSM)"


def test_parse_device_info_name_defaults_to_empty():
    dev = ram.parse_device_info(SAMPLE_IRECOVERY_NO_NAME)
    assert dev["name"] == ""


def test_parse_device_info_rejects_error_output():
    assert ram.parse_device_info(
        "ERROR: Unable to connect to device") is None
    assert ram.parse_device_info("") is None
    assert ram.parse_device_info("MODEL: d221ap\n") is None


def test_detect_device_uses_run_capture(monkeypatch):
    monkeypatch.setattr(
        ram, "run_capture",
        lambda cmd, timeout=15: (0, SAMPLE_IRECOVERY))
    dev = ram.detect_device()
    assert dev and dev["cpid"] == "0x8010"

    monkeypatch.setattr(
        ram, "run_capture", lambda cmd, timeout=15: (-1, "no device"))
    assert ram.detect_device() is None


# -----------------------------------------------------------------------------
# sshrd.sh version / darwin decision tables
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("15.7.1", (15, 7, 1)),
    ("16.0", (16, 0, 0)),
    ("11.2", (11, 2, 0)),
    ("12", (12, 0, 0)),
])
def test_parse_version(raw, expected):
    assert ram.parse_version(raw) == expected


@pytest.mark.parametrize("raw", ["", "fourteen.point.one", "15.beta.1"])
def test_parse_version_rejects_garbage(raw):
    with pytest.raises(RamdiskError):
        ram.parse_version(raw)


@pytest.mark.parametrize("cpid,major,expected", [
    ("0x8010", 15, 21),   # A11 iOS 15 -> darwin 21
    ("0x8960", 11, 17),   # A7  iOS 11 -> darwin 17
    ("0x8012", 15, 30),   # T2 special case: major + 15
    ("0x8010", 26, 25),   # iOS 26 era -> darwin = major - 1
    ("0x8012", 26, 41),   # T2 rule wins over the 26 rule
])
def test_darwin_major_for(cpid, major, expected):
    assert ram.darwin_major_for(cpid, major) == expected


@pytest.mark.parametrize("cpid,dm,minor,patch,expected", [
    ("0x8010", 16, 0, 0, False),    # dm < 17 -> never
    ("0x8960", 17, 3, 0, False),    # 17.3 -> never
    ("0x8012", 17, 4, 1, False),    # T2 17.4.1 -> never (sshrd cutoff)
    ("0x8012", 17, 4, 2, True),     # T2 17.4.2+ -> required
    ("0x8010", 17, 4, 2, False),    # non-T2 17.x -> never
    ("0x8010", 18, 0, 0, True),     # dm > 17 -> required
])
def test_trustcache_needed(cpid, dm, minor, patch, expected):
    assert ram.trustcache_needed(cpid, dm, minor, patch) is expected


@pytest.mark.parametrize("dm,minor,blocked", [
    (21, 0, False),
    (22, 0, False),   # iOS 16.0 builds fine
    (22, 1, True),    # iOS 16.1+ refused by the Linux path
    (23, 0, True),
])
def test_linux_build_blocked(dm, minor, blocked):
    result = ram.linux_build_blocked(dm, minor)
    assert bool(result) is blocked


@pytest.mark.parametrize("dm,minor,patch,expected", [
    (16, 0, 0, True),     # iOS 10 -> graft iconv
    (17, 3, 0, True),     # iOS 11.3 -> graft
    (17, 4, 1, True),     # iOS 11.4 -> graft
    (17, 4, 2, False),    # iOS 11.4.1+ -> no graft
    (18, 0, 0, False),    # iOS 12+ -> no graft
])
def test_needs_12rd(dm, minor, patch, expected):
    assert ram.needs_12rd(dm, minor, patch) is expected


# -----------------------------------------------------------------------------
# BuildManifest helpers (synthetic fixture mirrors the real plist layout)
# -----------------------------------------------------------------------------

def build_manifest(model: str = "d221ap") -> bytes:
    ident = {
        "ApChipID": "0x8015",
        "Info": {
            "DeviceClass": model,
            "Variant": "Customer Erase Install (IPSW)",
        },
        "Manifest": {
            "iBSS": {"Info": {"Path": "Firmware/dfu/iBSS.d22.RELEASE.im4p"}},
            "iBEC": {"Info": {"Path": "Firmware/dfu/iBEC.d22.RELEASE.im4p"}},
            "DeviceTree": {
                "Info": {"Path": "Firmware/all_flash/DeviceTree.d22ap.im4p"}},
            "KernelCache": {"Info": {"Path": "kernelcache.release.d22"}},
            "RestoreRamDisk": {"Info": {"Path": "038-65432-01.dmg"}},
        },
    }
    return plistlib.dumps(
        {"BuildIdentities": [ident], "ProductVersion": "15.7.1"})


def test_extract_manifest_path_parts():
    text = build_manifest().decode("utf-8")
    assert ram.extract_manifest_path(text, "d221ap", r"iBSS[.]") == \
        "Firmware/dfu/iBSS.d22.RELEASE.im4p"
    assert ram.extract_manifest_path(text, "d221ap", r"iBEC[.]") == \
        "Firmware/dfu/iBEC.d22.RELEASE.im4p"
    assert ram.extract_manifest_path(text, "d221ap", r"DeviceTree[.]") == \
        "Firmware/all_flash/DeviceTree.d22ap.im4p"
    assert ram.extract_manifest_path(
        text, "d221ap", r"kernelcache[.]release") == \
        "kernelcache.release.d22"


def test_extract_manifest_path_unknown_model():
    text = build_manifest().decode("utf-8")
    with pytest.raises(RamdiskError):
        ram.extract_manifest_path(text, "n999ap", r"iBSS[.]")
    with pytest.raises(RamdiskError):
        ram.extract_manifest_path(text, "", r"iBSS[.]")


def test_extract_manifest_path_from_real_pzb_manifest(tmp_path):
    """Optional: run against the manifest fetched during E2E testing."""
    import os
    fixture = os.path.join(
        os.environ.get("TEMP", ""), "opencode", "pzbtest",
        "BuildManifest.plist")
    if not os.path.isfile(fixture):
        pytest.skip("live BuildManifest fixture not present")
    with open(fixture, "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8", errors="replace")
    ibss = ram.extract_manifest_path(text, "d221ap", r"iBSS[.]")
    assert ibss.startswith("Firmware/dfu/iBSS.")
    assert ram.restore_ramdisk_name(raw).endswith(".dmg")


def test_strip_fw_prefix():
    assert ram.strip_fw_prefix(
        "Firmware/dfu/iBSS.d22.RELEASE.im4p", "Firmware/dfu/") == \
        "iBSS.d22.RELEASE.im4p"
    assert ram.strip_fw_prefix("kernelcache.release.d22", "Firmware/dfu/") == \
        "kernelcache.release.d22"


def test_restore_ramdisk_name():
    assert ram.restore_ramdisk_name(build_manifest()) == "038-65432-01.dmg"
    with pytest.raises(RamdiskError):
        ram.restore_ramdisk_name(b"not a plist")


# -----------------------------------------------------------------------------
# ipsw.me lookup (requests stubbed — no network in tests)
# -----------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_fetch_firmware_versions_parses_payload(monkeypatch):
    payload = {"firmwares": [
        {"version": "15.7.1", "signed": True},
        {"version": "15.7", "signed": False},
        {"version": ""},
    ]}
    monkeypatch.setattr(
        ram.requests, "get", lambda *a, **k: _FakeResponse(payload))
    out = ram.fetch_firmware_versions("iPhone10,3")
    assert out == [
        {"version": "15.7.1", "signed": True},
        {"version": "15.7", "signed": False},
        {"version": "", "signed": False},
    ]


def test_fetch_firmware_versions_raises_on_http_error(monkeypatch):
    def boom(*args, **kwargs):
        raise ram.requests.RequestException("offline")

    monkeypatch.setattr(ram.requests, "get", boom)
    with pytest.raises(RamdiskError):
        ram.fetch_firmware_versions("iPhone10,3")


def test_resolve_ipsw_url_picks_matching_version(monkeypatch):
    payload = {"firmwares": [
        {"version": "15.7.1", "url": "https://example/15.7.1.ipsw"},
        {"version": "15.7", "url": "https://example/15.7.ipsw"},
    ]}
    monkeypatch.setattr(
        ram.requests, "get", lambda *a, **k: _FakeResponse(payload))
    assert ram.resolve_ipsw_url("iPhone10,3", "15.7") == \
        "https://example/15.7.ipsw"
    with pytest.raises(RamdiskError):
        ram.resolve_ipsw_url("iPhone10,3", "14.0")


# -----------------------------------------------------------------------------
# pzb fetch honesty (pzb exits 0 even on failure)
# -----------------------------------------------------------------------------

def test_pzb_fetch_raises_when_output_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(ram, "wsl_tool", lambda *a, **k: 0)
    with pytest.raises(RamdiskError):
        ram._pzb_fetch("iBSS.d22.im4p", "https://example/ipsw",
                       cwd=str(tmp_path), log_cb=lambda m: None,
                       is_cancelled_cb=lambda: False)


def test_pzb_fetch_accepts_written_file(monkeypatch, tmp_path):
    target = tmp_path / "iBSS.d22.im4p"

    def fake_wsl_tool(*args, **kwargs):
        target.write_bytes(b"im4p payload")
        return 0

    monkeypatch.setattr(ram, "wsl_tool", fake_wsl_tool)
    ram._pzb_fetch("iBSS.d22.im4p", "https://example/ipsw",
                   cwd=str(tmp_path), log_cb=lambda m: None,
                   is_cancelled_cb=lambda: False)
    assert target.read_bytes() == b"im4p payload"


# -----------------------------------------------------------------------------
# Command construction (run_streaming stubbed — asserts argv, not behaviour)
# -----------------------------------------------------------------------------

def test_wsl_tool_builds_expected_command(monkeypatch, tmp_path):
    seen = {}

    def fake_run_streaming(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["cwd"] = kwargs.get("cwd")
        return 0

    monkeypatch.setattr(ram, "run_streaming", fake_run_streaming)
    monkeypatch.setattr(ram, "wsl_available", lambda: True)
    monkeypatch.setattr(ram, "_wsl_distro", "Ubuntu")

    ram.wsl_tool("img4", ["-i", r"C:\run\in.im4p", "-o", r"C:\run\out.img4"],
                 cwd=r"C:\run", log_cb=lambda m: None,
                 is_cancelled_cb=lambda: False)

    cmd = seen["cmd"]
    assert cmd[0] == "wsl.exe"
    assert cmd[1:4] == ["-d", "Ubuntu", "-e"]
    inner = cmd[4:]
    assert inner[0] == "bash" and inner[1] == "-c"
    script = inner[2]
    assert "cd '/mnt/c/run'" in script
    # Absolute argv paths must be translated too (WSL only rewrites cwd).
    assert "'/mnt/c/run/in.im4p'" in script
    assert "'/mnt/c/run/out.img4'" in script


def test_wsl_arg_translation():
    assert ram.wsl_arg(r"C:\Users\x\a.im4p") == "/mnt/c/Users/x/a.im4p"
    assert ram.wsl_arg("D:/tools/b.bin") == "/mnt/d/tools/b.bin"
    assert ram.wsl_arg("work/ramdisk.dmg") == "work/ramdisk.dmg"
    assert ram.wsl_arg("/mnt/c/already/translated") == \
        "/mnt/c/already/translated"
    assert ram.wsl_arg("https://example/x.ipsw") == \
        "https://example/x.ipsw"
    assert ram.wsl_arg("0" * 128) == "0" * 128


def test_native_tool_runs_vendored_exe_from_run_root(monkeypatch):
    seen = {}

    def fake_run_streaming(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["cwd"] = kwargs.get("cwd")
        return 0

    monkeypatch.setattr(ram, "run_streaming", fake_run_streaming)
    ram.native_tool("irecovery", ["-q"], log_cb=lambda m: None,
                    is_cancelled_cb=lambda: False)
    assert seen["cmd"][0] == ram.win_tool("irecovery")
    assert seen["cmd"][1:] == ["-q"]
    assert seen["cwd"] == ram.run_root()


def test_wsl_arg_normalises_relative_path_separators():
    # WSL rewrites cwd but not argv, so a relative Windows path reaches the
    # Linux binary verbatim and open() rejects the backslash.
    assert ram.wsl_arg(r"work\iBSS.d20.RELEASE.im4p") == \
        "work/iBSS.d20.RELEASE.im4p"
    assert ram.wsl_arg(r"work\iBSS.dec") == "work/iBSS.dec"


def test_wsl_arg_leaves_non_paths_alone():
    # Boot-args, URLs and hex ivkeys must survive untouched.
    boot_args = "rd=md0 debug=0x2014e -v wdt=-1"
    assert ram.wsl_arg(boot_args) == boot_args
    url = "https://updates.cdn-apple.com/a/b.ipsw"
    assert ram.wsl_arg(url) == url
    ivkey = "0b62971cc8919dcd" + "0" * 64
    assert ram.wsl_arg(ivkey) == ivkey


def test_pwn_and_settle_skips_reset_when_already_pwned(monkeypatch):
    """A device that is already pwned must not be reset: the reset hands it
    back to Apple's DFU driver, which then hides it from libusb."""
    monkeypatch.setattr(ram, "gaster_pwn", lambda *a: False)
    monkeypatch.setattr(
        ram, "usb_reset",
        lambda *a: pytest.fail("usb_reset must not run for an already-pwned device"))

    logs = []
    ram._pwn_and_settle(logs.append, lambda: False)
    assert any("skipping USB reset" in m for m in logs)


def test_pwn_and_settle_tolerates_reset_failure(monkeypatch):
    """irecovery can still reach the device, so a failed reset is not fatal."""
    monkeypatch.setattr(ram, "gaster_pwn", lambda *a: True)

    def boom(log_cb):
        raise ram.RamdiskError("USB reset failed: Input/Output Error")

    monkeypatch.setattr(ram, "usb_reset", boom)
    logs = []
    ram._pwn_and_settle(logs.append, lambda: False)
    assert any("USB reset failed" in m for m in logs)


def test_gaster_pwn_reports_whether_it_pwned(monkeypatch):
    monkeypatch.setattr(ram, "detect_device",
                        lambda: {"cpid": "0x8015", "pwned": True})
    monkeypatch.setattr(ram, "native_tool", lambda *a, **k: 0)
    assert ram.gaster_pwn(lambda m: None, lambda: False) is False

    state = {"pwned": False}
    monkeypatch.setattr(
        ram, "detect_device",
        lambda: {"cpid": "0x8015", "pwned": state["pwned"]})

    def fake_native(tool, args, **kwargs):
        state["pwned"] = True
        return 0

    monkeypatch.setattr(ram, "native_tool", fake_native)
    assert ram.gaster_pwn(lambda m: None, lambda: False) is True


def test_pwn_and_settle_falls_back_to_pnp_restart(monkeypatch):
    """Apple's DFU driver hides the device from libusb, so a failed libusb
    reset must fall through to a PnP restart rather than being fatal."""
    monkeypatch.setattr(ram, "gaster_pwn", lambda *a: True)
    monkeypatch.setattr(
        ram, "usb_reset",
        lambda *a: (_ for _ in ()).throw(ram.RamdiskError("no Apple USB device")))
    seen = []
    monkeypatch.setattr(ram, "usb_restart_device", seen.append)
    logs = []
    ram._pwn_and_settle(logs.append, lambda: False)
    assert seen == [logs.append]
    assert any("libusb reset unavailable" in m for m in logs)


def test_usb_restart_device_reports_permission_problem(monkeypatch):
    monkeypatch.setattr(ram, "detect_device", lambda: {"cpid": "0x8015"})
    monkeypatch.setattr(
        ram, "run_capture",
        lambda *a, **k: (1, "Failed to restart device: Access is denied."))
    with pytest.raises(RamdiskError, match="administrator"):
        ram.usb_restart_device(lambda m: None)


def test_usb_restart_device_requires_device_present(monkeypatch):
    monkeypatch.setattr(ram, "detect_device", lambda: None)
    with pytest.raises(RamdiskError, match="not responding"):
        ram.usb_restart_device(lambda m: None)


def test_run_streaming_timeout_covers_a_tool_that_never_exits(tmp_path):
    """The Windows gaster build lingers after pwning and never closes stdout.

    A timeout applied only to proc.wait() is never reached, because reading the
    output blocks first -- so the streaming wait has to be bounded too.
    """
    script = tmp_path / "hang.py"
    script.write_text("import time\nwhile True: time.sleep(0.2)\n")

    logs = []
    with pytest.raises(ram.RamdiskTimeout):
        ram.run_streaming(
            [sys.executable, str(script)], cwd=None,
            log_cb=logs.append, is_cancelled_cb=lambda: False,
            context="hang", timeout=1.5)


def test_run_streaming_completes_when_child_exits(tmp_path):
    script = tmp_path / "quick.py"
    script.write_text("print('hello')\n")
    logs = []
    rc = ram.run_streaming(
        [sys.executable, str(script)], cwd=None,
        log_cb=logs.append, is_cancelled_cb=lambda: False, timeout=30)
    assert rc == 0
    assert any("hello" in m for m in logs)


def test_ensure_dfu_driver_reports_permission_problem(monkeypatch):
    monkeypatch.setattr(
        ram, "run_capture",
        lambda *a, **k: (1, "Access is denied."))
    with pytest.raises(ram.RamdiskError, match="administrator"):
        ram.ensure_dfu_driver(lambda m: None)


def test_gaster_pwn_raises_usb_timeout_env(monkeypatch):
    """This gaster build defaults USB_TIMEOUT to 5 ms, which its own USB
    transfers cannot meet -- pwn/decrypt fail or hang unless it is raised."""
    state = {"pwned": False}
    monkeypatch.setattr(
        ram, "detect_device",
        lambda: {"cpid": "0x8015", "pwned": state["pwned"]})
    monkeypatch.setattr(ram, "ensure_dfu_driver", lambda log_cb: None)

    seen = {}

    def fake_native(tool, args, **kwargs):
        seen.update(kwargs)
        state["pwned"] = True
        return 0

    monkeypatch.setattr(ram, "native_tool", fake_native)
    ram.gaster_pwn(lambda m: None, lambda: False)
    assert seen["extra_env"] == ram.GASTER_ENV
    assert int(ram.GASTER_ENV["USB_TIMEOUT"]) >= 30000


def test_gaster_pwn_survives_driver_switch_failure(monkeypatch):
    """A permission problem switching drivers must not abort the pwn: on an
    already-pwned device the pwn is skipped entirely."""
    monkeypatch.setattr(
        ram, "detect_device",
        lambda: {"cpid": "0x8015", "pwned": False})
    monkeypatch.setattr(ram, "native_tool", lambda *a, **k: 0)

    def boom(log_cb):
        raise ram.RamdiskError("needs administrator rights")

    monkeypatch.setattr(ram, "ensure_dfu_driver", boom)
    logs = []
    ram.gaster_pwn(logs.append, lambda: False)
    assert any("administrator" in m for m in logs)


def test_gaster_helpers_use_native_tool(monkeypatch):
    calls = []

    def fake_native_tool(tool, args, **kwargs):
        calls.append((tool, tuple(args), kwargs.get("allow_failure")))
        return 0

    monkeypatch.setattr(ram, "native_tool", fake_native_tool)
    monkeypatch.setattr(ram, "wsl_available", lambda: True)
    monkeypatch.setattr(ram, "detect_device", lambda: None)
    monkeypatch.setattr(ram, "ensure_dfu_driver", lambda log_cb: None)

    ram.gaster_pwn(lambda m: None, lambda: False)

    assert calls[0][:2] == ("gaster", ("pwn",))


def test_parse_device_info_flags_pwned_checkm8():
    pwned = ram.parse_device_info(
        "CPID: 0x8015\nECID: 0x00044dd83ea0002e\nMODE: DFU\nPWND: CHECKM8\n")
    assert pwned["pwned"] is True
    # irecovery prints PWND: N/A on an un-pwned device, which must not read
    # as pwned — otherwise a fresh device skips the pwn it needs.
    plain = ram.parse_device_info("CPID: 0x8015\nMODE: DFU\nPWND: N/A\n")
    assert plain["pwned"] is False
    assert ram.parse_device_info("CPID: 0x8015")["pwned"] is False


def test_gaster_pwn_skipped_when_device_already_pwned(monkeypatch):
    monkeypatch.setattr(
        ram, "detect_device",
        lambda: {"cpid": "0x8015", "pwned": True, "mode": "DFU"})
    monkeypatch.setattr(
        ram, "native_tool",
        lambda *a, **k: pytest.fail("gaster must not re-pwn a pwned device"))

    logs = []
    ram.gaster_pwn(logs.append, lambda: False)

    assert any("already pwned" in m for m in logs)


def test_gaster_pwn_accepts_lingering_tool_after_timeout(monkeypatch):
    """The Windows gaster build pwns, then never exits. Timeout is fine if
    the device confirms the pwn landed."""
    state = {"pwned": False}

    def fake_native_tool(tool, args, **kwargs):
        assert tool == "gaster" and args == ["pwn"]
        assert kwargs["timeout"] == ram.PWN_TIMEOUT
        state["pwned"] = True  # exploit landed, but the tool keeps running
        raise ram.RamdiskTimeout("gaster pwn timed out after 90.0s")

    monkeypatch.setattr(
        ram, "detect_device",
        lambda: {"cpid": "0x8015", "pwned": state["pwned"]})
    monkeypatch.setattr(ram, "native_tool", fake_native_tool)

    logs = []
    ram.gaster_pwn(logs.append, lambda: False)

    assert any("lingered" in m for m in logs)


def test_gaster_pwn_timeout_without_pwn_raises(monkeypatch):
    """Timing out is only success if the device actually reports pwned."""
    monkeypatch.setattr(ram, "detect_device", lambda: None)
    monkeypatch.setattr(
        ram, "native_tool",
        lambda *a, **k: (_ for _ in ()).throw(
            ram.RamdiskTimeout("gaster pwn timed out after 90.0s")))

    with pytest.raises(RamdiskError, match="did not take effect"):
        ram.gaster_pwn(lambda m: None, lambda: False)


def test_op_create_requires_wsl_before_touching_device(monkeypatch):
    monkeypatch.setattr(ram, "wsl_available", lambda: False)
    steps = []
    with pytest.raises(RamdiskError):
        ram.op_create("15.7.1", "",
                      progress_cb=lambda p, step="", detail="":
                          steps.append((p, step)),
                      log_cb=lambda m: None,
                      is_cancelled_cb=lambda: False)
    assert steps and steps[0][1] == "Detect Device"


def test_default_dump_path_name():
    assert ram.default_dump_path().endswith("dumped.shsh2")


def test_ensure_tar_extracts_vendored_payload(monkeypatch, tmp_path):
    monkeypatch.setattr(ram, "sshtar_cache", lambda: str(tmp_path))
    out = ram._ensure_tar("ssh")
    assert out == str(tmp_path / "ssh.tar")
    assert os.path.getsize(out) > 0


# -----------------------------------------------------------------------------
# op_boot decision replay (sshrd.sh boot branch, no hardware)
# -----------------------------------------------------------------------------

def _run_op_boot(monkeypatch, tmp_path, cpid: str, version: str):
    sd = tmp_path / "sshramdisk"
    sd.mkdir()
    (sd / "iBSS.img4").write_bytes(b"stub")
    (sd / "version.txt").write_text(version, encoding="utf-8")

    calls = []
    monkeypatch.setattr(ram, "sshramdisk_dir", lambda: str(sd))
    monkeypatch.setattr(
        ram, "wait_for_device",
        lambda log_cb, cb: {"cpid": cpid, "model": "d221ap",
                            "product": "iPhone10,3", "ecid": "", "mode": "DFU"})
    monkeypatch.setattr(ram, "gaster_pwn", lambda *a: None)
    monkeypatch.setattr(ram, "usb_reset", lambda *a: None)
    monkeypatch.setattr(ram, "_sleep", lambda *a: None)
    monkeypatch.setattr(
        ram, "native_tool",
        lambda tool, args, **kw: calls.append((tool, tuple(args))) or 0)

    ram.op_boot(lambda p, step="", detail="": None,
                lambda m: None, lambda: False)
    return calls


def _sent_files(calls):
    return [args[1] for tool, args in calls
            if tool == "irecovery" and args[:1] == ("-f",)]


def _commands(calls):
    return [args[1] for tool, args in calls
            if tool == "irecovery" and args[:1] == ("-c",)]


def test_op_boot_a11_sends_go_and_trustcache(monkeypatch, tmp_path):
    calls = _run_op_boot(monkeypatch, tmp_path, "0x8010", "15.7.1")
    files = [f.replace("\\", "/") for f in _sent_files(calls)]
    cmds = _commands(calls)

    assert files[0].endswith("sshramdisk/iBSS.img4")
    assert any(f.endswith("sshramdisk/iBEC.img4") for f in files)
    assert "go" in cmds                                  # A10/A11/A12/T2
    assert any("trustcache.img4" in f for f in files)    # dm 21 -> needed
    assert "bootx" == cmds[-1]                           # bootx is terminal


def test_op_boot_a7_omits_go_and_trustcache(monkeypatch, tmp_path):
    calls = _run_op_boot(monkeypatch, tmp_path, "0x8960", "11.2")
    cmds = _commands(calls)
    files = _sent_files(calls)

    assert "go" not in cmds                              # 0x8960 never goes
    assert not any("trustcache.img4" in f for f in files)  # dm 17.2 -> skip
    assert "bootx" == cmds[-1]


def test_op_boot_t2_uses_plus15_darwin_mapping(monkeypatch, tmp_path):
    # T2 maps iOS 11.4 -> darwin 26 (major+15), so trustcache IS sent even
    # though an A7 on the same iOS would skip it at darwin 17.4.
    calls = _run_op_boot(monkeypatch, tmp_path, "0x8012", "11.4")
    files = _sent_files(calls)
    assert any("trustcache.img4" in f for f in files)
    assert "go" in _commands(calls)                      # 0x8012 goes


def test_op_boot_requires_built_ramdisk(monkeypatch, tmp_path):
    sd = tmp_path / "empty"
    sd.mkdir()
    monkeypatch.setattr(ram, "sshramdisk_dir", lambda: str(sd))
    with pytest.raises(RamdiskError):
        ram.op_boot(lambda *a, **k: None, lambda m: None, lambda: False)
