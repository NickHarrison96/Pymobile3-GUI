"""Unit tests for the experimental A12/A13 ramdisk manager.

Everything runs offline: USB access, WSL tool execution, the ipsw.me API and
the filesystem are stubbed, and the tests assert the *constructed* argv and the
boot decision table rather than running any tool. The upstream toolkit's own
patchers are never invoked here either.
"""

import os
import plistlib

import pytest

from pymobile3_gui.core.backend import ich_ramdisk as ich
from pymobile3_gui.core.backend import ramdisk_manager as ram
from pymobile3_gui.core.backend.ramdisk_manager import RamdiskError


# -----------------------------------------------------------------------------
# BuildManifest resolution
# -----------------------------------------------------------------------------

def _manifest(model="d321ap", extra=None, omit=()):
    images = {}
    required = {
        "iBEC": "Firmware/dfu/iBEC.d21.RELEASE",
        "DeviceTree": "Firmware/all_flash/DeviceTree.d21.im4p",
        "KernelCache": "Firmware/kernelcache.release.d21",
        "RestoreRamDisk": "Firmware/RestoreRamDisk.d21.dmg",
        "RestoreTrustCache": "Firmware/RestoreTrustCache.d21.trustcache",
        "iBSS": "Firmware/dfu/iBSS.d21.RELEASE",
        "RestoreSEP": "Firmware/sep-firmware.d21.img4",
    }
    for key, path in required.items():
        if key not in omit:
            images[key] = {"Info": {"Path": path}}
    for key, path in (extra or {}).items():
        images[key] = {"Info": {"Path": path}}
    return plistlib.dumps({"BuildIdentities": [
        {"Info": {"DeviceClass": model, "BuildNumber": "21F90"},
         "Manifest": images},
    ]})

def test_resolve_components_returns_required_and_optional():
    comp = ich.resolve_components(_manifest(), "d321ap")
    assert comp["iBEC"].endswith("iBEC.d21.RELEASE")
    assert comp["RestoreRamDisk"].endswith("RestoreRamDisk.d21.dmg")
    assert comp["RestoreTrustCache"].endswith(".trustcache")
    assert comp["iBSS"].endswith("iBSS.d21.RELEASE")
    assert comp["RestoreSEP"].endswith("sep-firmware.d21.img4")
    assert comp["build"] == "21F90"


def test_resolve_components_omits_absent_optional_components():
    comp = ich.resolve_components(_manifest(), "d321ap")
    assert "SPTM" not in comp
    assert "TXM" not in comp
    assert "PMP" not in comp          # A13-only, absent from this manifest


def test_resolve_components_honours_renamed_keys():
    """iOS 27-class firmware ships SPTM/TXM under namespaced keys."""
    comp = ich.resolve_components(
        _manifest(extra={"Ap,SPTM": "sp.bin", "Ap,TXM": "tx.bin"}),
        "d321ap")
    assert comp["SPTM"] == "sp.bin"
    assert comp["TXM"] == "tx.bin"


def test_resolve_components_falls_back_when_there_is_one_identity():
    """A manifest with a single identity is used even for a different board."""
    comp = ich.resolve_components(_manifest(model="n841ap"), "d999ap")
    assert comp["iBEC"].endswith("iBEC.d21.RELEASE")
    assert comp["build"] == "21F90"


def test_resolve_components_rejects_a_missing_required_component():
    with pytest.raises(RamdiskError, match="RestoreRamDisk"):
        ich.resolve_components(_manifest(omit=("RestoreRamDisk",)), "d321ap")


def test_resolve_components_rejects_an_unknown_board_with_several_identities():
    data = plistlib.dumps({"BuildIdentities": [
        {"Info": {"DeviceClass": "d321ap", "BuildNumber": "A"},
         "Manifest": {"iBEC": {"Info": {"Path": "a.bin"}}}},
        {"Info": {"DeviceClass": "n841ap", "BuildNumber": "B"},
         "Manifest": {"iBEC": {"Info": {"Path": "b.bin"}}}},
    ]})
    with pytest.raises(RamdiskError, match="no identity for board"):
        ich.resolve_components(data, "d999ap")


# -----------------------------------------------------------------------------
# Kernel patch-set selection (build.sh resolve_kpf_set)
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("version,has_txm,expected", [
    ("17.5.1", False, "ios18"),
    ("18.0", False, "ios18"),
    ("26.0", False, "ios18"),   # finder, never the stale byte table
    ("27.0", False, "ios27"),   # major alone is enough
    ("18.0", True, "ios27"),    # TXM firmware present
    ("nonsense", False, "ios18"),
])
def test_resolve_kpf_set(version, has_txm, expected):
    assert ich.resolve_kpf_set(version, has_txm) == expected


