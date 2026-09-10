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

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import datetime

from PySide6.QtCore import QObject, Signal

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
#
# CAUTION: only valid when the tool reports ONE bar for the whole step. AFC pull
# draws a fresh per-file bar (see _step_media), so parsing percentages there
# makes the overall bar restart on every file.
_PERCENT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_COUNT_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")

# How often a progress_probe is consulted while streaming. The probe walks a
# local directory, so it must not run on every tqdm redraw.
PROBE_INTERVAL = 1.0

# Time budget for the upfront AFC walk that yields an exact byte total.
# Measured ~2.2 ms/entry, so a 6k-file camera roll lands around 13s; this
# leaves generous headroom before we fall back to a plain file count. Cheap
# next to the transfer it is measuring — 27 GB over USB takes many minutes.
AFC_SCAN_BUDGET = 90.0

DEFAULT_OPTIONS = {
    "incl_media": True,
    "incl_crash": True,
    "incl_apps": True,
    "keep_intermediate": False,
}

# Step names emitted via step_changed. The UI checklist is built from
# plan_steps(), so these names are the single source of truth for both sides.
STEP_BACKUP = "iTunes backup"
STEP_MEDIA = "Camera media"
STEP_CRASH = "Crash reports"
STEP_APPS = "App inventory"
STEP_ARCHIVE = "Archive"


def _free_bytes(path: str) -> int:
    """Free space on the volume holding path; 0 when it cannot be determined."""
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def _gb(n: int) -> str:
    return f"{n / (1024 ** 3):.1f} GB"


def _local_dir_stats(path: str) -> tuple[int, int]:
    """(file_count, total_bytes) already written locally. Cheap; purely local."""
    count = 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            count += 1
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return count, total


async def _afc_scan(remote_root: str, budget: float) -> tuple[int, int]:
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.afc import AfcService

    lockdown = await create_using_usbmux()
    async with AfcService(lockdown=lockdown) as afc:
        # One stat per entry yields BOTH its type and its size, so a single
        # walk suffices. Calling isdir() as well would double the round trips
        # for no extra information — measured 26s vs 13s on a 6k-file roll.
        started = time.time()
        file_count = 0
        total_bytes = 0
        over_budget = False
        pending = [remote_root]

        while pending:
            current = pending.pop()
            try:
                entries = await afc.listdir(current)
            except Exception:
                continue
            for entry in entries:
                if entry in (".", ".."):
                    continue
                full = f"{current}/{entry}"
                try:
                    info = await afc.stat(full)
                except Exception:
                    continue
                if info.get("st_ifmt") == "S_IFDIR":
                    pending.append(full)
                    continue
                file_count += 1
                total_bytes += int(info.get("st_size", 0))
                if time.time() - started > budget:
                    over_budget = True
            if over_budget:
                break

        # An abandoned walk leaves BOTH totals short — the count is as partial
        # as the byte sum — so neither is a safe denominator. Report nothing and
        # let the caller degrade to coarse progress rather than show a bar that
        # races to 100% and sticks there.
        if over_budget:
            return 0, 0
        return file_count, total_bytes


def scan_remote_totals(remote_root: str,
                       budget: float = AFC_SCAN_BUDGET) -> tuple[int, int]:
    """
    (file_count, total_bytes) under a remote AFC path; (0, 0) if unreachable.

    total_bytes is 0 when the stat walk ran out of budget — callers should fall
    back to the file count in that case.
    """
    try:
        return asyncio.run(_afc_scan(remote_root, budget))
    except Exception:
        return 0, 0


