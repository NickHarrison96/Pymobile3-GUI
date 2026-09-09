# =============================================================================
# Pymobile3-GUI — iOS 17+ RemoteXPC / RSD Tunnel Manager
#
# Why this exists:
#   From iOS 17 onward Apple moved every developer service (DVT instruments,
#   proclist, screenshot, location simulation, app launch, ...) behind
#   RemoteXPC, reachable only through an RSD tunnel. A bare
#   `pymobiledevice3 developer dvt ...` call fails on iOS 17+ with
#   "Make sure you passed the --rsd option".
#
# Approach:
#   Run pymobiledevice3's `remote tunneld` daemon once, elevated (creating the
#   virtual network interface needs Administrator on Windows / root on
#   macOS+Linux). Every later command then routes through it via the
#   PYMOBILEDEVICE3_TUNNEL environment variable, so individual call sites do
#   not need --rsd host/port plumbing.
# =============================================================================

import ctypes
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request

TUNNELD_HOST = "127.0.0.1"
TUNNELD_PORT = 49151
TUNNELD_URL = f"http://{TUNNELD_HOST}:{TUNNELD_PORT}"

# Minimum iOS major version that requires a tunnel for developer services
RSD_REQUIRED_MAJOR = 17


# Single implementation lives in pymobile3_gui/core/backend/elevation.py so the
# app-wide elevation logic and this module can't drift apart. Re-exported here
# because the Developer view imports is_admin from this module.
from pymobile3_gui.core.backend.elevation import is_admin  # noqa: E402,F401


def needs_tunnel(product_version: str | None) -> bool:
    """True when this iOS version puts developer services behind RSD."""
    if not product_version:
        return False
    try:
        return int(str(product_version).split(".")[0]) >= RSD_REQUIRED_MAJOR
    except (ValueError, IndexError):
        return False