# -----------------------------------------------------------------------------
# Device gating
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("cpid,expected", [
    ("0x8020", True), ("0x8030", True), ("0x8015", False), ("0x8110", False),
])
def test_is_ich_device(cpid, expected):
    assert ich.is_ich_device({"cpid": cpid}) is expected


def test_is_ich_device_is_false_for_none():
    assert ich.is_ich_device(None) is False


@pytest.mark.parametrize("pwnd,expected", [
    ("usbliter8", True), ("USBLITER8", True), ("usbliter8 ", True),
    ("", False), ("CHECKM8", False),
])
def test_is_ich_pwned(pwnd, expected):
    assert ich.is_ich_pwned({"cpid": "0x8030", "pwnd": pwnd}) is expected


def test_wait_for_ich_device_rejects_other_chips(monkeypatch):
    monkeypatch.setattr(ram, "detect_device", lambda: {"cpid": "0x8015"})
    with pytest.raises(RamdiskError, match="not an A12/A13 target"):
        ich.wait_for_ich_device(lambda m: None, lambda: False)


# -----------------------------------------------------------------------------
# Toolkit and prepared-file validation
# -----------------------------------------------------------------------------

def test_require_toolkit_rejects_a_blank_path():
    with pytest.raises(RamdiskError, match="No toolkit folder"):
        ich.require_toolkit("   ")


def test_require_toolkit_rejects_a_missing_folder(tmp_path):
    with pytest.raises(RamdiskError, match="not found"):
        ich.require_toolkit(str(tmp_path / "nope"))


def test_require_toolkit_rejects_a_folder_without_patchers(tmp_path):
    with pytest.raises(RamdiskError, match="does not look like a toolkit"):
        ich.require_toolkit(str(tmp_path))


def test_require_toolkit_returns_the_patch_dir(tmp_path):
    patch = tmp_path / "patch"
    patch.mkdir()
    (patch / "iboot_patchfinder.py").write_text("", encoding="utf-8")
    assert ich.require_toolkit(str(tmp_path)) == str(patch)


def test_default_toolkit_dir_prefers_the_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv(ich.TOOLKIT_ENV, str(tmp_path))
    assert ich.default_toolkit_dir() == str(tmp_path)


def test_default_toolkit_dir_falls_back_to_the_desktop(monkeypatch):
    monkeypatch.delenv(ich.TOOLKIT_ENV, raising=False)
    monkeypatch.setenv("USERPROFILE", r"C:\Users\nick")
    assert ich.default_toolkit_dir().endswith(
        os.path.join("Desktop", "A12-A13-Ramdisk"))


def test_require_prepared_rejects_blank_and_missing(tmp_path):
    with pytest.raises(RamdiskError, match="No prepared ramdisk"):
        ich._require_prepared("", "prepared ramdisk image")
    with pytest.raises(RamdiskError, match="not found"):
        ich._require_prepared(str(tmp_path / "rd.dmg"), "prepared ramdisk image")
    empty = tmp_path / "rd.dmg"
    empty.write_bytes(b"")
    with pytest.raises(RamdiskError, match="not found"):
        ich._require_prepared(str(empty), "prepared ramdisk image")


def test_resolve_ticket_names_the_missing_file(tmp_path):
    resources = tmp_path / "resources"
    resources.mkdir()
    with pytest.raises(RamdiskError, match="IM4M_0x8030"):
        ich._resolve_ticket(str(tmp_path), "0x8030", lambda m: None)


def test_resolve_ticket_finds_the_per_chip_ticket(tmp_path):
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "IM4M_0x8030").write_bytes(b"\x30\x82\x01\x0d")
    logs = []
    path = ich._resolve_ticket(str(tmp_path), "0x8030", logs.append)
    assert path.endswith("IM4M_0x8030")
    assert any("IM4M_0x8030" in m for m in logs)


# -----------------------------------------------------------------------------
# WSL argv construction
# -----------------------------------------------------------------------------

def test_wsl_python_translates_argv_paths(monkeypatch):
    """WSL rewrites cwd but never argv, so paths must be converted for real."""
    captured = {}

    def fake_streaming(cmd, **kwargs):
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(ram, "wsl_available", lambda: True)
    monkeypatch.setattr(ram, "_wsl_distro", "Ubuntu")
    monkeypatch.setattr(ich, "ich_root", lambda: r"C:\data\ich")
    monkeypatch.setattr(ram, "run_streaming", fake_streaming)

    ich.wsl_python(
        r"C:\tk\patch\iboot_patchfinder.py",
        [r"C:\data\ich\work\iBEC.raw", r"C:\data\ich\out\iBEC.patched.raw",
         "--mode", "ibec"],
        log_cb=lambda m: None, is_cancelled_cb=lambda: False)

    assert captured["cmd"][:5] == [
        "wsl.exe", "-d", "Ubuntu", "-e", "python3"]
    assert captured["cmd"][5] == "/mnt/c/tk/patch/iboot_patchfinder.py"
    assert captured["cmd"][6] == "/mnt/c/data/ich/work/iBEC.raw"
    assert captured["cmd"][7] == "/mnt/c/data/ich/out/iBEC.patched.raw"
    assert captured["cmd"][8:] == ["--mode", "ibec"]


