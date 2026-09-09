# =============================================================================
# Pymobile3-GUI — Filesystem Locations
#
# One place that answers two different questions:
#
#   * where do the files we SHIP live?    -> app_dir(), resource_path()
#   * where do the files we WRITE live?   -> data_dir(), bin_dir(), backups_dir()
#
# Running from a source checkout the two are nearly the same folder, which is
# exactly why the distinction was never made. It stops being harmless once the
# app is packaged:
#
#   1. PyInstaller unpacks a onefile bundle into a TEMPORARY directory that is
#      deleted when the process exits. Anything written beside the executable —
#      downloaded platform-tools, for instance — is gone by the next launch.
#
#   2. The old code resolved paths with os.path.abspath("bin"), which is
#      relative to the CURRENT WORKING DIRECTORY, not to the app. Launched by
#      start.bat that happened to be the project folder, so it worked. Launched
#      from a Start Menu shortcut it is C:\Windows\System32, and the app would
#      try to create C:\Windows\System32\bin.
#
# So: read-only things resolve against the bundle, writable things resolve
# against a per-user directory that survives reinstalls and needs no elevation.
# =============================================================================

import os
import platform
import sys

APP_FOLDER_NAME = "Pymobile3-GUI"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle rather than source."""
    return getattr(sys, "frozen", False)


# -----------------------------------------------------------------------------
# Read-only: things we ship
# -----------------------------------------------------------------------------

def app_dir() -> str:
    """
    Root of the shipped application files (styles.qss, resources/, bin/).

    Frozen, PyInstaller sets sys._MEIPASS to the unpack directory. From source
    this is the project root — utils/ is one level down, hence the double
    dirname.
    """
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts: str) -> str:
    """Absolute path to a shipped resource, e.g. resource_path('styles.qss')."""
    return os.path.join(app_dir(), *parts)


# -----------------------------------------------------------------------------
# Writable: things we create at runtime
# -----------------------------------------------------------------------------

def config_dir() -> str:
    """
    Per-user CONFIG directory — small settings files.

    On Windows this is APPDATA (Roaming) deliberately, so per-user settings
    follow a roaming profile between machines. Bulky runtime files go in
    data_dir() (LOCALAPPDATA) instead.
    """
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif system == "Darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    path = os.path.join(base, APP_FOLDER_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def data_dir() -> str:
    """
    Per-user DATA directory — bulky runtime files (platform-tools, logs).

    LOCALAPPDATA rather than APPDATA on Windows: roaming profiles copy APPDATA
    between machines at sign-in, and a 15 MB SDK has no business being synced.
    """
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get(
            "APPDATA", os.path.expanduser("~")
        )
    elif system == "Darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get(
            "XDG_DATA_HOME", os.path.expanduser("~/.local/share")
        )
    path = os.path.join(base, APP_FOLDER_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def bin_dir() -> str:
    """Writable directory for downloaded tooling. Always under data_dir()."""
    path = os.path.join(data_dir(), "bin")
    os.makedirs(path, exist_ok=True)
    return path


def logs_dir() -> str:
    """Writable directory for logs the app generates."""
    path = os.path.join(data_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path


def documents_dir() -> str:
    """
    The user's Documents folder, falling back to home when there isn't one
    (common on Linux). Device output goes somewhere the user can actually find
    it, not into a hidden AppData folder.
    """
    candidate = os.path.normpath(os.path.expanduser("~/Documents"))
    return candidate if os.path.isdir(candidate) else os.path.expanduser("~")


def backups_dir() -> str:
    """
    Default destination for device acquisitions and backups.

    Previously <cwd>/backups, which meant real device data — PII — landed
    inside the project folder (and .gitignore has two separate rules trying to
    keep it out of git, which says everything). Now it is an explicit,
    user-visible location outside the source tree.
    """
    path = os.path.join(documents_dir(), APP_FOLDER_NAME, "backups")
    os.makedirs(path, exist_ok=True)
    return path


# -----------------------------------------------------------------------------
# Android platform-tools (adb / fastboot)
# -----------------------------------------------------------------------------

def platform_tools_install_dir() -> str:
    """
    Where the downloader extracts platform-tools to.

    Always the writable location — never beside the executable, which is
    read-only when packaged and temporary when onefile.
    """
    return os.path.join(bin_dir(), "platform-tools")


def platform_tools_candidates() -> list[str]:
    """
    Every directory that might hold adb/fastboot, in search order:
    a copy shipped inside the bundle first, then one we downloaded.
    """
    return [
        os.path.join(app_dir(), "bin", "platform-tools"),
        platform_tools_install_dir(),
    ]


def find_platform_tool(name: str) -> str | None:
    """
    Absolute path to a platform-tool binary ('adb', 'fastboot'), or None.

    Checks the shipped and downloaded locations only — callers that also want
    to honour a system-wide install should try shutil.which() first.
    """
    exe = f"{name}.exe" if os.name == "nt" else name
    for directory in platform_tools_candidates():
        candidate = os.path.join(directory, exe)
        if os.path.isfile(candidate):
            return candidate
    return None
