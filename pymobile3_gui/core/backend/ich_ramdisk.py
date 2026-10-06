"""
Pymobile3-GUI — A12/A13 SSH Ramdisk Manager (EXPERIMENTAL)

Behavioural port of the `A12-A13-Ramdisk` (ICHA12A13) toolkit: an SSH ramdisk
for Apple A12 / A13 devices that have been put into *pwned DFU* with
[usbliter8](https://github.com/prdgmshift/usbliter8) rather than checkm8.

Two steps of that toolkit are macOS-only and are therefore NOT implemented
here. Both fail closed with an explicit, actionable message rather than
producing something that looks like a success:

  * **Growing and injecting the ramdisk.** An A12+ RestoreRamDisk is an APFS
    container, and the toolkit does that with `hdiutil attach` /
    `diskutil apfs resizeContainer` / `hdiutil create -srcfolder`. There is no
    Windows or WSL equivalent that can write into an APFS volume: Ubuntu's
    `apfsprogs` ships `mkapfs` / `apfsck` / `apfs-snap` only (no srcfolder
    import), `apfs-fuse` is read-only, and `libfsapfs-utils` does not add file
    injection. So this tab takes an **already-expanded, SSH-injected ramdisk
    image** prepared once with the upstream toolkit on a Mac.
  * **The usbliter8 pwn / handoff.** `usbliter8_boot` is a Mach-O binary and
    usbliter8 has no Windows host build, so the DFU -> Recovery jump cannot be
    driven from here. The device has to be handed off first (with the upstream
    toolkit, on an RP2350), and this tab picks the chain up from Recovery.

Everything else is implemented and does run on Windows, using the two existing
execution paths: `wsl_tool`-style Linux tools for the offline build work and
the vendored native `irecovery.exe` for the USB side.

The toolkit's `patch/*.py` patchers are executed **in place** from a
user-supplied toolkit folder. They are deliberately not vendored into this
tree: the upstream project ships no LICENSE file and no license headers, and
this project is MIT (see `docs/REFERENCES.md`). Pointing at a checkout is not
a derivative work; copying it in would be.

EXPERIMENTAL. Unverified on hardware from this codebase — see the tab banner.
"""

import os
import plistlib
import shutil
import time
from typing import Callable, Optional

from pymobile3_gui.core.backend import ramdisk_manager as ram
from pymobile3_gui.core.backend.paths import data_dir
from pymobile3_gui.core.backend.ramdisk_manager import (
    RamdiskError, wsl_tool,
)

LogCb = Callable[[str], None]
ProgressCb = Callable[..., None]
CancelCb = Callable[[], bool]

# The two chips the upstream toolkit targets: A12 Bionic and A13 Bionic.
ICH_CPIDS = {"0x8020", "0x8030"}
ICH_CHIPS = {"0x8020": "A12X", "0x8030": "A13"}
ICH_PWND = "usbliter8"

# Components the toolkit always needs out of the IPSW, and the manifest keys it
# looks for. Several renamed across iOS generations, hence the candidate lists
# (verbatim from build.sh).
REQUIRED_COMPONENTS = ("iBEC", "DeviceTree", "KernelCache", "RestoreRamDisk",
                       "RestoreTrustCache")
OPTIONAL_COMPONENTS = {
    "iBSS": ("iBSS",),
    "RestoreSEP": ("RestoreSEP",),
    "SPTM": ("SPTM", "Ap,SPTM", "SecurePageTableMonitor", "RestoreSPTM"),
    "TXM": ("TXM", "Ap,TXM", "TrustedExecutionMonitor",
            "Ap,TrustedExecutionMonitor"),
    "AOP": ("AOP",),
    "ANE": ("ANE",),
    "AVE": ("AVE",),
    "ISP": ("ISP",),
    "GFX": ("GFX",),
    "SIO": ("SIO",),
    # A13 (t8030) only — absent on A12, which must not fail the build.
    "PMP": ("PMP", "Ap,PMP"),
}

# Coprocessor firmwares staged when --with-fw is on. Without them XNU commonly
# hangs at AppleA7IOPNub ("allocated nub") / disk0 "Device not configured".
FW_COMPONENTS = ("PMP", "AOP", "ANE", "AVE", "ISP", "GFX", "SIO")

KERNEL_PATCH_SETS = ("ios18", "ios17", "ios26-bytes", "ios27", "all")
TRUSTCACHE_MODES = ("prepared", "stock")

# Loaded in this order once the device is in Recovery. Mirrors boot.sh.
BOOTARGS_DEFAULT = "rd=md0 -v debug=0x14e serial=3 wdt=-1 keepsyms=1"

# irecovery command timeouts. boot.sh uses 30 s for commands and 300 s for
# uploads because a ramdisk or kernelcache is large over USB.
IRECV_CMD_TIMEOUT = 45.0
IRECV_UPLOAD_TIMEOUT = 300.0
# DFU must drop and Recovery must appear after the usbliter8 handoff. boot.sh
# allows 120 s and tells the user to replug the cable.
RECOVERY_WAIT_SECS = 120.0

CREATE_STEPS = [
    "Detect Device", "Resolve IPSW", "Fetch Firmware", "Patch Bootchain",
    "Patch Kernel", "Package Ramdisk", "Finalize",
]
BOOT_STEPS = ["Detect Device", "Handoff iBEC", "Wait for Recovery",
              "Load Bootchain", "Boot Ramdisk"]
MOUNT_STEPS = ["Connect", "Mount Filesystems"]
CLEAN_STEPS = ["Clean Workspace"]

TOOLKIT_ENV = "PMD3_ICH_TOOLKIT"

