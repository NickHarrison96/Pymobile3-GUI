"""
Pymobile3-GUI - Process Management
Handles single-instance enforcement and cleanup of child processes/services on exit.
"""
import os
import sys
import subprocess
import signal
import atexit
from typing import List, Set

# Global tracking of child processes
_child_pids: Set[int] = set()
_tunneld_pid: int = 0


def _get_current_process_name() -> str:
    """Get the executable name for this process."""
    if getattr(sys, "frozen", False):
        return os.path.basename(sys.executable)
    return os.path.basename(sys.argv[0])


def _find_other_instances() -> List[int]:
    """Find PIDs of other running instances of this app."""
    current_pid = os.getpid()
    current_name = _get_current_process_name()
    pids = []

    if sys.platform == "win32":
        try:
            # Use tasklist to find processes
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {current_name}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
            )
            for line in result.stdout.strip().splitlines():
                if line:
                    parts = line.split(",")
                    if len(parts) >= 2:
                        pid = int(parts[1].strip('"'))
                        if pid != current_pid:
                            pids.append(pid)
        except Exception:
            pass
    else:
        try:
            # Use pgrep on Unix
            result = subprocess.run(
                ["pgrep", "-f", current_name],
                capture_output=True, text=True
            )
            for line in result.stdout.strip().splitlines():
                pid = int(line.strip())
                if pid != current_pid:
                    pids.append(pid)
        except Exception:
            pass

    return pids


def kill_other_instances() -> int:
    """Kill all other instances of this application. Returns count killed."""
    pids = _find_other_instances()
    killed = 0

    for pid in pids:
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                os.kill(pid, signal.SIGTERM)
            killed += 1
        except Exception:
            pass

    return killed


def register_child_pid(pid: int):
    """Register a child PID for cleanup on exit."""
    _child_pids.add(pid)


def unregister_child_pid(pid: int):
    """Unregister a child PID (e.g., after clean exit)."""
    _child_pids.discard(pid)


def set_tunneld_pid(pid: int):
    """Track the tunneld daemon PID for cleanup."""
    global _tunneld_pid
    _tunneld_pid = pid
    if pid:
        _child_pids.add(pid)


def _kill_process_tree(pid: int):
    """Kill a process and its children."""
    try:
        if sys.platform == "win32":
            # Use taskkill /T to kill tree
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW
            )
        else:
            # Kill process group
            os.killpg(os.getpgid(pid), signal.SIGTERM)
    except Exception:
        pass


def cleanup_all():
    """Kill all tracked child processes and services."""
    # Kill tunneld specifically if we started it
    if _tunneld_pid:
        _kill_process_tree(_tunneld_pid)

    # Kill all other registered child processes
    for pid in list(_child_pids):
        if pid != _tunneld_pid:
            _kill_process_tree(pid)

    # Also kill any remaining pymobiledevice3 tunneld daemons we might have started
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/IM", "tunneld.exe"],
                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW
            )
        else:
            subprocess.run(["pkill", "-f", "pymobiledevice3.*tunneld"], capture_output=True)
    except Exception:
        pass


# Register cleanup on exit
atexit.register(cleanup_all)

# Also handle signals for cleaner shutdown
def _signal_handler(signum, frame):
    cleanup_all()
    sys.exit(0)

if sys.platform != "win32":
    try:
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)
    except Exception:
        pass