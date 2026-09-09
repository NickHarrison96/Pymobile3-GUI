# =============================================================================
# Pymobile3-GUI — Resource Manager, Core Allocator & Subprocess Runner
# =============================================================================

import sys
import os
import subprocess
import traceback
from PySide6.QtCore import QThreadPool

try:
    import psutil
except ImportError:
    psutil = None


def calculate_allocated_cores() -> int:
    """
    Determines thread allocation according to target core topology:
    - 6c / 6t   -> 2 threads
    - 6c / 12t+ -> 3 threads
    - < 6 cores -> 1 or 2 threads
    """
    try:
        cores = psutil.cpu_count(logical=False) if psutil else (os.cpu_count() or 4)
        threads = psutil.cpu_count(logical=True) if psutil else (os.cpu_count() or 4)

        if cores == 6 and threads == 6:
            return 2
        elif cores >= 6 and threads >= 12:
            return 3
        elif cores < 6:
            return 1 if threads <= 2 else 2
        else:
            return 3
    except Exception:
        return 2  # Safe fallback default


def configure_global_thread_pool() -> int:
    """Configures QThreadPool global instance max worker count."""
    allocated = calculate_allocated_cores()
    pool = QThreadPool.globalInstance()
    pool.setMaxThreadCount(allocated)
    return allocated


def safe_run_command(cmd: list[str], timeout: int = 10,
                     env: dict | None = None) -> tuple[bool, str]:
    """
    Executes CLI processes with strict timeout and exception handling
    to ensure worker threads never hang indefinitely.
    Suppresses console window popups on Windows.

    Args:
        env: Optional environment overrides merged onto the current environment.
             Used to inject PYMOBILEDEVICE3_TUNNEL for iOS 17+ developer commands.
    """
    try:
        startupinfo = None
        creationflags = 0
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)

        run_env = None
        if env:
            run_env = {**os.environ, **env}

        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            # Without an explicit codec Python uses the Windows ANSI codepage
            # (cp1252), which raises UnicodeDecodeError on tool output carrying
            # UTF-8 or raw bytes — e.g. `lockdown info --domain ...battery`.
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            startupinfo=startupinfo,
            creationflags=creationflags,
            env=run_env,
            check=False
        )
        if res.returncode == 0:
            return True, (res.stdout or "").strip()
        else:
            err = (res.stderr or "").strip() or f"Process exited with code {res.returncode}"
            return False, err
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s: {' '.join(cmd)}"
    except FileNotFoundError:
        return False, f"Executable binary not found: {cmd[0]}"
    except Exception as e:
        return False, f"Subprocess exception: {str(e)}"


def install_global_crash_handler(log_callback=None):
    """Intercepts unhandled Python exceptions and forwards reports to the GUI console."""
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        crash_report = f"\n[!] CRITICAL EXCEPTION TRAPPED:\n{err_msg}"

        if log_callback:
            try:
                log_callback(crash_report)
            except Exception:
                sys.stderr.write(crash_report)
        else:
            sys.stderr.write(crash_report)

    sys.excepthook = handle_exception