# Written out at run time rather than shipped as a file: under PyInstaller our
# own modules live inside the PYZ, and WSL needs a real path to execute.
WRAP_KERNEL_HELPER = r'''
import sys
from pathlib import Path

from pyimg4 import Compression, IMG4, IM4M, IM4P, PayloadProperty

raw_path, original_path, output_path, im4m_path = map(Path, sys.argv[1:5])

original = IM4P(original_path.read_bytes())
image = IM4P(fourcc="rkrn", description=original.description,
             payload=raw_path.read_bytes())
for prop in original.properties or []:
    image.add_property(PayloadProperty(fourcc=prop.fourcc, value=prop.value))
image.payload.compress(Compression.LZFSE)
output_path.write_bytes(
    IMG4(im4p=image, im4m=IM4M(im4m_path.read_bytes())).output())
print("wrote " + str(output_path))
'''

_DEP_ERROR = (
    "The A12/A13 patchers need two Python modules inside WSL "
    "(capstone for the kernel patchfinder, pyimg4 for image4 packaging).\n\n"
    "Install them with:\n"
    "  wsl -d {distro} -e pip3 install --break-system-packages "
    "capstone pyimg4"
)


# -----------------------------------------------------------------------------
# Locations
# -----------------------------------------------------------------------------

def ich_root() -> str:
    path = os.path.join(data_dir(), "ich")
    os.makedirs(path, exist_ok=True)
    return path


def bootchain_dir() -> str:
    path = os.path.join(ich_root(), "bootchain")
    os.makedirs(path, exist_ok=True)
    return path


def ich_work_dir() -> str:
    path = os.path.join(ich_root(), "work")
    os.makedirs(path, exist_ok=True)
    return path


def ich_cache_dir() -> str:
    path = os.path.join(ich_root(), "cache")
    os.makedirs(path, exist_ok=True)
    return path


# -----------------------------------------------------------------------------
# Toolkit location
# -----------------------------------------------------------------------------

def default_toolkit_dir() -> str:
    """Where to look for the upstream toolkit (env var, then Desktop)."""
    env = os.environ.get(TOOLKIT_ENV, "").strip()
    if env:
        return env
    userprofile = os.environ.get("USERPROFILE", "")
    if userprofile:
        return os.path.join(userprofile, "Desktop", "A12-A13-Ramdisk")
    return ""


def toolkit_patch_dir(toolkit: str) -> str:
    return os.path.join(toolkit, "patch")


def toolkit_resources_dir(toolkit: str) -> str:
    return os.path.join(toolkit, "resources")


def require_toolkit(toolkit: str) -> str:
    """
    Validate a toolkit folder and return the patch directory.

    Only the patchers are required: they are the one thing with no substitute,
    because the kernel and bootchain patching they do is the point of the
    flow. Resources (IM4M tickets, ssh payload) are optional here since the
    ramdisk is supplied pre-injected.
    """
    root = (toolkit or "").strip()
    if not root:
        raise RamdiskError(
            "No toolkit folder set. Point it at an A12-A13-Ramdisk checkout "
            "(the folder holding patch/ and resources/).")
    if not os.path.isdir(root):
        raise RamdiskError(f"Toolkit folder not found: {root}")
    patch = toolkit_patch_dir(root)
    if not os.path.isfile(os.path.join(patch, "iboot_patchfinder.py")):
        raise RamdiskError(
            f"{patch} does not look like a toolkit patch directory "
            "(iboot_patchfinder.py missing).")
    return patch


def im4m_path(toolkit: str, cpid: str) -> str:
    """Per-device APTicket. Optional: the tab can run with a prepared ticket."""
    return os.path.join(toolkit_resources_dir(toolkit), f"IM4M_{cpid}")


# -----------------------------------------------------------------------------
# Device gating
# -----------------------------------------------------------------------------

def is_ich_device(dev: Optional[dict]) -> bool:
    return bool(dev) and dev.get("cpid") in ICH_CPIDS


def is_ich_pwned(dev: Optional[dict]) -> bool:
    """Pwned-DFU state as usbliter8 reports it (`PWND: usbliter8`)."""
    return bool(dev) and str(dev.get("pwnd", "")).strip().lower() == ICH_PWND


def wait_for_ich_device(log_cb: LogCb, is_cancelled_cb: CancelCb) -> dict:
    """Poll `irecovery -q` until an A12/A13 device shows up in any mode."""
    announced = False
    while True:
        ram._check_cancel(is_cancelled_cb)
        dev = ram.detect_device()
        if dev and dev["cpid"] in ICH_CPIDS:
            return dev
        if dev:
            raise RamdiskError(
                f"Device CPID {dev['cpid']} is not an A12/A13 target "
                "(0x8020 / 0x8030). Use the SSH Ramdisk tab for A7-A11 / T2.")
        if not announced:
            log_cb("[*] Waiting for an A12/A13 device in DFU or Recovery")
            announced = True
        time.sleep(1.0)


