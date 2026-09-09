# =============================================================================
# Pymobile3-GUI — Streaming Process Runner
#
# QProcess-backed runner for long operations (device backups, restores, IPSW
# flashing, bulk pulls) that must NOT be wrapped in a fixed timeout.
#
# safe_run_command() is fine for quick queries, but it blocks until exit and
# kills the child at its timeout — a full iOS backup can run for an hour, so a
# 300s cap silently corrupts the operation. This runner instead streams output
# live, parses progress, and only ends when the process actually ends.
# =============================================================================

import os
import re
import sys
import time

from PySide6.QtCore import QObject, QProcess, Signal


# tqdm-style bars ("  45%|████▌     | 450/1000 [00:10<00:12, 44.5it/s]") and
# plain "45%" / "Progress: 45.0%" forms.
_PERCENT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
# "450/1000" item counters
_COUNT_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")


class StreamingProcessRunner(QObject):
    """
    Runs a command, streaming its output and progress.

    Signals:
        progress(int):        0-100, or -1 when the total is unknown.
        status(str):          Short human-readable current step.
        output(str):          Raw output line for the log view.
        finished(bool, str):  (success, summary message).
    """

    progress = Signal(int)
    status = Signal(str)
    output = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._buffer = ""
        self._started_at = 0.0
        self._cancelled = False
        self._last_percent = -1

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def is_running(self) -> bool:
        return (self._proc is not None
                and self._proc.state() != QProcess.ProcessState.NotRunning)

    def start(self, args: list[str], env: dict | None = None,
              use_module: bool = True):
        """
        Launch a pymobiledevice3 (or arbitrary) command.

        Args:
            args:       Arguments after the interpreter, e.g.
                        ["-m", "pymobiledevice3", "backup2", "backup", path]
                        or a full argv when use_module is False.
            env:        Environment overrides (e.g. tunnel routing).
            use_module: Prepend sys.executable.
        """
        if self.is_running():
            self.finished.emit(False, "Another operation is already running.")
            return

        self._cancelled = False
        self._buffer = ""
        self._last_percent = -1
        self._started_at = time.time()

        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._proc.readyRead.connect(self._on_ready_read)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error)

        proc_env = self._proc.processEnvironment()
        from PySide6.QtCore import QProcessEnvironment
        proc_env = QProcessEnvironment.systemEnvironment()
        # Unbuffered output so progress arrives live rather than at exit.
        proc_env.insert("PYTHONUNBUFFERED", "1")
        proc_env.insert("PYTHONIOENCODING", "utf-8")
        for key, value in (env or {}).items():
            proc_env.insert(key, str(value))
        self._proc.setProcessEnvironment(proc_env)

        if use_module:
            program, arguments = sys.executable, args
        else:
            program, arguments = args[0], args[1:]

        self.status.emit("Starting…")
        self.progress.emit(-1)
        self._proc.start(program, arguments)

    def cancel(self):
        """Terminate the running operation."""
        if not self.is_running():
            return
        self._cancelled = True
        self.status.emit("Cancelling…")
        self._proc.terminate()
        # Escalate if it does not exit promptly.
        if not self._proc.waitForFinished(3000):
            self._proc.kill()

    # -------------------------------------------------------------------------
    # Streaming
    # -------------------------------------------------------------------------

    def _on_ready_read(self):
        if not self._proc:
            return
        chunk = bytes(self._proc.readAll()).decode("utf-8", errors="replace")
        self._buffer += chunk

        # Progress bars rewrite the line with \r — treat both as separators.
        parts = re.split(r"[\r\n]", self._buffer)
        self._buffer = parts.pop() if parts else ""

        for line in parts:
            line = line.rstrip()
            if not line:
                continue
            self._parse_line(line)

    def _parse_line(self, line: str):
        """Extract progress from a line and forward it."""
        percent = None

        match = _PERCENT_RE.search(line)
        if match:
            try:
                percent = max(0, min(100, int(float(match.group(1)))))
            except ValueError:
                percent = None

        if percent is None:
            counted = _COUNT_RE.search(line)
            if counted:
                done, total = int(counted.group(1)), int(counted.group(2))
                if total > 0:
                    percent = max(0, min(100, int(done * 100 / total)))

        if percent is not None and percent != self._last_percent:
            self._last_percent = percent
            self.progress.emit(percent)

        # Keep the status line short — the log view carries full detail.
        self.status.emit(line[:120])
        self.output.emit(line)

    # -------------------------------------------------------------------------
    # Completion
    # -------------------------------------------------------------------------

    def _on_finished(self, exit_code: int, _exit_status):
        # Flush any partial trailing line.
        if self._buffer.strip():
            self._parse_line(self._buffer.strip())
            self._buffer = ""

        elapsed = self._format_elapsed()

        if self._cancelled:
            self.finished.emit(False, f"Cancelled by user after {elapsed}.")
        elif exit_code == 0:
            self.progress.emit(100)
            self.finished.emit(True, f"Completed successfully in {elapsed}.")
        else:
            self.finished.emit(False, f"Failed with exit code {exit_code} after {elapsed}.")

        self._proc = None

    def _on_error(self, error):
        messages = {
            QProcess.ProcessError.FailedToStart:
                "Failed to start — is Python or pymobiledevice3 available?",
            QProcess.ProcessError.Crashed: "The process crashed.",
            QProcess.ProcessError.Timedout: "The process timed out.",
            QProcess.ProcessError.WriteError: "Write error.",
            QProcess.ProcessError.ReadError: "Read error.",
        }
        # A terminate() we requested surfaces as Crashed — not a real error.
        if self._cancelled:
            return
        self.output.emit(f"[error] {messages.get(error, 'Unknown process error.')}")

    def elapsed_seconds(self) -> float:
        return time.time() - self._started_at if self._started_at else 0.0

    def _format_elapsed(self) -> str:
        return format_duration(self.elapsed_seconds())


def format_duration(seconds: float) -> str:
    """Render a duration as 45s / 3m 12s / 1h 04m."""
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"