def test_wsl_python_requires_wsl(monkeypatch):
    monkeypatch.setattr(ram, "wsl_available", lambda: False)
    with pytest.raises(RamdiskError, match="WSL"):
        ich.wsl_python(r"C:\tk\x.py", [], log_cb=lambda m: None,
                       is_cancelled_cb=lambda: False)


def test_python_deps_message_carries_the_fix(monkeypatch):
    monkeypatch.setattr(ram, "wsl_available", lambda: True)
    monkeypatch.setattr(ram, "_wsl_distro", "Ubuntu")
    monkeypatch.setattr(ram, "run_capture", lambda cmd, timeout=15: (1, "boom"))
    ok, detail = ich.python_deps_ok()
    assert ok is False
    assert "pip3 install --break-system-packages capstone pyimg4" in detail
    assert "wsl -d Ubuntu -e pip3" in detail


# -----------------------------------------------------------------------------
# Kernel wrapping
# -----------------------------------------------------------------------------

def test_wrap_kernel_writes_the_helper_and_calls_it(monkeypatch, tmp_path):
    """The helper is materialised on disk: under PyInstaller a .py in the PYZ
    is not a file WSL can execute."""
    monkeypatch.setattr(ich, "ich_root", lambda: str(tmp_path))
    monkeypatch.setattr(ram, "wsl_available", lambda: True)
    monkeypatch.setattr(ram, "_wsl_distro", "Ubuntu")
    captured = {}
    monkeypatch.setattr(
        ich, "wsl_python",
        lambda script, args, **kw: captured.update(script=script, args=args))

    def fake_raw(path):
        open(path, "wb").write(b"payload")
    fake_raw(tmp_path / "kc.raw")
    fake_raw(tmp_path / "kc.stock")
    fake_raw(tmp_path / "IM4M")
    (tmp_path / "out.img4").write_bytes(b"stub")

    ich.wrap_kernel(str(tmp_path / "kc.raw"), str(tmp_path / "kc.stock"),
                    str(tmp_path / "out.img4"), str(tmp_path / "IM4M"),
                    log_cb=lambda m: None, is_cancelled_cb=lambda: False)

    helper = captured["script"]
    assert os.path.isfile(helper)
    assert "pyimg4" in open(helper, encoding="utf-8").read()
    assert captured["args"][0].endswith("kc.raw")
    assert captured["args"][1].endswith("kc.stock")
    assert captured["args"][3].endswith("IM4M")


def test_wrap_kernel_fails_closed_on_no_output(monkeypatch, tmp_path):
    monkeypatch.setattr(ich, "ich_root", lambda: str(tmp_path))
    monkeypatch.setattr(ich, "wsl_python", lambda *a, **k: 0)
    with pytest.raises(RamdiskError, match="produced no"):
        ich.wrap_kernel("a", "b", str(tmp_path / "out.img4"), "c",
                        log_cb=lambda m: None, is_cancelled_cb=lambda: False)


# -----------------------------------------------------------------------------
# IPSW member cache
# -----------------------------------------------------------------------------

def test_fetch_member_reuses_a_cached_download(monkeypatch, tmp_path):
    monkeypatch.setattr(ich, "ich_cache_dir", lambda: str(tmp_path))
    fetched = []
    monkeypatch.setattr(
        ram, "_pzb_fetch",
        lambda member, url, **kw: fetched.append(member))

    cache = tmp_path / "iPhone12,1-21F90"
    cache.mkdir()
    (cache / "iBEC.d21.RELEASE").write_bytes(b"cached")

    path = ich._fetch_member("Firmware/dfu/iBEC.d21.RELEASE", "http://ipsw",
                             "iPhone12,1", "21F90", lambda m: None,
                             lambda: False)
    assert path == str(cache / "iBEC.d21.RELEASE")
    assert fetched == []          # no second download


def test_fetch_member_downloads_a_missing_member(monkeypatch, tmp_path):
    monkeypatch.setattr(ich, "ich_cache_dir", lambda: str(tmp_path))
    seen = {}

    def fake_pzb(member, url, *, cwd, log_cb, is_cancelled_cb):
        seen["cwd"] = cwd
        open(os.path.join(cwd, os.path.basename(member)), "wb").write(b"new")

    monkeypatch.setattr(ram, "_pzb_fetch", fake_pzb)

    path = ich._fetch_member("Firmware/dfu/iBEC.d21.RELEASE", "http://ipsw",
                             "iPhone12,1", "21F90", lambda m: None,
                             lambda: False)
    assert seen["cwd"] == str(tmp_path / "iPhone12,1-21F90")
    assert os.path.getsize(path) == 3