def wait_for_recovery(log_cb: LogCb, is_cancelled_cb: CancelCb,
                      timeout: float = RECOVERY_WAIT_SECS) -> dict:
    """
    Wait for the device to leave DFU and answer as Recovery.

    The usbliter8 handoff drops DFU and iBoot re-enumerates as Recovery over
    normal USB. DCSD/serial often still shows iBoot while host USB Recovery has
    not come back, which reads as "stuck after iBoot sent" upstream, so the
    wait is bounded and says what to do.
    """
    started = time.monotonic()
    deadline = started + timeout
    last_mode = ""
    prompted = False
    while time.monotonic() < deadline:
        ram._check_cancel(is_cancelled_cb)
        dev = ram.detect_device()
        mode = (dev or {}).get("mode", "")
        if mode != last_mode:
            log_cb(f"[*] USB MODE: {mode or 'none'}")
            last_mode = mode
        if mode == "Recovery":
            rc, _ = ram.run_capture([ram.win_tool("irecovery"), "-q"], timeout=10)
            if rc == 0:
                log_cb("[*] iBoot Recovery is ready over USB.")
                return dev
        if not prompted and time.monotonic() - started > 25:
            log_cb("[*] USB Recovery has not appeared yet — unplug the "
                   "cable, wait 2 s, plug it back into the same port and "
                   "leave the device alone. Still waiting.")
            prompted = True
        time.sleep(1.0)
    raise RamdiskError(
        "Timed out waiting for Recovery after the iBoot handoff. On a normal "
        "cable this usually means USB never re-enumerated: try a USB-A to "
        "Lightning cable, or re-run the usbliter8 handoff and this boot.")


# -----------------------------------------------------------------------------
# WSL python (the toolkit's own patchers)
# -----------------------------------------------------------------------------

def _wsl_distro_name() -> str:
    return ram.DEFAULT_WSL_DISTRO if not ram._wsl_distro else ram._wsl_distro


def wsl_python(
    script: str, args: list[str], *, log_cb: LogCb, is_cancelled_cb: CancelCb,
    allow_failure: bool = False, context: str = "", timeout: Optional[float] = None,
) -> int:
    """
    Run a Python script with WSL's interpreter.

    Paths are translated for argv, not just cwd: WSL rewrites the working
    directory but hands the argument vector through untouched, so a raw
    C:\\... path would reach the script as a relative filename.
    """
    if not ram.wsl_available():
        raise RamdiskError(
            "WSL (Ubuntu) is required for the A12/A13 build steps. "
            "Install it with: wsl --install")
    cmd = ["wsl.exe", "-d", _wsl_distro_name(), "-e", "python3",
           ram.win_to_wsl(script)]
    cmd += [ram.wsl_arg(a) for a in args]
    return ram.run_streaming(
        cmd, cwd=ich_root(), log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
        allow_failure=allow_failure,
        context=context or os.path.basename(script), timeout=timeout)


def python_deps_ok() -> tuple[bool, str]:
    """Check the two WSL-side modules the patchers import."""
    if not ram.wsl_available():
        return False, "WSL is not available"
    rc, out = ram.run_capture(
        ["wsl.exe", "-d", _wsl_distro_name(), "-e", "python3", "-c",
         "import capstone, pyimg4"], timeout=60)
    if rc == 0:
        return True, "capstone + pyimg4 available"
    return False, _DEP_ERROR.format(distro=_wsl_distro_name())


def _write_helper(name: str, source: str) -> str:
    """Materialise a helper script on disk so WSL can execute it."""
    path = os.path.join(ich_root(), name)
    if not os.path.isfile(path) or open(path, encoding="utf-8").read() != source:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(source)
    return path


def wrap_kernel(raw: str, original: str, output: str, ticket: str, *,
                log_cb: LogCb, is_cancelled_cb: CancelCb) -> None:
    """
    Re-wrap a (possibly patched) raw kernel as a signed `rkrn` IMG4.

    A patched kernel has to be LZFSE-compressed again and lose nothing from the
    stock IM4P's payload properties, which the bundled img4 cannot express, so
    this goes through pyimg4 the same way the toolkit does.
    """
    helper = _write_helper("ich_wrap_kernel.py", WRAP_KERNEL_HELPER)
    wsl_python(helper, [raw, original, output, ticket],
               log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
               context="wrap kernel (pyimg4)", timeout=300)
    if not os.path.isfile(output) or os.path.getsize(output) == 0:
        raise RamdiskError(f"kernel wrapping produced no {os.path.basename(output)}")


# -----------------------------------------------------------------------------
# BuildManifest
# -----------------------------------------------------------------------------

def resolve_components(manifest_bytes: bytes, model: str) -> dict:
    """
    Map component name -> IPSW member path for one board.

    build.sh picks the BuildIdentity whose `Info.DeviceClass` equals the board
    reported by irecovery, then reads `Manifest.<key>.Info.Path`. The optional
    components are resolved against their candidate key lists and omitted when
    the IPSW does not ship them.
    """
    try:
        data = plistlib.loads(manifest_bytes)
        identities = data["BuildIdentities"]
    except (plistlib.InvalidFileException, KeyError, TypeError) as e:
        raise RamdiskError(f"Cannot read BuildManifest.plist: {e}")

    identity = None
    for item in identities:
        if item.get("Info", {}).get("DeviceClass") == model:
            identity = item
            break
    if identity is None:
        if len(identities) != 1:
            raise RamdiskError(
                f"BuildManifest has no identity for board '{model}'.")
        identity = identities[0]

    images = identity.get("Manifest", {})

    def path_for(keys) -> Optional[str]:
        for key in keys:
            path = images.get(key, {}).get("Info", {}).get("Path")
            if path:
                return path
        return None

    out = {"build": identity.get("Info", {}).get("BuildNumber", "")}
    for name in REQUIRED_COMPONENTS:
        path = path_for((name,))
        if not path:
            raise RamdiskError(
                f"BuildManifest identity '{model}' has no {name} path.")
        out[name] = path
    for name, candidates in OPTIONAL_COMPONENTS.items():
        path = path_for(candidates)
        if path:
            out[name] = path
    return out


