# =============================================================================
# Pymobile3-GUI — Resource Manager, Core Allocator & Subprocess Runner
# =============================================================================

import sys
import os
import subprocess
import threading
import time
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
                     env: dict | None = None,
                     include_stderr: bool = False) -> tuple[bool, str]:
    """
    Executes CLI processes with strict timeout and exception handling
    to ensure worker threads never hang indefinitely.
    Suppresses console window popups on Windows.

    Args:
        env: Optional environment overrides merged onto the current environment.
             Used to inject PYMOBILEDEVICE3_TUNNEL for iOS 17+ developer commands.
        include_stderr: Append stderr to the returned text on success. pymobiledevice3
             logs failures (e.g. "Developer Mode is disabled") to stderr while still
             exiting 0, so without this a failed command looks successful.
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
            out = (res.stdout or "").strip()
            if include_stderr:
                err = (res.stderr or "").strip()
                out = f"{out}\n{err}".strip() if out else err
            return True, out
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
    """
    Intercepts unhandled Python exceptions and forwards reports to the GUI
    console and a timestamped log file.

    The frozen build runs console=False, so sys.stderr is invisible — a crash
    that only went to stderr would leave nothing for a bug report. The file in
    logs_dir() (plus the optional GUI callback) is what actually survives.
    Also hooks threading.excepthook, which catches exceptions raised in
    QThread.run / plain threads that sys.excepthook never sees.
    """

    def _emit(text: str) -> None:
        if log_callback:
            try:
                log_callback(text)
            except Exception:
                pass
        try:
            from pymobile3_gui.core.backend.paths import logs_dir
            path = os.path.join(logs_dir(), time.strftime("crash-%Y%m%d-%H%M%S.log"))
            with open(path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass
        try:
            sys.stderr.write(text)
        except Exception:
            pass

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        _emit(f"\n[!] CRITICAL EXCEPTION TRAPPED:\n{err_msg}")

    def handle_thread_exception(args):
        exc_type = getattr(args, "exc_type", Exception)
        exc_value = getattr(args, "exc_value", None)
        exc_tb = getattr(args, "exc_traceback", None)
        err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _emit(f"\n[!] UNHANDLED THREAD EXCEPTION:\n{err_msg}")

    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception
