"""
Pymobile3-GUI — SSH Ramdisk Manager

Windows port of SSHRD_Script (checkm8 SSH ramdisk, A7–A11 + T2), split into
two execution domains:

  * USB / DFU steps (gaster pwn, irecovery loads, iproxy) run as native
    Windows executables — checkm8 is timing-sensitive and must not go
    through USB/IP.
  * Offline build steps (pzb fetch, img4/iBoot64Patcher/KPlooshFinder/
    kerneldiff/hfsplus patching) run the x86-64 Linux binaries bundled from
    SSHRD_Script inside WSL.

The command sequences mirror sshrd.sh (Linux branch) step for step; where a
shell construct is impractical from Python (awk over BuildManifest, PlistBuddy
extraction) the equivalent is reproduced against the same input text.

Known deviations, all deliberate:
  * `gaster reset` has no counterpart in the available Windows gaster builds —
    replaced by a pyusb device reset (same libusb `usb_reset` operation).
  * ipsw.me / BuildManifest parsing uses requests + plistlib instead of
    curl + jq + PlistBuddy.
  * On failure the scratch work/ directory is kept for inspection instead of
    being deleted (the next create removes it anyway).
"""

import os
import plistlib
import queue
import re
import shutil
import socket
import subprocess
import threading
import time
from typing import Callable, Optional

import requests

from pymobile3_gui.core.backend import firmware_keys
from pymobile3_gui.core.backend.paths import data_dir, documents_dir, resource_path

LogCb = Callable[[str], None]
ProgressCb = Callable[..., None]
CancelCb = Callable[[], bool]

CHECKM8_CPIDS = {
    "0x8960", "0x7000", "0x7001", "0x8000", "0x8003",
    "0x8010", "0x8011", "0x8012", "0x8015",
}
GO_AFTER_IBEC = {"0x8010", "0x8011", "0x8012", "0x8015"}
NAND_REFORMAT_CPIDS = {"0x8960", "0x7000", "0x7001"}

IPSW_API = "https://api.ipsw.me/v4/device/{product}?type=ipsw"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
TOOL_PROGRESS_RE = re.compile(r"^\s*\d+%\s*\[")

CREATE_STEPS = [
    "Detect Device", "Resolve IPSW", "Fetch Firmware",
    "Patch Bootchain", "Patch Kernel", "Build Ramdisk", "Finalize",
]
BOOT_STEPS = ["Detect Device", "Pwn Device", "Send Bootchain", "Boot Ramdisk"]
RESET_STEPS = ["Detect Device", "Pwn Device", "Send Bootchain", "Erase Device"]
REBOOT_STEPS = ["Connect", "Reboot Device"]
DUMP_STEPS = ["Connect", "Detect OS", "Dump Blobs"]
CLEAN_STEPS = ["Clean Workspace"]


class RamdiskError(Exception):
    """User-facing failure in a ramdisk operation."""


class RamdiskTimeout(RamdiskError):
    """A tool outlived its timeout. Distinct from a tool that failed."""


# gaster pwn is a USB bootrom exploit; it normally lands in a few seconds.
# The Windows build does not always exit once it has, so this is the window
# we allow before we stop it and go by the device's own PWND state instead.
PWN_TIMEOUT = 90.0

# gaster's USB_TIMEOUT is in milliseconds and this build defaults it to 5 ms,
# which every USB transfer blows through, so `pwn` and `decrypt` fail (or hang)
# unless it is raised. Measured: rc=1 at the default, rc=0 at 30 s.
GASTER_ENV = {"USB_TIMEOUT": "30000"}


# -----------------------------------------------------------------------------
# Locations
# -----------------------------------------------------------------------------

def assets_root() -> str:
    return resource_path("assets", "sshrd")


def win_tool(name: str) -> str:
    return os.path.join(assets_root(), "win", name)


def linux_tool(name: str) -> str:
    return os.path.join(assets_root(), "Linux", name)


def shsh_path(cpid: str) -> str:
    return os.path.join(assets_root(), "shsh", f"{cpid}.shsh")


def bootlogo_path() -> str:
    return os.path.join(assets_root(), "bootlogo.im4p")


def run_root() -> str:
    """Working directory for every operation (script-dir equivalent)."""
    path = os.path.join(data_dir(), "ramdisk")
    os.makedirs(path, exist_ok=True)
    return path


def work_dir() -> str:
    return os.path.join(run_root(), "work")


def td_dir_12() -> str:
    return os.path.join(run_root(), "12rd")


def sshramdisk_dir() -> str:
    path = os.path.join(run_root(), "sshramdisk")
    os.makedirs(path, exist_ok=True)
    return path


def sshtar_cache() -> str:
    """Decompressed sshtar tars (assets stay pristine; script gzip -d in place)."""
    path = os.path.join(run_root(), "sshtars_cache")
    os.makedirs(path, exist_ok=True)
    return path


def _fresh_dir(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)


# -----------------------------------------------------------------------------
# Path / quoting helpers
# -----------------------------------------------------------------------------

def win_to_wsl(path: str) -> str:
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", path)
    if not m:
        raise RamdiskError(f"Cannot translate path for WSL: {path}")
    rest = m.group(2).replace("\\", "/")
    return f"/mnt/{m.group(1).lower()}/{rest}"


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def wsl_arg(value: str) -> str:
    """
    Translate Windows path separators in tool args to POSIX form.

    WSL rewrites cwd but never rewrites argv, so a raw C:\\... path would
    reach a Linux binary as a relative filename and fail to open. Relative
    paths need the same treatment for the separator: `work\\iBSS.im4p` reaches
    the Linux side verbatim and `open()` rejects the backslash. Drive letters
    only occur on genuine paths (URLs, hex bags, boot-args are untouched), so
    the prefix test is enough.
    """
    if re.match(r"^[A-Za-z]:[\\/]", value):
        return win_to_wsl(value)
    if "\\" in value and "://" not in value:
        return value.replace("\\", "/")
    return value


def _check_cancel(is_cancelled_cb: CancelCb) -> None:
    if is_cancelled_cb and is_cancelled_cb():
        raise RamdiskError("Operation cancelled.")


def _sleep(seconds: float, is_cancelled_cb: CancelCb) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        _check_cancel(is_cancelled_cb)
        time.sleep(0.2)


# -----------------------------------------------------------------------------
# Process runners
# -----------------------------------------------------------------------------

def _stream_output(
    proc: "subprocess.Popen",
    log_cb: LogCb,
    is_cancelled_cb: CancelCb,
    on_line: Optional[Callable[[str], None]] = None,
    deadline: Optional[float] = None,
) -> None:
    lines: "queue.Queue[Optional[str]]" = queue.Queue()

    def reader():
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=reader, daemon=True).start()
    while True:
        _check_cancel(is_cancelled_cb)
        try:
            line = lines.get(timeout=0.25)
        except queue.Empty:
            # The timeout has to cover this wait, not just proc.wait(): a tool
            # that never closes stdout (the Windows gaster build lingers after
            # pwning) would otherwise block here forever and the caller's
            # timeout would never be reached.
            if deadline is not None and time.monotonic() > deadline:
                if proc.poll() is None:
                    raise RamdiskTimeout(
                        "tool produced no output and did not exit")
                # Exited without closing the pipe; fall through to proc.wait().
                return
            continue
        if line is None:
            return
        clean = ANSI_RE.sub("", line).rstrip("\r")
        if not clean or TOOL_PROGRESS_RE.match(clean):
            continue
        if on_line:
            on_line(clean)
        log_cb(clean)


def run_streaming(
    cmd: list[str],
    *,
    cwd: Optional[str],
    log_cb: LogCb,
    is_cancelled_cb: CancelCb,
    allow_failure: bool = False,
    context: str = "",
    timeout: Optional[float] = None,
    extra_env: Optional[dict] = None,
) -> int:
    """Run a tool, streaming merged output to log_cb. Raises on bad rc."""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    child_env = None
    if extra_env:
        child_env = {**os.environ, **extra_env}
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=creationflags, env=child_env,
        )
    except OSError as e:
        raise RamdiskError(f"Failed to launch {cmd[0]}: {e}")
    try:
        _stream_output(
            proc, log_cb, is_cancelled_cb,
            deadline=(time.monotonic() + timeout) if timeout else None)
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise RamdiskTimeout(f"{context or cmd[0]} timed out after {timeout}s")
    except RamdiskError:
        # Cancellation raises out of _stream_output with no finally on the
        # Popen, so the child keeps running (a half-downloaded IPSW would keep
        # writing while the next op deletes the work dir). Kill it before
        # re-raising.
        try:
            proc.kill()
        finally:
            proc.wait()
        raise
    if rc != 0 and not allow_failure:
        raise RamdiskError(
            f"{context or os.path.basename(cmd[0])} failed (exit code {rc}).")
    return rc