def resolve_kpf_set(version: str, has_txm: bool) -> str:
    """
    Auto kernel-patch set, mirroring build.sh's resolve_kpf_set().

    TXM firmware (iOS 27-class) takes the TXM-aware path; everything from iOS
    17 up uses the AMFI + PE_i_can_has_debugger finder. The legacy iOS 26
    byte-offset table is never auto-selected — it does not match j210/23F84
    and the toolkit fails closed on it rather than guessing.
    """
    try:
        major = int(version.split(".")[0])
    except (ValueError, IndexError):
        return "ios18"
    if has_txm or major >= 27:
        return "ios27"
    return "ios18"


def _fetch_member(member: str, ipsw_url: str, product: str, build: str,
                  log_cb: LogCb, is_cancelled_cb: CancelCb) -> str:
    """
    Download one IPSW member, reusing the on-disk copy when it is there.

    This flow pulls far more than the checkm8 one — RestoreRamDisk, kernelcache,
    SPTM/TXM and six or seven coprocessor firmwares, well over a gigabyte — and
    switching kernel mode or patch set must not pay for it twice. Keyed by
    product and build so a different iOS version never reuses the wrong file.
    """
    cache = os.path.join(ich_cache_dir(), f"{product}-{build}")
    target = os.path.join(cache, os.path.basename(member))
    if os.path.isfile(target) and os.path.getsize(target) > 0:
        log_cb(f"[cache] {os.path.basename(member)}")
        return target
    os.makedirs(cache, exist_ok=True)
    ram._pzb_fetch(member, ipsw_url, cwd=cache, log_cb=log_cb,
                   is_cancelled_cb=is_cancelled_cb)
    return target


# -----------------------------------------------------------------------------
# Native irecovery
# -----------------------------------------------------------------------------

def _irecv(args: list[str], *, log_cb: LogCb, is_cancelled_cb: CancelCb,
           allow_failure: bool = False, context: str = "irecovery") -> int:
    timeout = IRECV_UPLOAD_TIMEOUT if args[:1] == ["-f"] else IRECV_CMD_TIMEOUT
    return ram.run_streaming(
        [ram.win_tool("irecovery"), *args], cwd=ich_root(), log_cb=log_cb,
        is_cancelled_cb=is_cancelled_cb, allow_failure=allow_failure,
        context=context, timeout=timeout)


def _bc(name: str) -> str:
    """Absolute path to a staged bootchain artifact (irecovery cwd is ich_root)."""
    return os.path.join("bootchain", name)


def _irecv_upload(name: str, log_cb: LogCb, is_cancelled_cb: CancelCb) -> None:
    path = _bc(name)
    if not os.path.isfile(os.path.join(ich_root(), path)):
        raise RamdiskError(
            f"bootchain is missing {name} — build it again with the same options.")
    _irecv(["-f", path], log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
           context=f"irecovery -f {name}")


def _irecv_cmd(command: str, log_cb: LogCb, is_cancelled_cb: CancelCb,
               *, required: bool = True) -> bool:
    """Send one iBoot command. Returns True only on a clean exit code.

    The callers chain a fallback onto this (`setenvnp` -> `setenv`,
    `setpicture 1` -> `setpicture`), so it has to report success as a boolean
    rather than passing the raw exit code through — `not 0` is True, which
    would take the fallback even on a command that worked.
    """
    rc = _irecv(["-c", command], log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                allow_failure=not required, context=f"irecovery -c {command}")
    return rc == 0


# -----------------------------------------------------------------------------
# Create
# -----------------------------------------------------------------------------