def test_fetch_member_keys_the_cache_by_product_and_build(monkeypatch, tmp_path):
    """A different iOS version must never reuse another build's members."""
    monkeypatch.setattr(ich, "ich_cache_dir", lambda: str(tmp_path))
    calls = []
    monkeypatch.setattr(
        ram, "_pzb_fetch",
        lambda member, url, **kw: calls.append((member, kw["cwd"])))

    ich._fetch_member("Firmware/dfu/iBEC", "u", "iPhone12,1", "21F90",
                      lambda m: None, lambda: False)
    ich._fetch_member("Firmware/dfu/iBEC", "u", "iPhone12,1", "22A100",
                      lambda m: None, lambda: False)
    assert len({cwd for _m, cwd in calls}) == 2


# -----------------------------------------------------------------------------
# irecovery argv (no hardware, no tools)
# -----------------------------------------------------------------------------

def test_irecv_uses_the_upload_timeout_for_f_and_the_command_one_otherwise(
        monkeypatch):
    seen = {}

    def fake_streaming(cmd, **kwargs):
        seen.setdefault("timeouts", []).append(kwargs.get("timeout"))
        return 0

    monkeypatch.setattr(ich, "ich_root", lambda: r"C:\data\ich")
    monkeypatch.setattr(ram, "run_streaming", fake_streaming)
    monkeypatch.setattr(ram, "win_tool", lambda name: rf"C:\assets\{name}.exe")

    ich._irecv(["-f", "bootchain/ramdisk.img4"], log_cb=lambda m: None,
               is_cancelled_cb=lambda: False)
    ich._irecv(["-c", "bootx"], log_cb=lambda m: None,
               is_cancelled_cb=lambda: False)

    assert seen["timeouts"] == [ich.IRECV_UPLOAD_TIMEOUT, ich.IRECV_CMD_TIMEOUT]
    assert seen["timeouts"][0] > seen["timeouts"][1]


def test_bootchain_info_reads_chain_info(tmp_path):
    (tmp_path / "chain.info").write_text(
        "product=iPhone12,1\nversion=18.0\nkernel=patched\n", encoding="utf-8")
    monkeypatch_dir = tmp_path
    assert ich.bootchain_info.__module__  # sanity: function is exported
    original = ich.bootchain_dir
    try:
        ich.bootchain_dir = lambda: str(monkeypatch_dir)
        info = ich.bootchain_info()
    finally:
        ich.bootchain_dir = original
    assert info["product"] == "iPhone12,1"
    assert info["kernel"] == "patched"


# -----------------------------------------------------------------------------
# op_boot decision replay
# -----------------------------------------------------------------------------

def _stage_bootchain(root, *, use_ibss=False, with_fw=False, sep=False,
                     sptm=False, txm=False, logo=False):
    bc = root / "bootchain"
    bc.mkdir(parents=True, exist_ok=True)
    for name in ("kernelcache.img4", "devicetree.img4", "trustcache.img4",
                 "ramdisk.img4", "iBoot.patched.bin"):
        (bc / name).write_bytes(b"stub")
    if use_ibss:
        (bc / "iBSS.patched.bin").write_bytes(b"stub")
        (bc / "iBEC.patched.img4").write_bytes(b"stub")
        (bc / "use-ibss").write_text("1\n", encoding="utf-8")
    if with_fw:
        for name in ich.FW_COMPONENTS:
            (bc / f"{name}.img4").write_bytes(b"stub")
        (bc / "with-fw.enabled").write_text("1\n", encoding="utf-8")
    if sep:
        (bc / "sep-firmware.img4").write_bytes(b"stub")
    if sptm:
        (bc / "sptm.img4").write_bytes(b"stub")
    if txm:
        (bc / "txm.img4").write_bytes(b"stub")
    if logo:
        (bc / "logo.img4").write_bytes(b"stub")
    return bc


def _run_boot(monkeypatch, tmp_path, mode="Recovery", **stage):
    _stage_bootchain(tmp_path, **stage)
    calls = []
    monkeypatch.setattr(ich, "ich_root", lambda: str(tmp_path))
    monkeypatch.setattr(ich, "bootchain_dir", lambda: str(tmp_path / "bootchain"))
    monkeypatch.setattr(
        ich, "wait_for_ich_device",
        lambda log_cb, cb: {"cpid": "0x8030", "model": "d321ap",
                            "product": "iPhone12,1", "ecid": "",
                            "mode": mode, "pwnd": "usbliter8"})
    monkeypatch.setattr(ram, "_sleep", lambda *a: None)
    monkeypatch.setattr(ich, "wait_for_recovery", lambda *a, **k: {"mode": "Recovery"})
    monkeypatch.setattr(
        ram, "run_streaming",
        lambda cmd, **kw: calls.append((tuple(cmd[1:]), kw.get("timeout"))) or 0)

    steps = []
    ich.op_boot(lambda p, step="", detail="": steps.append(step),
                lambda m: None, lambda: False)
    return calls, steps


def _files(calls):
    return [a[0][1] for a in calls if a[0][:1] == ("-f",)]


def _cmds(calls):
    return [a[0][1] for a in calls if a[0][:1] == ("-c",)]


def test_op_boot_refuses_a_device_still_in_dfu(monkeypatch, tmp_path):
    _stage_bootchain(tmp_path)
    monkeypatch.setattr(ich, "ich_root", lambda: str(tmp_path))
    monkeypatch.setattr(ich, "bootchain_dir", lambda: str(tmp_path / "bootchain"))
    monkeypatch.setattr(
        ich, "wait_for_ich_device",
        lambda log_cb, cb: {"cpid": "0x8030", "mode": "DFU", "pwnd": "usbliter8"})
    with pytest.raises(RamdiskError, match="still in pwned DFU"):
        ich.op_boot(lambda p, step="", detail="": None, lambda m: None,
                    lambda: False)


def test_op_boot_requires_a_staged_bootchain(monkeypatch, tmp_path):
    monkeypatch.setattr(ich, "bootchain_dir", lambda: str(tmp_path / "none"))
    with pytest.raises(RamdiskError, match="No A12/A13 bootchain staged"):
        ich.op_boot(lambda p, step="", detail="": None, lambda m: None,
                    lambda: False)


def test_op_boot_direct_ibec_order_and_setenvnp(monkeypatch, tmp_path):
    calls, steps = _run_boot(monkeypatch, tmp_path)
    cmds = _cmds(calls)

    assert "bootx" == cmds[-1]
    # setenvnp has to come immediately before bootx or the verbose text is lost.
    assert cmds[-2].startswith("setenvnp boot-args rd=md0")
    assert "go" not in cmds                     # direct iBEC path never sends go
    assert cmds[0] == "bgcolor 0 0 0"
    # firmware order: devicetree -> trustcache -> ramdisk -> kernel
    order = [c for c in cmds if c in ("devicetree", "firmware", "ramdisk")]
    assert order[:3] == ["devicetree", "firmware", "ramdisk"]
    assert steps[-1] == "Boot Ramdisk"
    assert all(s in ich.BOOT_STEPS for s in steps)


def test_op_boot_use_ibss_sends_go_then_waits(monkeypatch, tmp_path):
    calls, _ = _run_boot(monkeypatch, tmp_path, use_ibss=True)
    files = [f.replace("\\", "/") for f in _files(calls)]
    cmds = _cmds(calls)
    assert files[0].endswith("bootchain/iBSS.patched.bin")
    assert any(f.endswith("bootchain/iBEC.patched.img4") for f in files)
    assert "go" in cmds


def test_op_boot_loads_sep_with_rsepfirmware(monkeypatch, tmp_path):
    calls, _ = _run_boot(monkeypatch, tmp_path, sep=True)
    cmds = _cmds(calls)
    files = [f.replace("\\", "/") for f in _files(calls)]
    assert "rsepfirmware" in cmds
    assert "sepfirmware" not in cmds
    assert any(f.endswith("bootchain/sep-firmware.img4") for f in files)


def test_op_boot_loads_sptm_and_txm_when_staged(monkeypatch, tmp_path):
    calls, _ = _run_boot(monkeypatch, tmp_path, sptm=True, txm=True)
    files = [f.replace("\\", "/") for f in _files(calls)]
    assert any(f.endswith("bootchain/sptm.img4") for f in files)
    assert any(f.endswith("bootchain/txm.img4") for f in files)


def test_op_boot_firmware_comes_before_the_ramdisk_without_ibss(
        monkeypatch, tmp_path):
    calls, _ = _run_boot(monkeypatch, tmp_path, with_fw=True, use_ibss=False)
    files = [f.replace("\\", "/") for f in _files(calls)]
    aop = next(i for i, f in enumerate(files) if f.endswith("AOP.img4"))
    ramdisk = next(i for i, f in enumerate(files) if f.endswith("ramdisk.img4"))
    assert aop < ramdisk


def test_op_boot_firmware_comes_after_the_ramdisk_with_ibss(
        monkeypatch, tmp_path):
    calls, _ = _run_boot(monkeypatch, tmp_path, with_fw=True, use_ibss=True)
    files = [f.replace("\\", "/") for f in _files(calls)]
    aop = [i for i, f in enumerate(files) if f.endswith("AOP.img4")][0]
    ramdisk = [i for i, f in enumerate(files) if f.endswith("ramdisk.img4")][0]
    assert aop > ramdisk


