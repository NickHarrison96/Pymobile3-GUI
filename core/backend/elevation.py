# =============================================================================
# Pymobile3-GUI — Elevation Helpers
#
# Pymobile3-GUI deliberately launches UNELEVATED. Only a handful of operations
# actually need Administrator (the iOS tunnel interface, SFC, DISM, and
# machine-scope winget installs) — forcing a UAC prompt on every single
# launch to cover those was pure friction for the ~90% of sessions that
# never touch them.
#
# So elevation is requested at the moment it is needed:
#   * the iOS tunnel elevates just the tunneld process
#     (utils/ios_core/tunnel_manager.py — unchanged, it already did this)
#   * admin-only shell tools offer to relaunch the app elevated, via
#     components/terminal_widget.py's requires_admin path
# =============================================================================

import ctypes
import os
import sys


def is_admin() -> bool:
    """True when the current process is elevated (Administrator / root)."""
    if sys.platform == "win32":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def relaunch_as_admin() -> tuple[bool, str]:
    """
    Relaunch Pymobile3-GUI elevated via UAC. The caller is expected to quit the
    current (unelevated) instance once this returns success — the two must
    not run side by side.

    Windows only, on purpose: running a whole Linux/macOS GUI app as root is
    bad practice, and neither platform needs it here. Those platforms elevate
    per-operation instead (see tunnel_manager's osascript/pkexec paths).

    Returns (started, message).
    """
    if sys.platform != "win32":
        return False, (
            "Automatic relaunch is Windows-only. Restart Pymobile3-GUI with "
            "sudo/root privileges if a tool reports it needs them."
        )

    script = os.path.abspath(sys.argv[0])
    workdir = os.path.dirname(script) or os.getcwd()
    params = " ".join(f'"{arg}"' for arg in [script, *sys.argv[1:]])

    try:
        # ShellExecuteW with the "runas" verb is what raises the UAC prompt.
        # Values <= 32 are error codes, not handles.
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, workdir, 1
        )
    except Exception as e:
        return False, f"Could not request elevation: {e}"

    if rc > 32:
        return True, "Restarting Pymobile3-GUI as Administrator…"
    if rc == 5:  # SE_ERR_ACCESSDENIED — the user dismissed the UAC dialog
        return False, "Elevation was declined."
    return False, f"Elevation failed (ShellExecute code {rc})."