def op_create(
    version: str, toolkit: str, prepared_ramdisk: str, *,
    prepared_trustcache: str = "", trustcache_mode: str = "prepared",
    kernel_mode: str = "patched", kpf_set: str = "auto",
    with_fw: bool = True, use_ibss: bool = False, use_logo: bool = True,
    use_sep: bool = True,
    progress_cb: ProgressCb, log_cb: LogCb, is_cancelled_cb: CancelCb,
) -> None:
    """
    Build a signed A12/A13 bootchain into `bootchain/`.

    The two macOS-only steps are not attempted: the ramdisk and (by default)
    the trustcache come from files prepared with the upstream toolkit, and the
    usbliter8 handoff belongs to `op_boot`, which needs an already-handed-off
    device.
    """
    patch_dir = require_toolkit(toolkit)
    root = ich_root()

    progress_cb(0, step="Detect Device", detail="Waiting for an A12/A13 device...")
    if not ram.wsl_available():
        raise RamdiskError(
            "WSL (Ubuntu) is required to build a bootchain. "
            "Install it with: wsl --install")
    dev = wait_for_ich_device(log_cb, is_cancelled_cb)
    cpid, model, product = dev["cpid"], dev["model"], dev["product"]
    chip = ICH_CHIPS.get(cpid, cpid)
    log_cb(f"[*] Device: {product} board={model} CPID={cpid} ({chip})")

    ticket = _resolve_ticket(toolkit, cpid, log_cb)
    ramdisk_src = _require_prepared(prepared_ramdisk, "prepared ramdisk image")

    progress_cb(8, step="Resolve IPSW", detail=f"iOS {version} for {product}")
    ipsw_url = ram.resolve_ipsw_url(product, version)
    build = ram.build_number_from_ipsw_url(ipsw_url)
    log_cb(f"[*] IPSW: {ipsw_url}")

    work = ich_work_dir()
    ram._fresh_dir(work)

    progress_cb(14, step="Fetch Firmware", detail="BuildManifest...")
    ram._pzb_fetch("BuildManifest.plist", ipsw_url, cwd=work, log_cb=log_cb,
                   is_cancelled_cb=is_cancelled_cb)
    with open(os.path.join(work, "BuildManifest.plist"), "rb") as fh:
        manifest_bytes = fh.read()
    comp = resolve_components(manifest_bytes, model)
    manifest_build = comp.get("build") or ""
    if manifest_build and manifest_build != build:
        raise RamdiskError(
            f"BuildManifest build {manifest_build} does not match the "
            f"selected build {build}.")
    has_txm = "TXM" in comp
    if kpf_set == "auto":
        kpf_set = resolve_kpf_set(version, has_txm)
        log_cb(f"[*] kpf-set auto -> {kpf_set} (iOS {version}, TXM={has_txm})")

    wanted = ["BuildManifest.plist"]
    for name in REQUIRED_COMPONENTS:
        wanted.append(comp[name])
    if use_ibss:
        if "iBSS" not in comp:
            raise RamdiskError("--use-ibss was requested but this IPSW has no iBSS.")
        wanted.append(comp["iBSS"])
    for name in ("SPTM", "TXM", "RestoreSEP"):
        if name in comp:
            wanted.append(comp[name])
    if with_fw:
        for name in FW_COMPONENTS:
            # PMP only exists on A13, so a missing one is not a build failure;
            # any other absent coprocessor firmware means the device can hang
            # at AppleA7IOPNub, which is worth refusing over.
            if name not in comp:
                if name == "PMP":
                    continue
                raise RamdiskError(
                    f"BuildManifest is missing {name}, which the USB firmware "
                    "option needs. Turn that option off if you accept a device "
                    "that may hang after iBoot.")
            wanted.append(comp[name])

    total = len(wanted) - 1
    fetched = {}
    for n, member in enumerate(wanted[1:], start=1):
        ram._check_cancel(is_cancelled_cb)
        progress_cb(14 + int(26 * n / total), step="Fetch Firmware",
                    detail=f"{n}/{total} parts")
        for name, path in comp.items():
            if path == member:
                fetched[name] = _fetch_member(member, ipsw_url, product, build,
                                              log_cb, is_cancelled_cb)
                break
    ram._check_cancel(is_cancelled_cb)

    # ── Patch Bootchain ─────────────────────────────────────────────────────
    progress_cb(44, step="Patch Bootchain", detail="Decrypting iBSS / iBEC...")
    for name in ("iBSS", "iBEC"):
        if name not in fetched:
            continue
        src = fetched[name]
        wsl_tool("img4", ["-i", src, "-o", os.path.join("work", f"{name}.raw")],
                 cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                 context=f"img4 ({name})")

    bc = bootchain_dir()
    ram._fresh_dir(bc)
    out = os.path.join(root, "out")
    ram._fresh_dir(out)

    if use_ibss:
        wsl_python(os.path.join(patch_dir, "iboot_patchfinder.py"),
                   [os.path.join(work, "iBSS.raw"),
                    os.path.join(out, "iBSS.patched.raw"), "--mode", "ibss"],
                   log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                   context="iboot_patchfinder (iBSS)", timeout=900)
        rc = wsl_python(
            os.path.join(patch_dir, "finalize_iboot.py"),
            ["--stock", os.path.join(work, "iBSS.raw"),
             "--input", os.path.join(out, "iBSS.patched.raw"),
             "--output", _bc("iBSS.patched.bin"), "--board", model],
            log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
            allow_failure=True, context="finalize_iboot (iBSS)", timeout=300)
        if rc != 0:
            log_cb("[*] finalize_iboot had no iBSS slots to patch — using the "
                   "raw patched iBoot.")
            shutil.copyfile(os.path.join(out, "iBSS.patched.raw"),
                            os.path.join(bc, "iBSS.patched.bin"))
        with open(os.path.join(bc, "use-ibss"), "w", encoding="utf-8") as fh:
            fh.write("1\n")

    wsl_python(os.path.join(patch_dir, "iboot_patchfinder.py"),
               [os.path.join(work, "iBEC.raw"),
                os.path.join(out, "iBEC.patched.raw"), "--mode", "ibec"],
               log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
               context="iboot_patchfinder (iBEC)", timeout=900)
    wsl_python(os.path.join(patch_dir, "finalize_iboot.py"),
               ["--stock", os.path.join(work, "iBEC.raw"),
                "--input", os.path.join(out, "iBEC.patched.raw"),
                "--output", os.path.join(out, "iBoot.patched.bin"),
                "--board", model],
               log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
               context="finalize_iboot (iBEC)", timeout=300)
    shutil.copyfile(os.path.join(out, "iBoot.patched.bin"),
                    os.path.join(bc, "iBoot.patched.bin"))

    if use_ibss:
        # Typed IMG4 for the Recovery-stage iBSS -> iBEC handoff.
        wsl_tool("img4",
                 ["-i", os.path.join(bc, "iBoot.patched.bin"),
                  "-o", _bc("iBEC.patched.img4"), "-A", "-T", "ibec",
                  "-M", ticket],
                 cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                 context="img4 sign (patched iBEC)")

    for name, fourcc in (("SPTM", "sptm"), ("TXM", "trst")):
        if name not in fetched:
            continue
        wsl_tool("img4", ["-i", fetched[name],
                          "-o", os.path.join(work, f"{name}.raw")],
                 cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                 context=f"img4 ({name})")
        wsl_python(os.path.join(patch_dir, f"{name.lower()}_patchfinder.py"),
                   [os.path.join(work, f"{name}.raw"),
                    os.path.join(out, f"{name}.patched.raw")],
                   log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                   context=f"{name} patchfinder", timeout=900)
        args = ["-i", os.path.join(out, f"{name}.patched.raw"),
                "-o", _bc(f"{name.lower()}.img4"), "-A", "-T", fourcc,
                "-M", ticket]
        if name == "TXM":
            # Some iBoot trees only accept the untagged variant, so retry the
            # same wrap without -T before giving up.
            rc = wsl_tool("img4", args, cwd=root, log_cb=log_cb,
                          is_cancelled_cb=is_cancelled_cb, allow_failure=True,
                          context="img4 sign (TXM)")
            if rc != 0:
                wsl_tool("img4", ["-i", os.path.join(out, "TXM.patched.raw"),
                                  "-o", _bc("txm.img4"), "-A", "-M", ticket],
                         cwd=root, log_cb=log_cb,
                         is_cancelled_cb=is_cancelled_cb,
                         context="img4 sign (TXM, untagged)")
        else:
            wsl_tool("img4", args, cwd=root, log_cb=log_cb,
                     is_cancelled_cb=is_cancelled_cb,
                     context=f"img4 sign ({name})")
    progress_cb(56, step="Patch Bootchain", detail="Bootchain patched.")

    # ── Patch Kernel ─────────────────────────────────────────────────────────
    progress_cb(60, step="Patch Kernel", detail="Extracting kernelcache...")
    kc_raw = os.path.join(work, "kernelcache.raw")
    wsl_tool("img4", ["-i", fetched["KernelCache"], "-o", kc_raw],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="img4 (kernelcache)")

    if kernel_mode == "patched":
        progress_cb(66, step="Patch Kernel",
                    detail=f"patchfinder ({kpf_set})...")
        wsl_python(os.path.join(patch_dir, "apply_kernel_patches.py"),
                   [kc_raw, "--output", os.path.join(out, "kernelcache.patched.raw"),
                    "--kpf-set", kpf_set, "--allow-missing"],
                   log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                   context="apply_kernel_patches", timeout=1800)
        kernel_raw = os.path.join(out, "kernelcache.patched.raw")
    else:
        kernel_raw = kc_raw

    wrap_kernel(kernel_raw, fetched["KernelCache"],
                os.path.join(bc, "kernelcache.img4"), ticket,
                log_cb=log_cb, is_cancelled_cb=is_cancelled_cb)
    with open(os.path.join(bc, "kernel.mode"), "w", encoding="utf-8") as fh:
        fh.write(kernel_mode + "\n")
    with open(os.path.join(bc, "kpf.set"), "w", encoding="utf-8") as fh:
        fh.write(kpf_set + "\n")
    progress_cb(76, step="Patch Kernel", detail="Kernel packaged & signed.")

    # ── Package Ramdisk ──────────────────────────────────────────────────────
    progress_cb(80, step="Package Ramdisk",
                detail="Signing the prepared ramdisk...")
    wsl_tool("img4", ["-i", ramdisk_src, "-o", _bc("ramdisk.img4"),
                      "-A", "-T", "rdsk", "-M", ticket],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="img4 sign (ramdisk)", timeout=600)

    if trustcache_mode == "prepared":
        if not prepared_trustcache.strip():
            raise RamdiskError(
                "Trustcache mode is 'prepared' but no trustcache file was "
                "chosen. Pick the trustcache.bin produced by the upstream "
                "toolkit, or switch the mode to 'stock'.")
        tc_bin = os.path.abspath(prepared_trustcache.strip())
        if not os.path.isfile(tc_bin) or os.path.getsize(tc_bin) == 0:
            raise RamdiskError(f"Prepared trustcache not found: {tc_bin}")
        log_cb(f"[*] Trustcache: prepared {os.path.basename(tc_bin)}")
    else:
        progress_cb(84, step="Package Ramdisk", detail="Extracting trustcache...")
        tc_bin = os.path.join(work, "trustcache.bin")
        wsl_tool("img4", ["-i", fetched["RestoreTrustCache"], "-o", tc_bin],
                 cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                 context="img4 (trustcache)")
        log_cb("[!] Stock trustcache used: the SSH binaries injected into the "
               "prepared ramdisk are not in it, so the ramdisk may refuse to "
               "run them. Prepare a trustcache with the upstream toolkit and "
               "switch the mode to 'prepared' if it does.")

    wsl_tool("img4", ["-i", tc_bin, "-o", _bc("trustcache.img4"),
                      "-A", "-T", "rtsc", "-M", ticket],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="img4 sign (trustcache)")
    progress_cb(90, step="Package Ramdisk", detail="Ramdisk + trustcache ready.")

    # ── Finalize ─────────────────────────────────────────────────────────────
    wsl_tool("img4", ["-i", fetched["DeviceTree"], "-o", _bc("devicetree.img4"),
                      "-T", "rdtr", "-M", ticket],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="img4 sign (devicetree)")

    if with_fw:
        for name in FW_COMPONENTS:
            if name not in fetched:
                continue
            wsl_tool("img4", ["-i", fetched[name], "-o", _bc(f"{name}.img4"),
                              "-M", ticket],
                     cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                     context=f"img4 sign ({name})")
        with open(os.path.join(bc, "with-fw.enabled"), "w",
                  encoding="utf-8") as fh:
            fh.write("1\n")

    if use_sep and "RestoreSEP" in fetched:
        wsl_tool("img4", ["-i", fetched["RestoreSEP"],
                          "-o", _bc("sep-firmware.img4"), "-M", ticket],
                 cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                 context="img4 sign (RestoreSEP)")

    if use_logo:
        wsl_tool("img4", ["-i", ram.bootlogo_path(), "-o", _bc("logo.img4"),
                          "-A", "-T", "rlgo", "-M", ticket],
                 cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                 context="img4 sign (logo)")

    with open(os.path.join(bc, "chain.info"), "w", encoding="utf-8") as fh:
        fh.write(
            f"product={product}\nmodel={model}\ncpid={cpid}\nchip={chip}\n"
            f"version={version}\nbuild={build}\nibss={int(use_ibss)}\n"
            f"sptm={int('SPTM' in fetched)}\ntxm={int('TXM' in fetched)}\n"
            f"kernel={kernel_mode}\nkpf_set={kpf_set}\n"
            f"with_fw={int(with_fw)}\ntrustcache={trustcache_mode}\n"
            f"packaging=img4-with-im4m\nsource=prepared-ramdisk\n")

    shutil.rmtree(os.path.join(root, "work"), ignore_errors=True)
    shutil.rmtree(out, ignore_errors=True)
    log_cb("[*] Bootchain staged. Hand the device off with usbliter8, then "
           "use Boot Bootchain.")
    progress_cb(100, step="Finalize", detail="Bootchain ready.")