def test_op_boot_logo_uses_setpicture(monkeypatch, tmp_path):
    calls, _ = _run_boot(monkeypatch, tmp_path, logo=True)
    cmds = _cmds(calls)
    files = [f.replace("\\", "/") for f in _files(calls)]
    assert any(f.endswith("bootchain/logo.img4") for f in files)
    assert "setpicture 1" in cmds
    assert cmds.index("bgcolor 0 0 0") < cmds.index("setpicture 1")


def test_op_boot_falls_back_to_setenv(monkeypatch, tmp_path):
    """Some iBoot builds reject setenvnp; setenv still gets the args across."""
    calls = []

    def fake_streaming(cmd, **kwargs):
        args = tuple(cmd[1:])
        calls.append(args)
        if args[:1] == ("-c",) and args[1].startswith("setenvnp boot-args"):
            return 1        # setenvnp rejected by this iBoot
        return 0

    _stage_bootchain(tmp_path)
    monkeypatch.setattr(ich, "ich_root", lambda: str(tmp_path))
    monkeypatch.setattr(ich, "bootchain_dir", lambda: str(tmp_path / "bootchain"))
    monkeypatch.setattr(
        ich, "wait_for_ich_device",
        lambda log_cb, cb: {"cpid": "0x8030", "mode": "Recovery"})
    monkeypatch.setattr(ram, "_sleep", lambda *a: None)
    monkeypatch.setattr(ram, "run_streaming", fake_streaming)

    ich.op_boot(lambda p, step="", detail="": None, lambda m: None,
                lambda: False)

    cmds = [a[1] for a in calls if a[:1] == ("-c",)]
    assert any(c.startswith("setenv boot-args rd=md0") for c in cmds)
    assert cmds[-1] == "bootx"
    assert cmds.index([c for c in cmds
                       if c.startswith("setenv boot-args")][0]) == len(cmds) - 2


# -----------------------------------------------------------------------------
# op_create argv replay
# -----------------------------------------------------------------------------

def _toolkit(root):
    patch = root / "patch"
    patch.mkdir(parents=True, exist_ok=True)
    for name in ("iboot_patchfinder.py", "finalize_iboot.py",
                 "apply_kernel_patches.py", "sptm_patchfinder.py",
                 "txm_patchfinder.py"):
        (patch / name).write_text("", encoding="utf-8")
    resources = root / "resources"
    resources.mkdir(parents=True, exist_ok=True)
    (resources / "IM4M_0x8030").write_bytes(b"\x30\x82\x01\x0d")
    return root


def _prepared(root):
    rd = root / "ramdisk.expanded.dmg"
    rd.write_bytes(b"\x00" * 1024)
    tc = root / "trustcache.bin"
    tc.write_bytes(b"\x00" * 64)
    return str(rd), str(tc)


def _run_create(monkeypatch, tmp_path, *, use_ibss=False, with_fw=True,
                kernel_mode="patched", kpf_set="auto",
                trustcache_mode="prepared", extra_manifest=None,
                omit=(), use_prepared_trustcache=True, fw_omit=()):
    root = _toolkit(tmp_path / "tk")
    rd, tc = _prepared(tmp_path)
    if not use_prepared_trustcache:
        tc = ""
    monkeypatch.setattr(ich, "ich_root", lambda: str(tmp_path / "data"))
    monkeypatch.setattr(ich, "bootchain_dir",
                        lambda: str(tmp_path / "data" / "bootchain"))
    monkeypatch.setattr(ich, "ich_work_dir",
                        lambda: str(tmp_path / "data" / "work"))
    monkeypatch.setattr(ich, "ich_cache_dir",
                        lambda: str(tmp_path / "data" / "cache"))
    monkeypatch.setattr(ich, "require_toolkit", lambda tk: str(root / "patch"))
    monkeypatch.setattr(ram, "wsl_available", lambda: True)
    monkeypatch.setattr(ram, "_wsl_distro", "Ubuntu")
    monkeypatch.setattr(
        ich, "wait_for_ich_device",
        lambda log_cb, cb: {"cpid": "0x8030", "model": "d321ap",
                            "product": "iPhone12,1", "ecid": "",
                            "mode": "DFU", "pwnd": "usbliter8"})
    monkeypatch.setattr(ram, "resolve_ipsw_url",
                        lambda product, version:
                        "http://ipsw/iPhone12,1_21F90.ipsw")
    monkeypatch.setattr(ram, "build_number_from_ipsw_url", lambda url: "21F90")

    manifest = plistlib.loads(_manifest(extra=extra_manifest, omit=omit))
    if with_fw:
        for key in ("AOP", "ANE", "AVE", "ISP", "GFX", "SIO"):
            if key in fw_omit:
                continue
            manifest["BuildIdentities"][0]["Manifest"][key] = {
                "Info": {"Path": f"Firmware/{key}.d21.img4"}}
    manifest = plistlib.dumps(manifest)

    def fake_pzb(member, url, *, cwd, log_cb, is_cancelled_cb):
        os.makedirs(cwd, exist_ok=True)
        payload = manifest if member.endswith("BuildManifest.plist") else b"stub"
        with open(os.path.join(cwd, os.path.basename(member)), "wb") as fh:
            fh.write(payload)

    monkeypatch.setattr(ram, "_pzb_fetch", fake_pzb)

    wsl_calls = []
    monkeypatch.setattr(
        ich, "wsl_tool",
        lambda tool, args, **kw: wsl_calls.append(("wsl", tool, tuple(args))) or 0)

    # The real patchers write their output file and op_create goes on to copy,
    # wrap and sign it, so the stub has to as well. Paths that op_create left
    # relative are relative to ich_root().
    data_root = str(tmp_path / "data")

    def _resolve(path):
        return path if os.path.isabs(path) else os.path.join(data_root, path)

    def fake_python(script, args, **kw):
        py_calls.append((os.path.basename(script), tuple(args)))
        if "--output" in args:
            out = args[args.index("--output") + 1]
        elif len(args) > 1 and not args[-1].startswith("-"):
            out = args[1]          # positional output of the *finder scripts
        else:
            out = None
        if out:
            target = _resolve(out)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(b"patched")
        return 0

    py_calls = []
    monkeypatch.setattr(ich, "wsl_python", fake_python)

    def fake_wrap(raw, original, output, ticket, **kw):
        open(output, "wb").write(b"wrapped")

    monkeypatch.setattr(ich, "wrap_kernel", fake_wrap)

    steps = []
    ich.op_create(
        "18.0", str(root), rd, prepared_trustcache=tc,
        trustcache_mode=trustcache_mode, kernel_mode=kernel_mode,
        kpf_set=kpf_set, with_fw=with_fw, use_ibss=use_ibss,
        progress_cb=lambda p, step="", detail="": steps.append((p, step)),
        log_cb=lambda m: None, is_cancelled_cb=lambda: False)
    return wsl_calls, py_calls, steps


