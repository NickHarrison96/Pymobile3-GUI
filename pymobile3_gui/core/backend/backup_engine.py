# =============================================================================
# Pymobile3-GUI — iOS Forensic Acquisition Engine
#
# Multi-mode device acquisition, ported from the iForensics toolkit:
#
#   logical       iTunes/Finder-style mobilebackup2 backup.
#   logical_plus  Logical backup + camera media + crash reports + app
#                 inventory, collected into a single .tar archive.
#   prfs          Partially Restored File System — the Logical+ collection
#                 without the mobilebackup2 stage, so it captures the
#                 accessible file system quickly.
#   ffs           Full File System. Requires SSH to a jailbroken device and is
#                 reported as unsupported here rather than silently degrading
#                 to a weaker acquisition.
#
# Signals intentionally mirror StreamingProcessRunner so this engine can be
# handed straight to OperationProgressPanel.bind().
# =============================================================================

import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import datetime

from PySide6.QtCore import QThread, Signal

from pymobile3_gui.core.backend.process_runner import format_duration


ACQUISITION_MODES = {
    "logical": {
        "label": "Logical",
        "summary": "iTunes/Finder-style backup (mobilebackup2).",
        "detail": "Standard backup of app data, settings, and user content.",
    },
    "logical_plus": {
        "label": "Logical+",
        "summary": "Logical backup plus media, crash logs and app inventory.",
        "detail": "Everything in Logical, then camera media, crash reports and "
                  "the installed-app inventory, archived into one .tar.",
    },
    "prfs": {
        "label": "PRFS",
        "summary": "Partially Restored File System — accessible files only.",
        "detail": "Skips the mobilebackup2 stage and collects the reachable "
                  "file system (media, crash reports, app inventory). Faster, "
                  "but does not include app data held only in the backup.",
    },
    "ffs": {
        "label": "FFS",
        "summary": "Full File System — requires a jailbroken device over SSH.",
        "detail": "Not available without SSH access to a jailbroken device.",
    },
}

# Matches tqdm-style "45%" / "45.2%" and "450/1000" item counters, so the
# underlying tool's own progress can drive the overall bar.
_PERCENT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_COUNT_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")

DEFAULT_OPTIONS = {
    "incl_media": True,
    "incl_crash": True,
    "incl_apps": True,
    "keep_intermediate": False,
}