def _resolve_ticket(toolkit: str, cpid: str, log_cb: LogCb) -> str:
    """
    Locate the APTicket used to sign every image in the chain.

    The toolkit keeps one ticket per chip (`resources/IM4M_<cpid>`); those are
    not the device's own ticket, they are what makes the payload loadable by a
    pwned device, so the wrong one fails at boot rather than at build time.
    """
    candidate = im4m_path(toolkit, cpid)
    if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
        log_cb(f"[*] Ticket: {os.path.basename(candidate)}")
        return candidate
    raise RamdiskError(
        f"No APTicket for CPID {cpid}: expected {candidate}\n\n"
        "Copy the toolkit's resources/IM4M_<cpid> into that path, or point "
        "the toolkit folder at a checkout that has it.")


def _require_prepared(path: str, label: str) -> str:
    raw = (path or "").strip()
    if not raw:
        raise RamdiskError(f"No {label} selected.")
    resolved = os.path.abspath(raw)
    if not os.path.isfile(resolved) or os.path.getsize(resolved) == 0:
        raise RamdiskError(f"{label.capitalize()} not found: {resolved}")
    return resolved


# -----------------------------------------------------------------------------
# Boot
# -----------------------------------------------------------------------------

def op_boot(progress_cb: ProgressCb, log_cb: LogCb,
            is_cancelled_cb: CancelCb) -> None:
    """
    Load a staged bootchain onto a device that is already in Recovery.

    The DFU -> Recovery jump is `usbliter8_boot`, a macOS binary with no
    Windows build, so this starts where the handoff ends. Feeding a chain into
    a device that is still in pwned DFU would silently do nothing, so that is
    refused with an explanation rather than attempted.
    """
    require_bootchain()
    progress_cb(0, step="Detect Device", detail="Waiting for an A12/A13 device...")
    dev = wait_for_ich_device(log_cb, is_cancelled_cb)
    mode = dev.get("mode", "")
    log_cb(f"[*] Device: {dev.get('product', '')} board={dev.get('model', '')} "
           f"CPID={dev['cpid']} mode={mode or 'unknown'}")

    if mode == "DFU":
        raise RamdiskError(
            "The device is still in pwned DFU. Jumping it into Recovery needs "
            "usbliter8 (RP2350 hardware) and there is no Windows host build "
            "of it, so that step has to be done with the upstream toolkit. Run "
            "its handoff, wait for the device to reappear as Recovery, then "
            "run this again.")
    if mode != "Recovery":
        raise RamdiskError(
            f"Expected the device in Recovery, it reports MODE={mode or 'none'}. "
            "Complete the usbliter8 handoff first.")

    use_ibss = os.path.isfile(os.path.join(bootchain_dir(), "use-ibss"))
    with_fw = os.path.isfile(os.path.join(bootchain_dir(), "with-fw.enabled"))

    progress_cb(20, step="Handoff iBEC", detail="iBSS -> iBEC")
    if use_ibss:
        _irecv_upload("iBSS.patched.bin", log_cb, is_cancelled_cb)
        ram._sleep(4, is_cancelled_cb)
        _irecv_upload("iBEC.patched.img4", log_cb, is_cancelled_cb)
        _irecv_cmd("go", log_cb, is_cancelled_cb, required=False)
        ram._sleep(3, is_cancelled_cb)
        progress_cb(40, step="Wait for Recovery", detail="Polling USB...")
        wait_for_recovery(log_cb, is_cancelled_cb)

    progress_cb(55, step="Load Bootchain", detail="Display...")
    # Black background matches the fullscreen logo canvas (no white corners).
    _irecv_cmd("bgcolor 0 0 0", log_cb, is_cancelled_cb, required=False)
    ram._sleep(1, is_cancelled_cb)
    if os.path.isfile(os.path.join(bootchain_dir(), "logo.img4")):
        _irecv_upload("logo.img4", log_cb, is_cancelled_cb)
        if not _irecv_cmd("setpicture 1", log_cb, is_cancelled_cb,
                          required=False):
            _irecv_cmd("setpicture", log_cb, is_cancelled_cb, required=False)
        ram._sleep(3, is_cancelled_cb)

    for name in ("sptm", "txm"):
        if os.path.isfile(os.path.join(bootchain_dir(), f"{name}.img4")):
            log_cb(f"[*] Loading patched {name.upper()}")
            _irecv_upload(f"{name}.img4", log_cb, is_cancelled_cb)
            _irecv_cmd("firmware", log_cb, is_cancelled_cb, required=False)

    if os.path.isfile(os.path.join(bootchain_dir(), "sep-firmware.img4")):
        log_cb("[*] Loading RestoreSEP (rsepfirmware)")
        _irecv_upload("sep-firmware.img4", log_cb, is_cancelled_cb)
        # rsepfirmware, not sepfirmware: AppleSEPManager needs the DT property.
        _irecv_cmd("rsepfirmware", log_cb, is_cancelled_cb, required=False)

    if with_fw and not use_ibss:
        for name in FW_COMPONENTS:
            if os.path.isfile(os.path.join(bootchain_dir(), f"{name}.img4")):
                log_cb(f"[*] Loading {name}")
                _irecv_upload(f"{name}.img4", log_cb, is_cancelled_cb)
                _irecv_cmd("firmware", log_cb, is_cancelled_cb, required=False)

    progress_cb(75, step="Load Bootchain", detail="DeviceTree / trustcache")
    _irecv_upload("devicetree.img4", log_cb, is_cancelled_cb)
    _irecv_cmd("devicetree", log_cb, is_cancelled_cb)
    _irecv_upload("trustcache.img4", log_cb, is_cancelled_cb)
    _irecv_cmd("firmware", log_cb, is_cancelled_cb)
    _irecv_upload("ramdisk.img4", log_cb, is_cancelled_cb)
    ram._sleep(2, is_cancelled_cb)
    _irecv_cmd("ramdisk", log_cb, is_cancelled_cb)

    if with_fw and use_ibss:
        for name in FW_COMPONENTS:
            if os.path.isfile(os.path.join(bootchain_dir(), f"{name}.img4")):
                log_cb(f"[*] Loading {name}")
                _irecv_upload(f"{name}.img4", log_cb, is_cancelled_cb)
                _irecv_cmd("firmware", log_cb, is_cancelled_cb, required=False)

    progress_cb(90, step="Boot Ramdisk", detail="kernelcache bootx")
    _irecv_upload("kernelcache.img4", log_cb, is_cancelled_cb)
    # setenvnp immediately before bootx is what puts verbose text on the
    # screen; boot-args baked into iBoot alone were not enough upstream.
    if not _irecv_cmd(f"setenvnp boot-args {BOOTARGS_DEFAULT}", log_cb,
                      is_cancelled_cb, required=False):
        _irecv_cmd(f"setenv boot-args {BOOTARGS_DEFAULT}", log_cb,
                   is_cancelled_cb, required=False)
    _irecv_cmd("bootx", log_cb, is_cancelled_cb)
    log_cb("[*] Verbose boot text should appear on the device. When SSH is "
           "up, run mount_ich to mount every filesystem.")
    progress_cb(100, step="Boot Ramdisk", detail="bootx sent.")


