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
#
# The tunnel runs persistently in the background until explicitly stopped
# by the user or when the application exits.
# =============================================================================

import ctypes
import json
import logging
import os
import platform
import subprocess
import sys
import time
import threading
import urllib.error
import urllib.request
from typing import Optional

TUNNELD_HOST = "127.0.0.1"
TUNNELD_PORT = 49151
TUNNELD_URL = f"http://{TUNNELD_HOST}:{TUNNELD_PORT}"

# pymobiledevice3 reads its --tunnel option from this variable
# (pymobiledevice3.cli.cli_common.TUNNEL_ENV_VAR).
#
# It MUST carry a concrete UDID. click discards empty-string environment values
# (Parameter.resolve_envvar_value does `if rv:` before returning), so exporting
# PYMOBILEDEVICE3_TUNNEL="" does not mean "use the only tunneld device" — it means
# the option is never set at all and the command silently bypasses the tunnel.
TUNNEL_ENV_VAR = "PYMOBILEDEVICE3_TUNNEL"

# Minimum iOS major version that requires a tunnel for developer services
RSD_REQUIRED_MAJOR = 17

# Health check interval (seconds)
HEALTH_CHECK_INTERVAL = 10

logger = logging.getLogger(__name__)

# Single implementation lives in pymobile3_gui/core/backend/elevation.py so the
# app-wide elevation logic and this module can't drift apart. Re-exported here
# because the Developer view imports is_admin from this module.
from pymobile3_gui.core.backend.elevation import is_admin  # noqa: E402,F401