class TunneldManager:
    """
    Manages the pymobiledevice3 tunneld daemon and exposes the environment
    needed for developer commands to reach a device over RSD.

    Usage:
        tm = TunneldManager()
        if not tm.is_running():
            ok, msg = tm.start()          # prompts for elevation
        env = tm.tunnel_env(udid)         # pass to safe_run_command(env=...)
    """

    def __init__(self, log_callback=None):
        self._log = log_callback or (lambda _msg: None)
        self._proc = None
        self._started_by_us = False

    # -------------------------------------------------------------------------
    # State
    # -------------------------------------------------------------------------

    def is_running(self, timeout: float = 1.5) -> bool:
        """True when a tunneld daemon is answering locally."""
        try:
            with urllib.request.urlopen(TUNNELD_URL, timeout=timeout):
                return True
        except urllib.error.HTTPError:
            # Daemon answered (any status) — it is alive.
            return True
        except Exception:
            return False

    def list_devices(self, timeout: float = 3.0) -> dict:
        """Return tunneld's view of reachable devices ({} when unavailable)."""
        try:
            with urllib.request.urlopen(TUNNELD_URL, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception:
            return {}

    def rsd_for(self, udid: str) -> tuple[str, int] | None:
        """Return (host, port) of the RSD endpoint for a UDID, if tunneld has one."""
        devices = self.list_devices()
        entry = devices.get(udid)
        # tunneld returns {udid: [{"tunnel-address": host, "tunnel-port": port}, ...]}
        if isinstance(entry, list) and entry:
            entry = entry[0]
        if isinstance(entry, dict):
            host = entry.get("tunnel-address")
            port = entry.get("tunnel-port")
            if host and port:
                return host, int(port)
        return None

    # -------------------------------------------------------------------------
    # Environment injection
    # -------------------------------------------------------------------------

    @staticmethod
    def tunnel_env(udid: str | None = None) -> dict:
        """
        Environment overrides that make pymobiledevice3 route developer
        commands through tunneld. Pass to safe_run_command(env=...).
        """
        # An empty value tells pymobiledevice3 to use the only tunneld device.
        return {"PYMOBILEDEVICE3_TUNNEL": udid or ""}

    @staticmethod
    def rsd_args(host: str, port: int) -> list[str]:
        """Explicit --rsd arguments, for call sites that prefer them."""
        return ["--rsd", host, str(port)]

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def start(self, wait_seconds: int = 25) -> tuple[bool, str]:
        """
        Start tunneld, elevating if required, then wait until it answers.

        Elevation shows a UAC prompt on Windows (or an auth prompt on
        macOS/Linux) — creating the tunnel interface cannot work without it.
        """
        if self.is_running():
            return True, "tunneld is already running."

        try:
            if is_admin():
                ok, msg = self._spawn_direct()
            else:
                ok, msg = self._spawn_elevated()
            if not ok:
                return False, msg
        except Exception as e:
            return False, f"Failed to launch tunneld: {e}"

        # Poll for readiness — the daemon needs a moment to bind.
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if self.is_running():
                self._started_by_us = True
                return True, "tunneld started."
            time.sleep(1.0)

        return False, (
            f"tunneld did not respond on {TUNNELD_URL} within {wait_seconds}s. "
            "If a UAC/authentication prompt appeared, it may have been declined."
        )

    def _tunneld_cmd(self) -> list[str]:
        return [sys.executable, "-m", "pymobiledevice3", "remote", "tunneld"]

    def _spawn_direct(self) -> tuple[bool, str]:
        """Start tunneld in-process (already privileged)."""
        creationflags = 0
        if os.name == "nt":
            creationflags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            )
        self._proc = subprocess.Popen(
            self._tunneld_cmd(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self._log(f"[tunnel] tunneld launched (pid {self._proc.pid})")
        return True, "tunneld launched."

    def _spawn_elevated(self) -> tuple[bool, str]:
        """Start tunneld with an elevation prompt."""
        system = platform.system()

        if system == "Windows":
            # Start-Process -Verb RunAs raises the UAC prompt.
            args = ",".join(f"'{a}'" for a in self._tunneld_cmd()[1:])
            ps = (
                f"Start-Process -FilePath '{sys.executable}' "
                f"-ArgumentList {args} -Verb RunAs -WindowStyle Hidden"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, text=True, timeout=60,
            )
            if res.returncode != 0:
                err = (res.stderr or "").strip()
                if "canceled by the user" in err.lower() or "cancelled" in err.lower():
                    return False, "Elevation was declined — tunneld needs Administrator."
                return False, f"Elevation failed: {err or 'unknown error'}"
            self._log("[tunnel] tunneld launched elevated (UAC approved)")
            return True, "tunneld launched elevated."

        if system == "Darwin":
            cmd = " ".join(self._tunneld_cmd())
            script = f'do shell script "{cmd} > /dev/null 2>&1 &" with administrator privileges'
            res = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=60,
            )
            if res.returncode != 0:
                return False, f"Authorization failed: {(res.stderr or '').strip()}"
            return True, "tunneld launched with administrator privileges."

        # Linux — prefer pkexec (graphical prompt), fall back to sudo.
        launcher = "pkexec" if _which("pkexec") else "sudo"
        try:
            self._proc = subprocess.Popen(
                [launcher] + self._tunneld_cmd(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return False, "Neither pkexec nor sudo is available to elevate tunneld."
        return True, f"tunneld launched via {launcher}."

    def stop(self) -> tuple[bool, str]:
        """Stop a tunneld we started. Elevated daemons need matching privileges."""
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
            self._started_by_us = False
            return True, "tunneld stopped."

        if not self._started_by_us:
            return False, "tunneld was not started by this application."
        return False, "tunneld runs elevated; stop it from an elevated shell."

    # -------------------------------------------------------------------------
    # Preflight
    # -------------------------------------------------------------------------

    def preflight(self, product_version: str | None = None) -> list[dict]:
        """
        Report every precondition for iOS 17+ developer services.

        Returns a list of {name, ok, detail, fix} dicts for UI rendering.
        """
        checks: list[dict] = []

        admin = is_admin()
        checks.append({
            "name": "Administrator privileges",
            "ok": admin,
            "detail": "Required to create the tunnel network interface."
                      if not admin else "Running elevated.",
            "fix": "Restart Pymobile3-GUI as Administrator, or approve the UAC prompt "
                   "when starting the tunnel.",
        })

        running = self.is_running()
        checks.append({
            "name": "tunneld daemon",
            "ok": running,
            "detail": f"Listening on {TUNNELD_URL}." if running
                      else "Not running — developer services will fail.",
            "fix": "Open the Developer view and press 'Start Tunnel'.",
        })

        if product_version:
            required = needs_tunnel(product_version)
            checks.append({
                "name": f"iOS {product_version} tunnel requirement",
                "ok": True,
                "detail": "iOS 17+ — developer services require RSD."
                          if required else
                          "Pre-iOS 17 — developer services work without a tunnel.",
                "fix": "",
            })

        return checks


def _which(name: str) -> str | None:
    """Minimal shutil.which wrapper kept local to avoid an extra import cost."""
    from shutil import which
    return which(name)


# =============================================================================
# Shared instance + developer-command helper
# =============================================================================

_manager: TunneldManager | None = None


def get_tunnel_manager() -> TunneldManager:
    """Process-wide TunneldManager so every dialog shares one daemon."""
    global _manager
    if _manager is None:
        _manager = TunneldManager()
    return _manager


TUNNEL_HINT = (
    "This is an iOS 17+ developer service and needs an active RSD tunnel.\n"
    "Open the Developer view and press 'Start Tunnel',\n"
    "then make sure Developer Mode is enabled and the DDI is mounted."
)


def run_developer_command(args: list[str], timeout: int = 20,
                          udid: str | None = None,
                          require_tunnel: bool = True) -> tuple[bool, str]:
    """
    Run a `pymobiledevice3 developer ...` style command through the tunnel.

    Args:
        args: pymobiledevice3 arguments, e.g. ["developer", "dvt", "proclist"].
        udid: Target device; omit to use tunneld's only device.
        require_tunnel: Fail fast with guidance when no tunnel is up.

    Returns:
        (ok, output) — on failure the output carries actionable guidance.
    """
    from pymobile3_gui.core.backend.resource_manager import safe_run_command

    tm = get_tunnel_manager()
    tunnel_up = tm.is_running()

    if require_tunnel and not tunnel_up:
        return False, (
            "No RSD tunnel is running.\n\n" + TUNNEL_HINT
        )

    env = tm.tunnel_env(udid) if tunnel_up else None
    cmd = [sys.executable, "-m", "pymobiledevice3"] + args
    ok, out = safe_run_command(cmd, timeout=timeout, env=env)

    if not ok and "--rsd" in out:
        out = f"{out}\n\n{TUNNEL_HINT}"
    return ok, out