def require_bootchain() -> None:
    if not os.path.isfile(os.path.join(bootchain_dir(), "kernelcache.img4")):
        raise RamdiskError("No A12/A13 bootchain staged — create one first.")


def bootchain_info() -> dict:
    """Parse chain.info into a dict (empty when nothing is staged)."""
    path = os.path.join(bootchain_dir(), "chain.info")
    if not os.path.isfile(path):
        return {}
    info = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            key, sep, value = line.partition("=")
            if sep:
                info[key.strip()] = value.strip()
    return info


# -----------------------------------------------------------------------------
# Post-boot helpers
# -----------------------------------------------------------------------------

def op_mount(progress_cb: ProgressCb, log_cb: LogCb,
             is_cancelled_cb: CancelCb) -> None:
    """
    Mount every NAND filesystem over SSH.

    `mount_ich` is what the toolkit's SSH payload ships for iOS 17 through 27+;
    older payloads only have the shell `mount_filesystems`. Probing for the
    binary first keeps one button working across both.
    """
    progress_cb(10, step="Connect", detail="Starting iproxy...")
    try:
        ram.start_iproxy(log_cb)
        ram._check_cancel(is_cancelled_cb)
        progress_cb(45, step="Mount Filesystems", detail="Detecting helper...")
        rc, out = ram.ssh_exec("command -v mount_ich || command -v mount_filesystems",
                               timeout=25)
        helper = out.strip().splitlines()[-1].strip() if rc == 0 else ""
        if not helper:
            raise RamdiskError(
                "Neither mount_ich nor mount_filesystems exists in the booted "
                "ramdisk — the SSH payload you injected does not carry them.")
        log_cb(f"[*] Using {helper}")
        progress_cb(70, step="Mount Filesystems", detail=os.path.basename(helper))
        rc, out = ram.ssh_exec(helper, timeout=180)
        if out.strip():
            log_cb(out.strip())
        if rc != 0:
            log_cb(f"[!] {os.path.basename(helper)} exited {rc} — some volumes "
                   "may still be unmounted.")
        progress_cb(100, step="Mount Filesystems",
                    detail="Mounted System / Preboot / xART / Data.")
    finally:
        ram.stop_iproxy()


def op_console(progress_cb: ProgressCb, log_cb: LogCb,
               is_cancelled_cb: CancelCb) -> None:
    progress_cb(20, step="Open Console", detail="Starting iproxy...")
    ram.open_ssh_console(log_cb)
    progress_cb(100, step="Open Console", detail="Console launched.")


def op_clean(progress_cb: ProgressCb, log_cb: LogCb,
             is_cancelled_cb: CancelCb) -> None:
    progress_cb(30, step="Clean Workspace", detail="Removing bootchain + work")
    ram.stop_iproxy()
    shutil.rmtree(bootchain_dir(), ignore_errors=True)
    shutil.rmtree(os.path.join(ich_root(), "out"), ignore_errors=True)
    shutil.rmtree(os.path.join(ich_root(), "work"), ignore_errors=True)
    # The IPSW member cache is deliberately kept: it is over a gigabyte and
    # keyed by product-build, so the next build of the same version is free.
    log_cb("[*] Removed the staged A12/A13 bootchain (IPSW cache kept)")
    progress_cb(100, step="Clean Workspace", detail="Done.")