def test_op_create_patches_and_signs_the_bootchain(monkeypatch, tmp_path):
    wsl_calls, py_calls, steps = _run_create(monkeypatch, tmp_path)

    scripts = [s for s, _a in py_calls]
    assert scripts.count("iboot_patchfinder.py") == 1     # iBEC only, no iBSS
    assert "finalize_iboot.py" in scripts
    assert "apply_kernel_patches.py" in scripts

    iboot = next(a for s, a in py_calls if s == "iboot_patchfinder.py")
    assert iboot[-2:] == ("--mode", "ibec")

    img4_args = [a for _k, tool, a in wsl_calls if tool == "img4"]
    types = {a[a.index("-T") + 1] for a in img4_args if "-T" in a}
    # rdsk wraps the prepared ramdisk, rtsc the trustcache, rdtr the devicetree.
    assert {"rdsk", "rtsc", "rdtr"} <= types
    # Only the ramdisk and trustcache are wrapped from a plain file with -A;
    # DeviceTree is already an IM4P.
    wrapped = {a[a.index("-T") + 1] for a in img4_args if "-A" in a}
    assert {"rdsk", "rtsc"} <= wrapped
    assert "rdtr" not in wrapped

    assert steps[0] == (0, "Detect Device")
    assert steps[-1][1] == "Finalize"
    assert all(step in ich.CREATE_STEPS for _p, step in steps)


def test_op_create_use_ibss_patches_ibss_and_types_the_ibec_handoff(
        monkeypatch, tmp_path):
    wsl_calls, py_calls, _ = _run_create(monkeypatch, tmp_path, use_ibss=True)
    modes = [a[-1] for s, a in py_calls if s == "iboot_patchfinder.py"]
    assert sorted(modes) == ["ibec", "ibss"]
    tagged = [a for _k, tool, a in wsl_calls
              if tool == "img4" and "-T" in a and a[a.index("-T") + 1] == "ibec"]
    assert any("iBEC.patched.img4" in " ".join(a) for a in tagged)


def test_op_create_patches_sptm_and_txm_when_present(monkeypatch, tmp_path):
    _wsl, py_calls, _ = _run_create(
        monkeypatch, tmp_path,
        extra_manifest={"Ap,SPTM": "sp.bin", "Ap,TXM": "tx.bin"})
    scripts = [s for s, _a in py_calls]
    assert "sptm_patchfinder.py" in scripts
    assert "txm_patchfinder.py" in scripts


def test_op_create_stock_kernel_skips_the_patchfinder(monkeypatch, tmp_path):
    _wsl, py_calls, _ = _run_create(monkeypatch, tmp_path,
                                    kernel_mode="stock")
    assert "apply_kernel_patches.py" not in [s for s, _a in py_calls]