def run_capture(cmd: list[str], *, timeout: float = 15) -> tuple[int, str]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        out = subprocess.run(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout, creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return out.returncode, out.stdout.decode("utf-8", errors="replace")


# -----------------------------------------------------------------------------
# WSL
# -----------------------------------------------------------------------------

_wsl_distro: Optional[str] = "unchecked"

DEFAULT_WSL_DISTRO = "Ubuntu"


def _resolve_wsl_distro() -> Optional[str]:
    for distro in (DEFAULT_WSL_DISTRO, None):
        cmd = ["wsl.exe"]
        if distro:
            cmd += ["-d", distro]
        cmd += ["-e", "true"]
        rc, _ = run_capture(cmd, timeout=30)
        if rc == 0:
            return distro or ""
    return None


def wsl_available() -> bool:
    global _wsl_distro
    if _wsl_distro == "unchecked":
        _wsl_distro = _resolve_wsl_distro() or None
    return bool(_wsl_distro)


def wsl_tool(
    tool: str,
    args: list[str],
    *,
    cwd: str,
    log_cb: LogCb,
    is_cancelled_cb: CancelCb,
    allow_failure: bool = False,
    context: str = "",
    timeout: Optional[float] = None,
) -> int:
    """Run a bundled Linux binary inside WSL with cwd set."""
    if not wsl_available():
        raise RamdiskError(
            "WSL (Ubuntu) is required for ramdisk build steps. "
            "Install it with: wsl --install")
    wsl_cwd = win_to_wsl(cwd)
    binary = win_to_wsl(linux_tool(tool))
    inner = f"cd {sh_quote(wsl_cwd)} && {sh_quote(binary)} " + " ".join(
        sh_quote(wsl_arg(a)) for a in args)
    cmd = ["wsl.exe"]
    if _wsl_distro:
        cmd += ["-d", _wsl_distro]
    cmd += ["-e", "bash", "-c", inner]
    return run_streaming(
        cmd, cwd=None, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
        allow_failure=allow_failure,
        context=context or f"{tool} {' '.join(args[:1])}".strip(), timeout=timeout,
    )


def native_tool(
    tool: str,
    args: list[str],
    *,
    log_cb: LogCb,
    is_cancelled_cb: CancelCb,
    allow_failure: bool = False,
    context: str = "",
    timeout: Optional[float] = None,
    extra_env: Optional[dict] = None,
) -> int:
    """Run a vendored native Windows executable (cwd = run root)."""
    return run_streaming(
        [win_tool(tool), *args], cwd=run_root(), log_cb=log_cb,
        is_cancelled_cb=is_cancelled_cb, allow_failure=allow_failure,
        context=context or tool, timeout=timeout, extra_env=extra_env,
    )


# -----------------------------------------------------------------------------
# Device detection (DFU / recovery via native irecovery)
# -----------------------------------------------------------------------------

def parse_device_info(text: str) -> Optional[dict]:
    """Parse `irecovery -q` output into a device dict (None when absent)."""
    if "CPID" not in text:
        return None
    info = {}
    for line in text.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            info[key.strip().lower()] = val.strip()
    cpid = info.get("cpid")
    if not cpid:
        return None
    return {
        "cpid": cpid,
        "model": info.get("model", ""),
        "product": info.get("product", ""),
        "name": info.get("name", ""),
        "ecid": info.get("ecid", ""),
        "mode": info.get("mode", ""),
        "pwned": info.get("pwnd", "").upper() == "CHECKM8",
    }


def detect_device() -> Optional[dict]:
    rc, out = run_capture([win_tool("irecovery"), "-q"], timeout=10)
    if rc != 0:
        return None
    return parse_device_info(out)


def wait_for_device(log_cb: LogCb, is_cancelled_cb: CancelCb) -> dict:
    announced = False
    while True:
        _check_cancel(is_cancelled_cb)
        dev = detect_device()
        if dev:
            if dev["cpid"] not in CHECKM8_CPIDS:
                raise RamdiskError(
                    f"Device CPID {dev['cpid']} is not a checkm8 "
                    "(A7–A11 / T2) target.")
            return dev
        if not announced:
            log_cb("[*] Waiting for device in DFU mode")
            announced = True
        time.sleep(1.0)


# -----------------------------------------------------------------------------
# gaster / USB helpers
# -----------------------------------------------------------------------------

def is_pwned(log_cb: LogCb) -> bool:
    """Ask the DFU device whether checkm8 pwning is still in effect."""
    dev = detect_device()
    return bool(dev and dev["pwned"])


def gaster_pwn(log_cb: LogCb, is_cancelled_cb: CancelCb) -> bool:
    """
    Put the device into pwned DFU mode.

    Returns True when this call performed the pwn (the caller then needs a USB
    reset to re-enumerate), False when the device was already pwned.
    """
    # Pwning is already in effect (a previous run, or the user in another
    # tool). Re-running gaster would re-exploit the device for nothing and on
    # some builds wedges it, so skip straight past it.
    if is_pwned(log_cb):
        log_cb("[*] Device already pwned (PWND: CHECKM8) — skipping gaster pwn")
        return False

    log_cb("[*] Pwning device with gaster (checkm8)...")
    # gaster talks to the device over libusb, so it must not be sitting behind
    # Apple's DFU driver. Best effort: on a device that is already pwned we are
    # about to skip the pwn anyway, and a permission problem here should not
    # stop an operation that does not need it.
    try:
        ensure_dfu_driver(log_cb)
    except RamdiskError as exc:
        log_cb(f"[!] {exc}")
    # The Windows gaster build pwns successfully but then lingers instead of
    # exiting, so waiting on EOF hangs forever on a successful pwn. Bound it
    # and settle on what the device itself reports: irecovery reflects
    # PWND: CHECKM8 as soon as the exploit lands.
    try:
        native_tool("gaster", ["pwn"], log_cb=log_cb,
                    is_cancelled_cb=is_cancelled_cb, context="gaster pwn",
                    timeout=PWN_TIMEOUT, extra_env=GASTER_ENV)
    except RamdiskTimeout:
        if not is_pwned(log_cb):
            raise RamdiskError(
                "gaster pwn did not take effect within "
                f"{PWN_TIMEOUT:.0f}s. Check that the DFU driver is the "
                "winra1n/libusb driver (Zadig) and that the device is still "
                "in DFU mode.") from None
        log_cb("[*] gaster pwn took effect; the tool lingered after pwning "
               "and was terminated — continuing.")
    return True


def usb_reset(log_cb: LogCb) -> None:
    """
    `gaster reset` equivalent — libusb usb_reset_device via pyusb.

    None of the available Windows gaster builds expose a reset command, so
    the same libusb operation is issued directly against the DFU device.
    """
    import usb.backend.libusb1
    import usb.core

    dll = os.path.join(assets_root(), "win", "libusb-1.0.dll")
    backend = None
    if os.path.isfile(dll):
        backend = usb.backend.libusb1.get_backend(find_library=lambda _: dll)
    kwargs = {"idVendor": 0x05AC}
    if backend:
        kwargs["backend"] = backend
    dev = None
    # Try the known checkm8-era DFU product ids first, then fall back to ANY
    # Apple device — but never drop the vendor filter: resetting an arbitrary
    # non-Apple USB device (a user's mouse/keyboard/hub) would be catastrophic.
    for product in (0x1227, 0x1222, 0x1228):
        kw = dict(kwargs)
        kw["idProduct"] = product
        try:
            dev = usb.core.find(**kw)
        except usb.core.USBError as e:
            raise RamdiskError(f"USB reset failed: {e}")
        if dev is not None:
            break
    if dev is None:
        try:
            dev = usb.core.find(**kwargs)
        except usb.core.USBError as e:
            raise RamdiskError(f"USB reset failed: {e}")
    if dev is None:
        raise RamdiskError(
            "USB reset failed: no Apple USB device visible. If gaster pwn "
            "worked but this fails, check the DFU driver (WinUSB/libusbk).")
    try:
        dev.reset()
    except usb.core.USBError as e:
        raise RamdiskError(f"USB reset failed: {e}")
    log_cb("[*] USB device reset (gaster reset equivalent).")


def ensure_dfu_driver(log_cb: LogCb) -> None:
    """
    Make sure the DFU interface is bound to a libusb-style driver.

    `gaster` reaches the device through libusb, and Apple's DFU driver
    (AppleUsbMux, service WINUSB) binds the interface exclusively, so a pwn
    attempt against it hangs instead of failing. Applying the already-registered
    libusbK package to the matching hardware id is the scripted equivalent of
    choosing it in Zadig. Windows re-binds Apple's driver on the next
    re-enumeration, so this runs immediately before each pwn. Needs admin.
    """
    script = (
        "$inf = 'C:\\Windows\\INF\\oem6.inf'; "
        "if (-not (Test-Path $inf)) { exit 3 }; "
        "pnputil /add-driver $inf /install"
    )
    rc, out = run_capture(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=60)
    lowered = out.lower()
    if "access is denied" in lowered:
        raise RamdiskError(
            "Switching the DFU driver to libusbK needs administrator rights.")
    if "total driver packages" not in lowered and rc != 0:
        raise RamdiskError(f"Could not apply the libusbK driver: {out.strip()}")
    log_cb("[*] DFU driver set to libusbK (libusb) for gaster.")


def usb_restart_device(log_cb: LogCb) -> None:
    """
    Re-enumerate the DFU device via `pnputil /restart-device`.

    Fallback for `usb_reset` when pyusb cannot claim the device, which is the
    normal case on Windows: Apple's DFU driver binds the interface exclusively,
    so libusb never sees it however the driver rank is set. PnP restarts the
    node regardless of which driver owns it, which is the re-enumeration
    `gaster reset` performs. Needs administrator rights.
    """
    if detect_device() is None:
        raise RamdiskError(
            "Cannot restart the DFU device: it is not responding.")
    script = (
        "$d = Get-PnpDevice -PresentOnly | "
        "Where-Object { $_.InstanceId -like 'USB\\VID_05AC&PID_1227*' } | "
        "Select-Object -First 1; "
        "if (-not $d) { exit 2 }; "
        "pnputil /restart-device $d.InstanceId"
    )
    rc, out = run_capture(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=45)
    lowered = out.lower()
    if "access is denied" in lowered:
        raise RamdiskError(
            "pnputil /restart-device needs administrator rights")
    if "successfully" not in lowered:
        raise RamdiskError(
            f"pnputil /restart-device did not report success: {out.strip()}")
    log_cb("[*] DFU device restarted via pnputil (gaster reset equivalent).")


# -----------------------------------------------------------------------------
# iproxy + SSH (paramiko)
# -----------------------------------------------------------------------------

_iproxy_lock = threading.Lock()
_iproxy_proc: Optional[subprocess.Popen] = None


def start_iproxy(log_cb: LogCb) -> None:
    global _iproxy_proc
    with _iproxy_lock:
        if _iproxy_proc and _iproxy_proc.poll() is None:
            return
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        _iproxy_proc = subprocess.Popen(
            [win_tool("iproxy"), "2222:22"], cwd=run_root(),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=creationflags,
        )
    for _ in range(30):
        try:
            with socket.create_connection(("127.0.0.1", 2222), timeout=0.3):
                log_cb("[*] iproxy forwarding 2222 -> 22.")
                return
        except OSError:
            time.sleep(0.2)
    raise RamdiskError("iproxy did not open port 2222 — is a device connected?")


def stop_iproxy() -> None:
    global _iproxy_proc
    with _iproxy_lock:
        proc = _iproxy_proc
        _iproxy_proc = None
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def ssh_exec(command: str, *, timeout: float = 30) -> tuple[int, str]:
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            "127.0.0.1", port=2222, username="root", password="alpine",
            timeout=15, banner_timeout=15, auth_timeout=15,
            allow_agent=False, look_for_keys=False,
        )
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        return rc, out if not err else out + err
    finally:
        client.close()