# Process manager for PID tracking
from pymobile3_gui.core.process_manager import (
    set_tunneld_pid, register_child_pid, unregister_child_pid
)


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

    The tunnel runs persistently in the background until explicitly stopped
    by the user or when the application exits.

    Usage:
        tm = TunneldManager()
        if not tm.is_running():
            ok, msg = tm.start()          # prompts for elevation
        env = tm.tunnel_env(udid)         # pass to safe_run_command(env=...)
    """

    def __init__(self, log_callback=None):
        # Default to the module logger rather than a no-op: a swallowed
        # "tunnel died" line is the difference between a diagnosable failure
        # and a silent one.
        self._log = log_callback or logger.info
        self._proc = None
        self._started_by_us = False
        self._elevated_pid: Optional[int] = None
        self._health_thread: Optional[threading.Thread] = None
        self._stop_health_check = threading.Event()
        self._lock = threading.Lock()

    def set_log_callback(self, log_callback) -> None:
        """Re-point tunnel diagnostics, e.g. into the Developer view console."""
        self._log = log_callback or logger.info

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

    def get_status(self) -> dict:
        """Get detailed tunnel status for UI."""
        running = self.is_running()
        devices = self.list_devices() if running else {}
        return {
            "running": running,
            "started_by_us": self._started_by_us,
            "elevated": self._elevated_pid is not None,
            "devices": devices,
            "url": TUNNELD_URL,
        }

    # -------------------------------------------------------------------------
    # Environment injection
    # -------------------------------------------------------------------------

    def resolve_udid(self, udid: str | None = None) -> str | None:
        """
        Concrete UDID to route through tunneld.

        Returns None when tunneld exposes no device, or more than one and the
        caller did not say which — both cases need surfacing rather than a guess.
        """
        if udid:
            return udid
        devices = self.list_devices()
        if len(devices) == 1:
            return next(iter(devices))
        if len(devices) > 1:
            self._log(
                f"[tunnel] {len(devices)} devices visible to tunneld; "
                "caller must specify a UDID"
            )
        return None

    def tunnel_env(self, udid: str | None = None) -> dict:
        """
        Environment overrides that make pymobiledevice3 route developer
        commands through tunneld. Pass to safe_run_command(env=...).

        Returns {} when no single device can be resolved — never a blank
        PYMOBILEDEVICE3_TUNNEL, which click would drop (see TUNNEL_ENV_VAR).
        """
        resolved = self.resolve_udid(udid)
        if not resolved:
            return {}
        return {TUNNEL_ENV_VAR: resolved}

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

        The tunnel will run persistently in the background until stop() is called
        or the application exits.
        """
        with self._lock:
            if self.is_running():
                # Check if we started it, if not mark as not started by us
                if not self._started_by_us:
                    self._log("[tunnel] Existing tunnel detected (not started by us)")
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
                    self._start_health_monitor()
                    self._log("[tunnel] Tunnel started and healthy")
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
        pid = self._proc.pid
        self._log(f"[tunnel] tunneld launched (pid {pid})")
        # Register with process manager for cleanup on exit
        register_child_pid(pid)
        set_tunneld_pid(pid)
        return True, "tunneld launched."

    def _spawn_elevated(self) -> tuple[bool, str]:
        """Start tunneld with an elevation prompt."""
        system = platform.system()

        if system == "Windows":
            # Start-Process -Verb RunAs raises the UAC prompt.
            # Note: We can't easily get the PID when using Start-Process -Verb RunAs.
            # The process will be tracked by the process_manager cleanup (taskkill /IM tunneld.exe)
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
            # Mark as elevated but we don't have the PID
            self._elevated_pid = -1  # sentinel value
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
            pid = self._proc.pid
            self._log(f"[tunnel] tunneld launched via {launcher} (pid {pid})")
            register_child_pid(pid)
            set_tunneld_pid(pid)
        except FileNotFoundError:
            return False, "Neither pkexec nor sudo is available to elevate tunneld."
        return True, f"tunneld launched via {launcher}."

    def _start_health_monitor(self):
        """Start background health check thread."""
        if self._health_thread and self._health_thread.is_alive():
            return
        self._stop_health_check.clear()
        self._health_thread = threading.Thread(
            target=self._health_check_loop,
            daemon=True,
            name="tunnel-health-monitor"
        )
        self._health_thread.start()

    def _health_check_loop(self):
        """
        Periodically verify the tunnel is still healthy.

        A single failed probe is not proof the daemon died — tunneld stops
        answering briefly while it re-enumerates a device that was just
        unplugged or re-locked. Only _on_tunnel_lost decides when to give up.
        """
        consecutive_failures = 0
        while not self._stop_health_check.wait(HEALTH_CHECK_INTERVAL):
            if self.is_running():
                if consecutive_failures:
                    self._log(
                        f"[tunnel] recovered after {consecutive_failures} "
                        "failed health check(s)"
                    )
                consecutive_failures = 0
                continue

            consecutive_failures += 1
            self._log(f"[tunnel] health check failed (x{consecutive_failures})")
            if not self._on_tunnel_lost(consecutive_failures):
                self._log("[tunnel] giving up on the tunnel; marking it down")
                with self._lock:
                    self._started_by_us = False
                    self._proc = None
                    self._elevated_pid = None
                break

    def _on_tunnel_lost(self, consecutive_failures: int) -> bool:
        """
        Decide what to do when tunneld stops answering.

        Called from the health-monitor thread after each failed probe, with the
        number of consecutive failures so far (1 on the first).

        Return True to keep monitoring (the tunnel may come back), False to stop
        monitoring and mark the tunnel down.

        TODO(nick): choose the recovery policy — see the notes in chat.
        """
        # Placeholder: tolerate two blips, then mark down. Preserves the old
        # give-up behaviour without dying on a single transient failure.
        return consecutive_failures < 3

    def stop(self) -> tuple[bool, str]:
        """Stop a tunneld we started. Elevated daemons need matching privileges."""
        with self._lock:
            # Stop health monitor
            self._stop_health_check.set()
            if self._health_thread:
                self._health_thread.join(timeout=2)
                self._health_thread = None

            if self._proc is not None:
                pid = self._proc.pid
                try:
                    self._proc.terminate()
                    self._proc.wait(timeout=5)
                except Exception:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                self._proc = None
                unregister_child_pid(pid)
                if self._elevated_pid != -1:  # not sentinel
                    set_tunneld_pid(0)
                self._started_by_us = False
                self._elevated_pid = None
                self._log("[tunnel] tunneld stopped")
                return True, "tunneld stopped."

            # If we started it elevated on Windows, we can't stop it directly
            # (it runs in a separate elevated process tree)
            if self._elevated_pid == -1:
                self._started_by_us = False
                self._elevated_pid = None
                self._log("[tunnel] Elevated tunnel cannot be stopped from unelevated process")
                return False, "Elevated tunnel running; stop it from an elevated shell or close the app to clean up."

            if not self._started_by_us:
                return False, "tunneld was not started by this application."

            return False, "tunneld not running."

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

        # Check Developer Mode status if device connected
        dev_mode_enabled = self._check_developer_mode()
        checks.append({
            "name": "Developer Mode",
            "ok": dev_mode_enabled,
            "detail": "Enabled on device." if dev_mode_enabled
                      else "Not enabled or not confirmed on device.",
            "fix": "Run 'Enable Dev Mode' in Developer view, then confirm on device "
                   "(Settings > Privacy & Security > Developer Mode) and reboot.",
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

    def _check_developer_mode(self) -> bool:
        """Check if Developer Mode is enabled on the connected device."""
        try:
            from pymobile3_gui.core.backend.resource_manager import safe_run_command
            ok, out = safe_run_command(
                [sys.executable, "-m", "pymobiledevice3", "amfi", "developer-mode-status"],
                timeout=10
            )
            if ok and out:
                # Returns "true" or "false"
                return "true" in out.lower()
        except Exception:
            pass
        return False


def _which(name: str) -> str | None:
    """Minimal shutil.which wrapper kept local to avoid an extra import cost."""
    from shutil import which
    return which(name)


# =============================================================================
# Shared instance + developer-command helper
# =============================================================================

_manager: TunneldManager | None = None


def get_tunnel_manager(log_callback=None) -> TunneldManager:
    """
    Process-wide TunneldManager so every dialog shares one daemon.

    Pass log_callback once (e.g. from the Developer view) to route tunnel
    diagnostics into the UI console; later calls may re-point it.
    """
    global _manager
    if _manager is None:
        _manager = TunneldManager(log_callback=log_callback)
    elif log_callback is not None:
        _manager.set_log_callback(log_callback)
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

    # A running daemon that exposes no resolvable device would otherwise run the
    # command with no --tunnel at all, which fails deep inside pymobiledevice3
    # with an unrelated "pass the --rsd option" message.
    if require_tunnel and not env:
        devices = tm.list_devices()
        if not devices:
            return False, (
                "The tunnel is running but has not picked up a device yet.\n\n"
                "Check the device is unlocked and trusted, then retry. "
                "iOS 17+ devices can take a few seconds to appear after the "
                "tunnel starts.\n\n" + TUNNEL_HINT
            )
        return False, (
            f"{len(devices)} devices are visible to the tunnel "
            f"({', '.join(sorted(devices))}).\n\n"
            "Disconnect the others, or pass an explicit UDID."
        )

    cmd = [sys.executable, "-m", "pymobiledevice3"] + args
    ok, out = safe_run_command(cmd, timeout=timeout, env=env)

    if not ok:
        # Check for common failure patterns and add guidance
        if "--rsd" in out or "pass --tunnel" in out or "Make sure you passed the --rsd option" in out:
            out = f"{out}\n\n{TUNNEL_HINT}"
        elif "Developer Mode" in out and "enable-developer-mode" in out:
            out = f"{out}\n\n[TIP] Run 'Enable Dev Mode' in the Developer view, then confirm on device (Settings > Privacy & Security > Developer Mode) and reboot."
        elif "DeveloperDiskImage" in out or "mounter auto-mount" in out:
            out = f"{out}\n\n[TIP] Run 'Auto-Mount DDI' in the Developer view to mount the Developer Disk Image."

    return ok, out