def test_op_create_explicit_kpf_set_is_passed_through(monkeypatch, tmp_path):
    _wsl, py_calls, _ = _run_create(monkeypatch, tmp_path, kpf_set="ios27")
    kpf = next(a for s, a in py_calls if s == "apply_kernel_patches.py")
    assert kpf[kpf.index("--kpf-set") + 1] == "ios27"


def test_op_create_without_fw_stages_no_coprocessor_images(
        monkeypatch, tmp_path):
    wsl_calls, _py, _ = _run_create(monkeypatch, tmp_path, with_fw=False)
    signed_names = " ".join(
        " ".join(a) for _k, tool, a in wsl_calls if tool == "img4")
    for name in ich.FW_COMPONENTS:
        assert f"{name}.img4" not in signed_names


def test_op_create_with_fw_requires_every_coprocessor(monkeypatch, tmp_path):
    """A manifest without SIO must fail loudly rather than boot a chain that
    hangs at AppleA7IOPNub."""
    with pytest.raises(RamdiskError, match="missing SIO"):
        _run_create(monkeypatch, tmp_path, fw_omit=("SIO",))


def test_op_create_tolerates_a_missing_pmp_on_a12(monkeypatch, tmp_path):
    """PMP is A13-only firmware; its absence must not fail an A12 build."""
    wsl_calls, _py, _ = _run_create(monkeypatch, tmp_path)
    signed_names = " ".join(
        " ".join(a) for _k, tool, a in wsl_calls if tool == "img4")
    assert "PMP.img4" not in signed_names


def test_op_create_prepared_trustcache_needs_a_file(monkeypatch, tmp_path):
    with pytest.raises(RamdiskError, match="no trustcache file was chosen"):
        _run_create(monkeypatch, tmp_path, use_prepared_trustcache=False)


def test_op_create_stock_trustcache_mode_extracts_from_the_ipsw(
        monkeypatch, tmp_path):
    wsl_calls, _py, _ = _run_create(monkeypatch, tmp_path,
                                    trustcache_mode="stock",
                                    kernel_mode="stock")
    pairs = []
    for _k, tool, a in wsl_calls:
        if tool != "img4" or "-i" not in a or "-o" not in a:
            continue
        pairs.append((a[a.index("-i") + 1], a[a.index("-o") + 1]))
    assert any(src.endswith(".trustcache") and out.endswith("trustcache.bin")
               for src, out in pairs)


# -----------------------------------------------------------------------------
# Post-boot helpers
# -----------------------------------------------------------------------------

def test_op_mount_prefers_mount_ich(monkeypatch):
    calls = []
    monkeypatch.setattr(ram, "start_iproxy", lambda log_cb: None)
    monkeypatch.setattr(ram, "stop_iproxy", lambda: None)
    monkeypatch.setattr(
        ram, "ssh_exec",
        lambda cmd, timeout=30: (0, "/usr/bin/mount_ich\n") if "command -v" in cmd
        else (0, calls.append(cmd) or ""))
    ich.op_mount(lambda p, step="", detail="": None, lambda m: None,
                 lambda: False)
    assert calls == ["/usr/bin/mount_ich"]


def test_op_mount_falls_back_to_the_shell_script(monkeypatch):
    calls = []
    monkeypatch.setattr(ram, "start_iproxy", lambda log_cb: None)
    monkeypatch.setattr(ram, "stop_iproxy", lambda: None)
    monkeypatch.setattr(
        ram, "ssh_exec",
        lambda cmd, timeout=30: (0, "/usr/bin/mount_filesystems\n")
        if "command -v" in cmd else (0, calls.append(cmd) or ""))
    ich.op_mount(lambda p, step="", detail="": None, lambda m: None,
                 lambda: False)
    assert calls == ["/usr/bin/mount_filesystems"]


def test_op_mount_reports_a_payload_without_either_helper(monkeypatch):
    monkeypatch.setattr(ram, "start_iproxy", lambda log_cb: None)
    monkeypatch.setattr(ram, "stop_iproxy", lambda: None)
    monkeypatch.setattr(ram, "ssh_exec", lambda cmd, timeout=30: (1, ""))
    with pytest.raises(RamdiskError, match="does not carry them"):
        ich.op_mount(lambda p, step="", detail="": None, lambda m: None,
                     lambda: False)


def test_op_mount_stops_iproxy_even_on_failure(monkeypatch):
    stopped = []
    monkeypatch.setattr(ram, "start_iproxy", lambda log_cb: None)
    monkeypatch.setattr(ram, "stop_iproxy", lambda: stopped.append(True))
    monkeypatch.setattr(
        ram, "ssh_exec",
        lambda cmd, timeout=30: (_ for _ in ()).throw(
            RamdiskError("iproxy died")))
    with pytest.raises(RamdiskError):
        ich.op_mount(lambda p, step="", detail="": None, lambda m: None,
                     lambda: False)
    assert stopped == [True]