# -----------------------------------------------------------------------------
# IPSW resolution (ipsw.me — same API sshrd.sh queries with curl + jq)
# -----------------------------------------------------------------------------

def fetch_firmware_versions(product: str) -> list[dict]:
    try:
        resp = requests.get(IPSW_API.format(product=product), timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        raise RamdiskError(f"ipsw.me lookup failed for {product}: {e}")
    return [
        {"version": fw.get("version", ""), "signed": bool(fw.get("signed"))}
        for fw in data.get("firmwares", [])
    ]


def resolve_ipsw_url(product: str, version: str) -> str:
    try:
        resp = requests.get(IPSW_API.format(product=product), timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        raise RamdiskError(f"ipsw.me lookup failed for {product}: {e}")
    for fw in data.get("firmwares", []):
        if fw.get("version") == version and fw.get("url"):
            return fw["url"]
    known = ", ".join(fw.get("version", "") for fw in data.get("firmwares", [])[:8])
    raise RamdiskError(
        f"No IPSW for {product} version {version} on ipsw.me "
        f"(recent: {known}...)")


def build_number_from_ipsw_url(url: str) -> str:
    """
    Pull the build number out of an IPSW filename.

    Apple names them `<product>_<board>_<version>_<build>_Restore.ipsw`, and the
    key pages are indexed by build, so the build has to come from the URL rather
    than being asked for separately.
    """
    match = re.search(r"_(\d{2}[A-Za-z]\d{3,4})_Restore\.ipsw", url)
    if not match:
        raise RamdiskError(f"Could not determine the build number from {url}")
    return match.group(1)


def _decrypt_bootchain_image(
    src: str, dst: str, keys: dict, root: str,
    log_cb: LogCb, is_cancelled_cb: CancelCb,
) -> None:
    """Decrypt one KBAG-wrapped bootchain image using Apple Wiki keys."""
    _check_cancel(is_cancelled_cb)
    name = os.path.basename(src)
    component = firmware_keys.lookup_key(keys, name)
    if component is None:
        raise RamdiskError(
            f"The Apple Wiki publishes no keys for {name}, "
            "so it cannot be decrypted on this machine.")
    wsl_tool("img4", ["-i", src, "-o", dst, "-k", firmware_keys.ivkey(component)],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context=f"img4 -k ({name})")
    log_cb(f"[*] {name} -> {os.path.basename(dst)} ({component.component} key)")


# -----------------------------------------------------------------------------
# BuildManifest helpers (ports of the awk / PlistBuddy extractions)
# -----------------------------------------------------------------------------

def extract_manifest_path(
    manifest_text: str, model: str, key_pattern: str,
) -> str:
    """
    Equivalent of sshrd.sh's:
      awk "/MODEL/{x=1} x&&/key/{print;exit}" BuildManifest.plist |
        grep '<string>' | cut -d> -f2 | cut -d< -f1
    """
    if not model:
        raise RamdiskError("Device model unknown — cannot select build identity.")
    lines = manifest_text.splitlines()
    start = -1
    for i, line in enumerate(lines):
        if model in line:
            start = i
            break
    if start < 0:
        raise RamdiskError(
            f"BuildManifest has no identity for device model '{model}'.")
    pat = re.compile(key_pattern)
    for line in lines[start:]:
        if pat.search(line):
            m = re.search(r"<string>([^<]*)</string>", line)
            if m:
                return m.group(1)
    raise RamdiskError(f"BuildManifest entry not found: {key_pattern}")


def strip_fw_prefix(path: str, prefix: str) -> str:
    """sed 's/Firmware[/]dfu[/]//' equivalent (pzb writes flattened files)."""
    if path.startswith(prefix):
        return path[len(prefix):]
    return path


def restore_ramdisk_name(manifest_bytes: bytes) -> str:
    """Linux/PlistBuddy: BuildIdentities:0:Manifest:RestoreRamDisk:Info:Path."""
    try:
        data = plistlib.loads(manifest_bytes)
        return data["BuildIdentities"][0]["Manifest"]["RestoreRamDisk"]["Info"]["Path"]
    except (plistlib.InvalidFileException, KeyError, IndexError, TypeError) as e:
        raise RamdiskError(f"Cannot read RestoreRamDisk path from manifest: {e}")


# -----------------------------------------------------------------------------
# Version / darwin mapping conditions (verbatim from sshrd.sh)
# -----------------------------------------------------------------------------

def parse_version(version: str) -> tuple[int, int, int]:
    parts = (version.split(".") + ["0", "0", "0"])[:3]
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        raise RamdiskError(f"Invalid iOS version: '{version}'")


def darwin_major_for(cpid: str, major: int) -> int:
    if cpid == "0x8012":
        return major + 15
    if major >= 26:
        return major - 1
    return major + 6


def trustcache_needed(cpid: str, dm: int, minor: int, patch: int) -> bool:
    """Inverted form of sshrd.sh's skip condition (lines 249/291/196)."""
    skip = dm < 17 or (
        dm == 17 and (minor < 4 or (minor == 4 and patch <= 1) or cpid != "0x8012")
    )
    return not skip


def linux_build_blocked(dm: int, minor: int) -> Optional[str]:
    """sshrd.sh Linux branch refuses iOS 16.1+ (hfsplus path limitation)."""
    if dm > 22 or (dm == 22 and minor >= 1):
        return ("iOS 16.1 and newer cannot be built through the SSHRD Linux "
                "path — pick an iOS ≤ 16.0 ramdisk version.")
    return None


def needs_12rd(dm: int, minor: int, patch: int) -> bool:
    return dm < 17 or (dm == 17 and (minor < 4 or (minor == 4 and patch <= 1)))


# -----------------------------------------------------------------------------
# ipsw fetch + tar helpers
# -----------------------------------------------------------------------------

def _pzb_fetch(
    zip_path: str, url: str, *, cwd: str, log_cb: LogCb,
    is_cancelled_cb: CancelCb,
) -> None:
    out_name = os.path.basename(zip_path)
    target = os.path.join(cwd, out_name)
    if os.path.exists(target):
        os.remove(target)
    log_cb(f"[pzb] {zip_path}")
    wsl_tool("pzb", ["-g", zip_path, url], cwd=cwd, log_cb=log_cb,
             is_cancelled_cb=is_cancelled_cb, context=f"pzb {out_name}")
    # pzb exits 0 even on failure — the file is the only honest signal.
    if not os.path.isfile(target) or os.path.getsize(target) == 0:
        raise RamdiskError(f"pzb failed to download {zip_path} from the IPSW.")


def _ensure_tar(name: str) -> str:
    """Decompress assets/sshtars/<name>.tar.gz into the cache (once)."""
    gz = os.path.join(assets_root(), "sshtars", f"{name}.tar.gz")
    dst = os.path.join(sshtar_cache(), f"{name}.tar")
    if not os.path.isfile(dst) or os.path.getsize(dst) == 0:
        import gzip
        with gzip.open(gz, "rb") as src, open(dst, "wb") as out:
            shutil.copyfileobj(src, out)
    return dst


# -----------------------------------------------------------------------------
# Operations
# -----------------------------------------------------------------------------

def op_create(
    version: str, trollstore_app: str,
    progress_cb: ProgressCb, log_cb: LogCb, is_cancelled_cb: CancelCb,
) -> None:
    root = run_root()

    progress_cb(0, step="Detect Device", detail="Waiting for DFU device...")
    if not wsl_available():
        raise RamdiskError(
            "WSL (Ubuntu) is required to build a ramdisk. "
            "Install it with: wsl --install — then try again.")
    dev = wait_for_device(log_cb, is_cancelled_cb)
    cpid, model, product = dev["cpid"], dev["model"], dev["product"]
    log_cb(f"[*] Device: {product} model={model} CPID={cpid}")

    shsh = shsh_path(cpid)
    if not os.path.isfile(shsh):
        raise RamdiskError(f"No SHSH blob bundled for CPID {cpid} ({shsh}).")

    major, minor, patch = parse_version(version)
    dm = darwin_major_for(cpid, major)
    blocked = linux_build_blocked(dm, minor)
    if blocked:
        raise RamdiskError(blocked)

    progress_cb(6, step="Resolve IPSW", detail=f"iOS {version} for {product}")
    ipsw_url = resolve_ipsw_url(product, version)
    log_cb(f"[*] IPSW: {ipsw_url}")

    _fresh_dir(work_dir())
    shutil.rmtree(td_dir_12(), ignore_errors=True)
    sshramdisk_dir()

    progress_cb(12, step="Fetch Firmware", detail="Pwning device...")
    # sshrd.sh also runs `gaster decrypt_kbag 000...0 || true` here (an A10X/T2
    # workaround). It is deliberately not ported: on this gaster build it
    # produces no output and no kbag, it was called without a timeout so it can
    # hang, and the keys it would cache are now fetched from The Apple Wiki.
    gaster_pwn(log_cb, is_cancelled_cb)
    wsl_tool("img4tool", ["-e", "-s", shsh, "-m", os.path.join("work", "IM4M")],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="img4tool (SHSH -> IM4M)")

    total_fetch = 7
    fetch_n = 0

    def fetched():
        nonlocal fetch_n
        fetch_n += 1
        progress_cb(12 + int(40 * fetch_n / total_fetch),
                    step="Fetch Firmware", detail=f"{fetch_n}/{total_fetch} parts")

    work = work_dir()
    _pzb_fetch("BuildManifest.plist", ipsw_url, cwd=work, log_cb=log_cb,
               is_cancelled_cb=is_cancelled_cb)
    fetched()

    with open(os.path.join(work, "BuildManifest.plist"), "rb") as fh:
        manifest_bytes = fh.read()
    manifest_text = manifest_bytes.decode("utf-8", errors="replace")

    ibss_zip = extract_manifest_path(manifest_text, model, r"iBSS[.]")
    ibec_zip = extract_manifest_path(manifest_text, model, r"iBEC[.]")
    dt_zip = extract_manifest_path(manifest_text, model, r"DeviceTree[.]")
    kc_zip = extract_manifest_path(manifest_text, model, r"kernelcache[.]release")
    ramdisk_zip = restore_ramdisk_name(manifest_bytes)

    tc_zip = f"Firmware/{ramdisk_zip}.trustcache"
    fetch_tc = trustcache_needed(cpid, dm, minor, patch)

    for part in (ibss_zip, ibec_zip, dt_zip):
        _pzb_fetch(part, ipsw_url, cwd=work, log_cb=log_cb,
                   is_cancelled_cb=is_cancelled_cb)
        fetched()
    if fetch_tc:
        _pzb_fetch(tc_zip, ipsw_url, cwd=work, log_cb=log_cb,
                   is_cancelled_cb=is_cancelled_cb)
        fetched()
    _pzb_fetch(kc_zip, ipsw_url, cwd=work, log_cb=log_cb,
               is_cancelled_cb=is_cancelled_cb)
    fetched()
    _pzb_fetch(ramdisk_zip, ipsw_url, cwd=work, log_cb=log_cb,
               is_cancelled_cb=is_cancelled_cb)
    fetched()

    ibss_file = os.path.join("work", strip_fw_prefix(ibss_zip, "Firmware/dfu/"))
    ibec_file = os.path.join("work", strip_fw_prefix(ibec_zip, "Firmware/dfu/"))
    kc_file = os.path.join("work", kc_zip)
    dt_file = os.path.join("work", strip_fw_prefix(dt_zip, "Firmware/all_flash/"))
    ramdisk_file = os.path.join("work", ramdisk_zip)
    tc_file = os.path.join("work", os.path.basename(tc_zip))

    # ── Patch Bootchain ────────────────────────────────────────────────────
    progress_cb(55, step="Patch Bootchain", detail="Decrypting iBSS / iBEC...")
    if dm >= 24:
        wsl_tool("img4", ["-i", ibss_file, "-o", os.path.join("work", "iBSS.dec")],
                 cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                 context="img4 (iBSS)")
        wsl_tool("img4", ["-i", ibec_file, "-o", os.path.join("work", "iBEC.dec")],
                 cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                 context="img4 (iBEC)")
    else:
        # sshrd.sh uses `gaster decrypt` here, which drives the device's AES
        # engine over USB. That is unreliable on Windows, so take the bootchain
        # keys from The Apple Wiki and decrypt locally instead.
        build = build_number_from_ipsw_url(ipsw_url)
        progress_cb(55, step="Patch Bootchain",
                    detail=f"Fetching firmware keys for {build}...")
        try:
            keys = firmware_keys.fetch_component_keys(
                build, product, major)
        except firmware_keys.FirmwareKeyError as exc:
            raise RamdiskError(
                f"{exc}\n\nThe Apple Wiki has no published keys for this "
                "build, so it cannot be built without device-side "
                "decryption.") from exc
        for src in (ibss_file, ibec_file):
            _decrypt_bootchain_image(src, os.path.join("work", os.path.basename(
                src).split(".")[0] + ".dec"), keys, root, log_cb,
                is_cancelled_cb)

    wsl_tool("iBoot64Patcher",
             [os.path.join("work", "iBSS.dec"), os.path.join("work", "iBSS.patched")],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="iBoot64Patcher (iBSS)")

    boot_args = "rd=md0 debug=0x2014e -v wdt=-1"
    if trollstore_app:
        boot_args += f" TrollStore={trollstore_app}"
    if cpid in NAND_REFORMAT_CPIDS:
        boot_args += " nand-enable-reformat=1 -restore"

    wsl_tool("iBoot64Patcher",
             [os.path.join("work", "iBEC.dec"), os.path.join("work", "iBEC.patched"),
              "-b", boot_args, "-n"],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="iBoot64Patcher (iBEC)")

    wsl_tool("img4",
             ["-i", os.path.join("work", "iBSS.patched"),
              "-o", os.path.join("sshramdisk", "iBSS.img4"),
              "-M", os.path.join("work", "IM4M"), "-A", "-T", "ibss"],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="img4 sign (iBSS)")
    wsl_tool("img4",
             ["-i", os.path.join("work", "iBEC.patched"),
              "-o", os.path.join("sshramdisk", "iBEC.img4"),
              "-M", os.path.join("work", "IM4M"), "-A", "-T", "ibec"],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="img4 sign (iBEC)")
    progress_cb(66, step="Patch Bootchain", detail="Bootchain signed.")

    # ── Patch Kernel ───────────────────────────────────────────────────────
    progress_cb(68, step="Patch Kernel", detail="Extracting kernelcache...")
    wsl_tool("img4", ["-i", kc_file, "-o", os.path.join("work", "kcache.raw")],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="img4 (kernelcache)")
    wsl_tool("KPlooshFinder",
             [os.path.join("work", "kcache.raw"),
              os.path.join("work", "kcache.patched")],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="KPlooshFinder")
    wsl_tool("kerneldiff",
             [os.path.join("work", "kcache.raw"),
              os.path.join("work", "kcache.patched"),
              os.path.join("work", "kc.bpatch")],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="kerneldiff")
    wsl_tool("img4",
             ["-i", kc_file, "-o", os.path.join("sshramdisk", "kernelcache.img4"),
              "-M", os.path.join("work", "IM4M"), "-T", "rkrn",
              "-P", os.path.join("work", "kc.bpatch"), "-J"],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="img4 sign (kernel)")
    wsl_tool("img4",
             ["-i", dt_file, "-o", os.path.join("sshramdisk", "devicetree.img4"),
              "-M", os.path.join("work", "IM4M"), "-T", "rdtr"],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="img4 sign (devicetree)")
    if fetch_tc:
        wsl_tool("img4",
                 ["-i", tc_file,
                  "-o", os.path.join("sshramdisk", "trustcache.img4"),
                  "-M", os.path.join("work", "IM4M"), "-T", "rtsc"],
                 cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                 context="img4 sign (trustcache)")
    wsl_tool("img4", ["-i", ramdisk_file, "-o", os.path.join("work", "ramdisk.dmg")],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="img4 (ramdisk)")
    progress_cb(80, step="Patch Kernel", detail="Kernel patched & signed.")

    # ── Build Ramdisk ──────────────────────────────────────────────────────
    progress_cb(82, step="Build Ramdisk", detail="Growing ramdisk image...")
    if cpid == "0x8012":
        grow = "133169152"
    else:
        grow = "210000000"
    wsl_tool("hfsplus",
             [os.path.join("work", "ramdisk.dmg"), "grow", grow],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="hfsplus grow")

    if model == "j42dap":
        tar_name = "atvssh"
    elif cpid == "0x8012":
        tar_name = "t2ssh"
    else:
        tar_name = "ssh"

    if needs_12rd(dm, minor, patch):
        log_cb("[*] iOS <= 11.4 device — grafting libiconv from the iOS 12 "
               "restore ramdisk...")
        d12 = td_dir_12()
        os.makedirs(d12, exist_ok=True)
        url12 = resolve_ipsw_url(product, "12.0")
        _pzb_fetch("BuildManifest.plist", url12, cwd=d12, log_cb=log_cb,
                   is_cancelled_cb=is_cancelled_cb)
        with open(os.path.join(d12, "BuildManifest.plist"), "rb") as fh:
            d12_manifest = fh.read()
        d12_ramdisk = restore_ramdisk_name(d12_manifest)
        _pzb_fetch(d12_ramdisk, url12, cwd=d12, log_cb=log_cb,
                   is_cancelled_cb=is_cancelled_cb)
        wsl_tool("img4", ["-i", d12_ramdisk, "-o", "ramdisk.dmg"],
                 cwd=d12, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                 context="img4 (iOS 12 ramdisk)")
        for dylib in ("usr/lib/libiconv.2.dylib", "usr/lib/libcharset.1.dylib"):
            wsl_tool("hfsplus", ["ramdisk.dmg", "extract", dylib,
                                 os.path.basename(dylib)],
                     cwd=d12, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                     context=f"hfsplus extract {os.path.basename(dylib)}")
        for dylib in ("libiconv.2.dylib", "libcharset.1.dylib"):
            wsl_tool("hfsplus",
                     [os.path.join("..", "work", "ramdisk.dmg"), "add", dylib,
                      f"usr/lib/{dylib}"],
                     cwd=d12, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                     context=f"hfsplus add {dylib}")
        shutil.rmtree(d12, ignore_errors=True)

    progress_cb(88, step="Build Ramdisk", detail=f"Injecting {tar_name} payload...")
    tar_path = _ensure_tar(tar_name)
    wsl_tool("hfsplus",
             [os.path.join("work", "ramdisk.dmg"), "untar", tar_path],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="hfsplus untar")

    # ── Finalize ───────────────────────────────────────────────────────────
    progress_cb(94, step="Finalize", detail="Signing ramdisk images...")
    wsl_tool("img4",
             ["-i", os.path.join("work", "ramdisk.dmg"),
              "-o", os.path.join("sshramdisk", "ramdisk.img4"),
              "-M", os.path.join("work", "IM4M"), "-A", "-T", "rdsk"],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="img4 sign (ramdisk)")
    wsl_tool("img4",
             ["-i", bootlogo_path(),
              "-o", os.path.join("sshramdisk", "logo.img4"),
              "-M", os.path.join("work", "IM4M"), "-A", "-T", "rlgo"],
             cwd=root, log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
             context="img4 sign (logo)")

    with open(os.path.join(sshramdisk_dir(), "version.txt"), "w",
              encoding="utf-8") as fh:
        fh.write(version)

    shutil.rmtree(work_dir(), ignore_errors=True)
    shutil.rmtree(td_dir_12(), ignore_errors=True)
    log_cb("[*] Finished! Use Boot Ramdisk to start the device.")
    progress_cb(100, step="Finalize", detail="Ramdisk created.")


def _require_built() -> None:
    if not os.path.isfile(os.path.join(sshramdisk_dir(), "iBSS.img4")):
        raise RamdiskError("Create an SSH ramdisk first.")


def _pwn_and_settle(log_cb: LogCb, is_cancelled_cb: CancelCb) -> None:
    """
    Ensure the device is pwned, then re-enumerate only if we had to pwn it.

    The reset also hands the device back to Apple's DFU driver, which hides it
    from libusb, and it needs a driver we do not necessarily control. So it is
    both conditional and best-effort: a failure here must not stop us when
    `irecovery` can still reach the device and will say so if it cannot.
    """
    if not gaster_pwn(log_cb, is_cancelled_cb):
        log_cb("[*] Already pwned; skipping USB reset")
        return
    try:
        usb_reset(log_cb)
        return
    except RamdiskError as exc:
        log_cb(f"[!] libusb reset unavailable ({exc})")
    # Fall back to a PnP restart, which works even when Apple's DFU driver
    # holds the interface away from libusb. Needs admin; the app already
    # relaunches elevated for the iOS 17+ tunnel.
    try:
        usb_restart_device(log_cb)
    except RamdiskError as exc:
        log_cb(f"[!] PnP restart failed ({exc}); continuing — irecovery will "
               "report if the device is really unreachable.")


def op_boot(
    progress_cb: ProgressCb, log_cb: LogCb, is_cancelled_cb: CancelCb,
) -> None:
    _require_built()
    progress_cb(0, step="Detect Device", detail="Waiting for DFU device...")
    dev = wait_for_device(log_cb, is_cancelled_cb)
    cpid = dev["cpid"]

    with open(os.path.join(sshramdisk_dir(), "version.txt"), encoding="utf-8") as fh:
        version = fh.read().strip()
    major, minor, patch = parse_version(version)
    dm = darwin_major_for(cpid, major)

    progress_cb(25, step="Pwn Device", detail="gaster pwn + USB reset")
    _pwn_and_settle(log_cb, is_cancelled_cb)

    sd = sshramdisk_dir()
    progress_cb(45, step="Send Bootchain", detail="iBSS -> iBEC")
    native_tool("irecovery", ["-f", os.path.join("sshramdisk", "iBSS.img4")],
                log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                context="irecovery (iBSS)")
    _sleep(2, is_cancelled_cb)
    native_tool("irecovery", ["-f", os.path.join("sshramdisk", "iBEC.img4")],
                log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                context="irecovery (iBEC)")
    if cpid in GO_AFTER_IBEC:
        native_tool("irecovery", ["-c", "go"], log_cb=log_cb,
                    is_cancelled_cb=is_cancelled_cb, context="irecovery go")
    _sleep(2, is_cancelled_cb)

    progress_cb(70, step="Send Bootchain", detail="logo / ramdisk / devicetree")
    native_tool("irecovery", ["-f", os.path.join("sshramdisk", "logo.img4")],
                log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                context="irecovery (logo)")
    native_tool("irecovery", ["-c", "setpicture 0x1"], log_cb=log_cb,
                is_cancelled_cb=is_cancelled_cb, context="irecovery setpicture")
    native_tool("irecovery", ["-f", os.path.join("sshramdisk", "ramdisk.img4")],
                log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                context="irecovery (ramdisk)")
    native_tool("irecovery", ["-c", "ramdisk"], log_cb=log_cb,
                is_cancelled_cb=is_cancelled_cb, context="irecovery ramdisk")
    native_tool("irecovery", ["-f", os.path.join("sshramdisk", "devicetree.img4")],
                log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                context="irecovery (devicetree)")
    native_tool("irecovery", ["-c", "devicetree"], log_cb=log_cb,
                is_cancelled_cb=is_cancelled_cb, context="irecovery devicetree")
    if trustcache_needed(cpid, dm, minor, patch):
        native_tool("irecovery", ["-f", os.path.join("sshramdisk", "trustcache.img4")],
                    log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                    context="irecovery (trustcache)")
        native_tool("irecovery", ["-c", "firmware"], log_cb=log_cb,
                    is_cancelled_cb=is_cancelled_cb, context="irecovery firmware")

    progress_cb(90, step="Boot Ramdisk", detail="kernelcache bootx")
    native_tool("irecovery", ["-f", os.path.join("sshramdisk", "kernelcache.img4")],
                log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                context="irecovery (kernelcache)")
    native_tool("irecovery", ["-c", "bootx"], log_cb=log_cb,
                is_cancelled_cb=is_cancelled_cb, context="irecovery bootx")
    log_cb("[*] Device should now show text on screen.")
    progress_cb(100, step="Boot Ramdisk", detail="Boot sent.")


def op_reset(
    progress_cb: ProgressCb, log_cb: LogCb, is_cancelled_cb: CancelCb,
) -> None:
    _require_built()
    progress_cb(0, step="Detect Device", detail="Waiting for DFU device...")
    dev = wait_for_device(log_cb, is_cancelled_cb)
    cpid = dev["cpid"]

    progress_cb(25, step="Pwn Device", detail="gaster pwn + USB reset")
    _pwn_and_settle(log_cb, is_cancelled_cb)

    progress_cb(50, step="Send Bootchain", detail="iBSS -> iBEC")
    native_tool("irecovery", ["-f", os.path.join("sshramdisk", "iBSS.img4")],
                log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                context="irecovery (iBSS)")
    _sleep(2, is_cancelled_cb)
    native_tool("irecovery", ["-f", os.path.join("sshramdisk", "iBEC.img4")],
                log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                context="irecovery (iBEC)")
    if cpid in GO_AFTER_IBEC:
        native_tool("irecovery", ["-c", "go"], log_cb=log_cb,
                    is_cancelled_cb=is_cancelled_cb, context="irecovery go")
    _sleep(2, is_cancelled_cb)

    progress_cb(75, step="Erase Device", detail="oblit-inprogress 5")
    native_tool("irecovery", ["-c", "setenv oblit-inprogress 5"], log_cb=log_cb,
                is_cancelled_cb=is_cancelled_cb, context="irecovery setenv")
    native_tool("irecovery", ["-c", "saveenv"], log_cb=log_cb,
                is_cancelled_cb=is_cancelled_cb, context="irecovery saveenv")
    native_tool("irecovery", ["-c", "reset"], log_cb=log_cb,
                is_cancelled_cb=is_cancelled_cb, context="irecovery reset")
    log_cb("[*] Device should now show a progress bar and erase all data.")
    progress_cb(100, step="Erase Device", detail="Erase requested.")


def op_reboot(
    progress_cb: ProgressCb, log_cb: LogCb, is_cancelled_cb: CancelCb,
) -> None:
    progress_cb(10, step="Connect", detail="Starting iproxy...")
    try:
        start_iproxy(log_cb)
        _check_cancel(is_cancelled_cb)
        progress_cb(60, step="Reboot Device", detail="ssh /sbin/reboot")
        rc, _ = ssh_exec("/sbin/reboot", timeout=20)
        if rc != 0:
            raise RamdiskError(f"reboot command exited {rc}.")
        log_cb("[*] Device should now reboot.")
        progress_cb(100, step="Reboot Device", detail="Reboot sent.")
    finally:
        stop_iproxy()


def op_dump_blobs(
    output_path: str, progress_cb: ProgressCb, log_cb: LogCb,
    is_cancelled_cb: CancelCb,
) -> None:
    progress_cb(10, step="Connect", detail="Starting iproxy...")
    try:
        start_iproxy(log_cb)
        _check_cancel(is_cancelled_cb)
        progress_cb(40, step="Detect OS", detail="sw_vers over ssh...")
        rc, osname = ssh_exec("sw_vers -productName", timeout=20)
        if rc != 0:
            raise RamdiskError(
                "SSH into the ramdisk failed — boot the ramdisk first.")
        osname = osname.strip()
        if osname == "Bridge OS":
            raise RamdiskError("BridgeOS not supported!")
        rc, osver = ssh_exec("sw_vers -productVersion", timeout=20)
        major = 0
        try:
            major = int(osver.strip().split(".")[0])
        except (ValueError, IndexError):
            pass
        device = "rdisk2" if major >= 16 else "rdisk1"
        log_cb(f"[*] {osname} {osver.strip()} -> /dev/{device}")

        _check_cancel(is_cancelled_cb)
        progress_cb(70, step="Dump Blobs", detail=f"Reading /dev/{device}...")
        raw = _ssh_read_bytes(f"cat /dev/{device}", 0x4000 * 256,
                              is_cancelled_cb)
        if len(raw) < 4096:
            raise RamdiskError(
                f"Unexpected dump size ({len(raw)} bytes) — is the ramdisk booted?")
        dump_path = os.path.join(run_root(), "dump.raw")
        with open(dump_path, "wb") as fh:
            fh.write(raw)

        progress_cb(90, step="Dump Blobs", detail="img4tool --convert...")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        wsl_tool("img4tool", ["--convert", "-s", output_path, dump_path],
                 cwd=run_root(), log_cb=log_cb, is_cancelled_cb=is_cancelled_cb,
                 context="img4tool --convert")
        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            raise RamdiskError("img4tool did not produce a .shsh2 output.")
        log_cb(f"[*] Onboard blobs dumped to {output_path}")
        progress_cb(100, step="Dump Blobs", detail=output_path)
    finally:
        stop_iproxy()


def _ssh_read_bytes(
    command: str, limit: int, is_cancelled_cb: CancelCb,
) -> bytes:
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            "127.0.0.1", port=2222, username="root", password="alpine",
            timeout=15, banner_timeout=15, auth_timeout=15,
            allow_agent=False, look_for_keys=False,
        )
        _, stdout, _ = client.exec_command(command, timeout=60)
        chunks = []
        got = 0
        while got < limit:
            _check_cancel(is_cancelled_cb)
            data = stdout.read(min(65536, limit - got))
            if not data:
                break
            chunks.append(data)
            got += len(data)
        stdout.channel.close()
        return b"".join(chunks)
    finally:
        client.close()


def op_clean(progress_cb: ProgressCb, log_cb: LogCb,
             is_cancelled_cb: CancelCb) -> None:
    progress_cb(30, step="Clean Workspace", detail="Removing work + sshramdisk")
    shutil.rmtree(work_dir(), ignore_errors=True)
    shutil.rmtree(td_dir_12(), ignore_errors=True)
    shutil.rmtree(sshramdisk_dir(), ignore_errors=True)
    log_cb("[*] Removed the current created SSH ramdisk")
    progress_cb(100, step="Clean Workspace", detail="Done.")


def open_ssh_console(log_cb: LogCb) -> None:
    start_iproxy(log_cb)
    ssh_exe = shutil.which("ssh")
    if not ssh_exe:
        stop_iproxy()
        raise RamdiskError(
            "Windows OpenSSH client (ssh.exe) not found — enable the "
            "'OpenSSH Client' optional feature to use the SSH console.")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        [ssh_exe, "-p", "2222", "-o", "StrictHostKeyChecking=no",
         "-o", "UserKnownHostsFile=NUL", "root@127.0.0.1"],
        cwd=run_root(), creationflags=creationflags | getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )

    def watcher():
        proc.wait()
        stop_iproxy()

    threading.Thread(target=watcher, daemon=True).start()
    log_cb("[*] SSH console opened (root@localhost:2222).")


def default_dump_path() -> str:
    return os.path.join(documents_dir(), "Pymobile3-GUI", "dumped.shsh2")