def plan_steps(mode: str, options: dict | None = None) -> list[str]:
    """
    The exact steps AcquisitionWorker will emit for this mode and options.

    The view builds its checklist from this rather than hardcoding prose names,
    so a checklist entry can never fail to match the step that drives it.
    """
    opts = {**DEFAULT_OPTIONS, **(options or {})}
    if mode == "logical":
        return [STEP_BACKUP]
    if mode not in ("logical_plus", "prfs"):
        return []

    steps: list[str] = []
    if mode == "logical_plus":
        steps.append(STEP_BACKUP)
    if opts["incl_media"]:
        steps.append(STEP_MEDIA)
    if opts["incl_crash"]:
        steps.append(STEP_CRASH)
    if opts["incl_apps"]:
        steps.append(STEP_APPS)
    if steps:
        steps.append(STEP_ARCHIVE)
    return steps


class AcquisitionWorker(QObject):
    """
    Runs a multi-step forensic acquisition.

    Deliberately a QObject, not a QThread: TaskManager already runs worker_fn on
    its own thread, and nesting a QThread inside that thread silently breaks
    signal delivery. The inner QThread's signals are queued to the thread that
    *owns* the object — the outer worker thread — which is blocked waiting and
    runs no event loop, so the queued events are never dispatched and no
    progress or log line ever reaches the UI.

    Call execute() from whatever thread should do the work; emissions are then
    direct calls and reach their callbacks immediately.

    Signals (matching StreamingProcessRunner so the progress panel can bind):
        progress(int)        0-100, -1 for indeterminate
        status(str)          free-form status text for the current line
        step_changed(str)    a real step boundary; the name is one of STEP_*
        output(str)          log line
        finished(bool, str)  (success, summary)

    status fires for every line of tool output, so it must not be mistaken for a
    step transition — a checklist driven by it would advance on tqdm noise.
    """

    progress = Signal(int)
    status = Signal(str)
    step_changed = Signal(str)
    output = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, mode: str, output_dir: str,
                 options: dict | None = None, parent=None,
                 is_cancelled_cb=None):
        super().__init__(parent)
        self.mode = mode
        self.output_dir = output_dir
        self.options = {**DEFAULT_OPTIONS, **(options or {})}
        self._cancelled = False
        # Lets an owner (TaskManager) signal cancellation without holding a
        # reference to this object.
        self._is_cancelled_cb = is_cancelled_cb
        self._proc: subprocess.Popen | None = None
        self._started_at = 0.0

    # -------------------------------------------------------------------------
    # Control
    # -------------------------------------------------------------------------

    def cancel(self):
        """Request cancellation; the current step is terminated."""
        self._cancelled = True
        self.status.emit("Cancelling…")
        self._kill_current_process()

    def _kill_current_process(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def _should_cancel(self) -> bool:
        """
        True once cancellation is requested from either side. Latches, so a
        cancel observed mid-step still tears down the running subprocess.
        """
        if self._cancelled:
            return True
        if self._is_cancelled_cb and self._is_cancelled_cb():
            self._cancelled = True
            self._kill_current_process()
            return True
        return False

    # -------------------------------------------------------------------------
    # Entry point
    # -------------------------------------------------------------------------

    def execute(self):
        """Run the acquisition on the calling thread."""
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

            if self._should_cancel():
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
        self.step_changed.emit(STEP_BACKUP)
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
            steps.append((STEP_BACKUP, lambda b, s: self._step_backup(stage_dir, b, s)))
        if self.options["incl_media"]:
            steps.append((STEP_MEDIA, lambda b, s: self._step_media(stage_dir, b, s)))
        if self.options["incl_crash"]:
            steps.append((STEP_CRASH, lambda b, s: self._step_crash(stage_dir, b, s)))
        if self.options["incl_apps"]:
            steps.append((STEP_APPS, lambda b, s: self._step_apps(stage_dir)))

        if not steps:
            return False, "No acquisition components selected."

        completed: list[str] = []
        failed: list[str] = []

        # Weight each step evenly across 0-90%; archiving takes the last slice.
        span = 90 // len(steps)

        for index, (label, action) in enumerate(steps, start=1):
            if self._should_cancel():
                return False, "Cancelled."
            base = (index - 1) * span
            self.step_changed.emit(label)
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

        if self._should_cancel():
            return False, "Cancelled."

        # Archive everything collected
        self.step_changed.emit(STEP_ARCHIVE)
        self.status.emit("Creating archive…")
        self.progress.emit(92)
        archive_path = os.path.join(
            self.output_dir, f"{mode_label.lower().rstrip('+')}_{timestamp}.tar"
        )

        _staged_files, staged_bytes = _local_dir_stats(stage_dir)
        free = _free_bytes(self.output_dir)
        if free and staged_bytes and free < staged_bytes * 1.05:
            return False, (
                f"Collected {_gb(staged_bytes)} but only {_gb(free)} is free — "
                f"archiving needs about that much again. The staged files are "
                f"still at {stage_dir}; free some space and re-archive, or "
                f"re-run with archiving disabled."
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

        # `afc pull` draws a NEW tqdm bar for every file over 4 MB, so its
        # percentages describe one photo, not the camera roll. Feeding those to
        # the overall bar made it sweep this step's slice once per file forever.
        # Measure the destination directory against a known total instead.
        self.status.emit("Scanning camera roll…")
        file_count, total_bytes = scan_remote_totals("/DCIM")
        if total_bytes:
            self.output.emit(
                f"  Camera roll: {file_count} files, {_gb(total_bytes)}")
            # The collection is later tar'd from this staging directory, so the
            # peak requirement is roughly twice what we are about to pull.
            # Filling the disk mid-transfer leaves a corrupt half-acquisition
            # and takes the whole machine down with it.
            free = _free_bytes(stage_dir)
            needed = int(total_bytes * 2.1)
            if free and free < needed:
                self.output.emit(
                    f"  ! Not enough free space: {_gb(free)} available, "
                    f"~{_gb(needed)} needed (the collection is archived to a "
                    f".tar, which briefly doubles usage).")
                self.status.emit("Insufficient disk space")
                return False
        elif file_count:
            self.output.emit(
                f"  Camera roll: {file_count} files "
                "(size scan skipped; progress counts files)")
        else:
            self.output.emit("  Camera roll size unknown; progress will be coarse.")

        def probe():
            copied_files, copied_bytes = _local_dir_stats(target)
            if total_bytes:
                return copied_bytes * 100.0 / total_bytes
            if file_count:
                return copied_files * 100.0 / file_count
            return None

        # AFC is rooted at /var/mobile/Media, so /DCIM is the camera roll.
        return self._stream(["afc", "pull", "/DCIM", target],
                            step_label="Media", base=base, span=span,
                            progress_probe=probe if (total_bytes or file_count) else None)

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
                base: int | None = None, span: int | None = None,
                progress_probe=None) -> bool:
        """
        Run a step, forwarding its output live. Deliberately has no timeout —
        a full acquisition can legitimately run for a long time.

        base/span map the tool's own 0-100% onto this step's slice of the
        overall bar. Without them the bar would sit at the step's starting
        value while the status text advanced, which reads as a stuck bar.

        progress_probe overrides percentage parsing for tools that draw a bar
        per file rather than one for the whole step: it is polled at most every
        PROBE_INTERVAL seconds and returns the step's own 0-100 completion, or
        None when it cannot tell. Progress is clamped monotonic either way, so
        a step can never visibly run backwards.
        """
        try:
            self._proc = subprocess.Popen(self._base_cmd(args), **self._popen_kwargs())
        except Exception as e:
            self.output.emit(f"  ! Failed to start {step_label or args[0]}: {e}")
            return False

        last_overall = -1
        last_probe_at = 0.0
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            if self._should_cancel():
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

                if progress_probe is not None:
                    now = time.time()
                    if now - last_probe_at < PROBE_INTERVAL:
                        continue
                    last_probe_at = now
                    pct = progress_probe()
                else:
                    pct = self._parse_percent(part)

                if pct is None:
                    continue
                overall = int(base + (span * max(0.0, min(100.0, pct)) / 100))
                # Monotonic within the step: a per-file bar restarting at 0 must
                # never drag the overall bar backwards.
                if overall > last_overall:
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