class AcquisitionWorker(QThread):
    """
    Runs a multi-step forensic acquisition.

    Signals (matching StreamingProcessRunner so the progress panel can bind):
        progress(int)        0-100, -1 for indeterminate
        status(str)          current step
        output(str)          log line
        finished(bool, str)  (success, summary)
    """

    progress = Signal(int)
    status = Signal(str)
    output = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, mode: str, output_dir: str,
                 options: dict | None = None, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.output_dir = output_dir
        self.options = {**DEFAULT_OPTIONS, **(options or {})}
        self._cancelled = False
        self._proc: subprocess.Popen | None = None
        self._started_at = 0.0

    # -------------------------------------------------------------------------
    # Control
    # -------------------------------------------------------------------------

    def is_running(self) -> bool:
        return self.isRunning()

    def cancel(self):
        """Request cancellation; the current step is terminated."""
        self._cancelled = True
        self.status.emit("Cancelling…")
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Entry point
    # -------------------------------------------------------------------------

    def run(self):
        self._started_at = time.time()
        try:
            if self.mode == "ffs":
                self.finished.emit(False, (
                    "FFS acquisition needs SSH access to a jailbroken device, "
                    "which this build does not configure. Use Logical+ or PRFS."
                ))
                return

            os.makedirs(self.output_dir, exist_ok=True)

            if self.mode == "logical":
                ok, message = self._run_logical()
            elif self.mode in ("logical_plus", "prfs"):
                ok, message = self._run_collection(include_backup=(self.mode == "logical_plus"))
            else:
                ok, message = False, f"Unknown acquisition mode: {self.mode}"

            if self._cancelled:
                self.finished.emit(False, f"Cancelled after {self._elapsed()}.")
                return
            self.finished.emit(ok, message)

        except Exception as e:
            self.finished.emit(False, f"Acquisition failed: {e}")

    # -------------------------------------------------------------------------
    # Modes
    # -------------------------------------------------------------------------

    def _run_logical(self) -> tuple[bool, str]:
        self.output.emit("=== Logical acquisition (mobilebackup2) ===")
        self.status.emit("Creating iTunes-style backup…")
        ok = self._stream(["backup2", "backup", "--full", self.output_dir],
                          step_label="Backup", base=0, span=100)
        if not ok:
            return False, "mobilebackup2 backup failed — see the log for detail."
        self.progress.emit(100)
        return True, f"Logical backup completed in {self._elapsed()} → {self.output_dir}"

    def _run_collection(self, include_backup: bool) -> tuple[bool, str]:
        """Logical+ (with backup) or PRFS (without)."""
        mode_label = "Logical+" if include_backup else "PRFS"
        self.output.emit(f"=== {mode_label} acquisition ===")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stage_dir = os.path.join(self.output_dir, f"{mode_label.lower().rstrip('+')}_{timestamp}")
        os.makedirs(stage_dir, exist_ok=True)

        # Each action takes (base, span) so it can map its own progress onto
        # its slice of the overall bar.
        steps: list[tuple[str, callable]] = []
        if include_backup:
            steps.append(("iTunes backup", lambda b, s: self._step_backup(stage_dir, b, s)))
        if self.options["incl_media"]:
            steps.append(("Camera media", lambda b, s: self._step_media(stage_dir, b, s)))
        if self.options["incl_crash"]:
            steps.append(("Crash reports", lambda b, s: self._step_crash(stage_dir, b, s)))
        if self.options["incl_apps"]:
            steps.append(("App inventory", lambda b, s: self._step_apps(stage_dir)))

        if not steps:
            return False, "No acquisition components selected."

        completed: list[str] = []
        failed: list[str] = []

        # Weight each step evenly across 0-90%; archiving takes the last slice.
        span = 90 // len(steps)

        for index, (label, action) in enumerate(steps, start=1):
            if self._cancelled:
                return False, "Cancelled."
            base = (index - 1) * span
            self.status.emit(f"[{index}/{len(steps)}] {label}…")
            self.output.emit(f"\n[{index}/{len(steps)}] {label}")
            self.progress.emit(base)
            try:
                # Each step reports its own 0-100%, mapped into [base, base+span).
                if action(base, span):
                    completed.append(label)
                else:
                    failed.append(label)
                    self.output.emit(f"  ! {label} did not complete.")
            except Exception as e:
                failed.append(label)
                self.output.emit(f"  ! {label} error: {e}")

        if self._cancelled:
            return False, "Cancelled."

        # Archive everything collected
        self.status.emit("Creating archive…")
        self.progress.emit(92)
        archive_path = os.path.join(
            self.output_dir, f"{mode_label.lower().rstrip('+')}_{timestamp}.tar"
        )
        try:
            with tarfile.open(archive_path, "w:") as tar:
                tar.add(stage_dir, arcname=os.path.basename(stage_dir))
            self.output.emit(f"\nArchive written: {archive_path}")
        except Exception as e:
            return False, f"Collected data but archiving failed: {e}"

        if not self.options["keep_intermediate"]:
            self.status.emit("Cleaning up staging files…")
            shutil.rmtree(stage_dir, ignore_errors=True)

        self.progress.emit(100)
        size_mb = os.path.getsize(archive_path) / (1024 * 1024)
        summary = (f"{mode_label} completed in {self._elapsed()} — "
                   f"{', '.join(completed) or 'nothing'} collected "
                   f"({size_mb:.1f} MB)")
        if failed:
            summary += f"; skipped: {', '.join(failed)}"
        return True, summary

    # -------------------------------------------------------------------------
    # Steps
    # -------------------------------------------------------------------------

    def _step_backup(self, stage_dir: str, base: int = 0, span: int = 0) -> bool:
        target = os.path.join(stage_dir, "itunes_backup")
        os.makedirs(target, exist_ok=True)
        return self._stream(["backup2", "backup", "--full", target],
                            step_label="Backup", base=base, span=span)

    def _step_media(self, stage_dir: str, base: int = 0, span: int = 0) -> bool:
        target = os.path.join(stage_dir, "media")
        os.makedirs(target, exist_ok=True)
        # AFC is rooted at /var/mobile/Media, so /DCIM is the camera roll.
        return self._stream(["afc", "pull", "/DCIM", target],
                            step_label="Media", base=base, span=span)

    def _step_crash(self, stage_dir: str, base: int = 0, span: int = 0) -> bool:
        target = os.path.join(stage_dir, "crash_reports")
        os.makedirs(target, exist_ok=True)
        return self._stream(["crash", "pull", target],
                            step_label="Crash", base=base, span=span)

    def _step_apps(self, stage_dir: str) -> bool:
        target = os.path.join(stage_dir, "apps_inventory.json")
        ok, out = self._capture(["apps", "list"])
        if not ok:
            return False
        try:
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(out)
            self.output.emit(f"  App inventory saved ({len(out)} bytes).")
            return True
        except Exception as e:
            self.output.emit(f"  ! Could not write app inventory: {e}")
            return False

    # -------------------------------------------------------------------------
    # Subprocess helpers
    # -------------------------------------------------------------------------

    def _base_cmd(self, args: list[str]) -> list[str]:
        return [sys.executable, "-m", "pymobiledevice3"] + args

    def _popen_kwargs(self) -> dict:
        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "env": {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        return kwargs

    def _stream(self, args: list[str], step_label: str = "",
                base: int | None = None, span: int | None = None) -> bool:
        """
        Run a step, forwarding its output live. Deliberately has no timeout —
        a full acquisition can legitimately run for a long time.

        base/span map the tool's own 0-100% onto this step's slice of the
        overall bar. Without them the bar would sit at the step's starting
        value while the status text advanced, which reads as a stuck bar.
        """
        try:
            self._proc = subprocess.Popen(self._base_cmd(args), **self._popen_kwargs())
        except Exception as e:
            self.output.emit(f"  ! Failed to start {step_label or args[0]}: {e}")
            return False

        last_overall = -1
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            if self._cancelled:
                break
            # tqdm redraws with \r, so one read can carry several updates.
            for part in re.split(r"[\r\n]", line):
                part = part.rstrip()
                if not part:
                    continue
                self.output.emit(f"  {part}")
                self.status.emit(f"{step_label}: {part[:90]}" if step_label else part[:110])

                if base is None or span is None:
                    continue
                pct = self._parse_percent(part)
                if pct is None:
                    continue
                overall = int(base + (span * pct / 100))
                if overall != last_overall:
                    last_overall = overall
                    self.progress.emit(overall)

        self._proc.wait()
        code = self._proc.returncode
        self._proc = None
        return code == 0

    @staticmethod
    def _parse_percent(line: str) -> float | None:
        """Pull a 0-100 percentage out of a tqdm/progress line, if present."""
        match = _PERCENT_RE.search(line)
        if match:
            try:
                return max(0.0, min(100.0, float(match.group(1))))
            except ValueError:
                return None
        counted = _COUNT_RE.search(line)
        if counted:
            done, total = float(counted.group(1)), float(counted.group(2))
            if total > 0:
                return max(0.0, min(100.0, done * 100 / total))
        return None

    def _capture(self, args: list[str], timeout: int = 60) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                self._base_cmd(args), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt" else 0,
            )
            return result.returncode == 0, (result.stdout or result.stderr or "").strip()
        except Exception as e:
            return False, str(e)

    def _elapsed(self) -> str:
        return format_duration(time.time() - self._started_at)
