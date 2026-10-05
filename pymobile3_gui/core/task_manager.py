"""
Pymobile3-GUI - Task Manager
Centralized async/threaded task manager for long-running operations
(forensic acquisition, file transfers, DDI mounting, firmware restore).
Emits granular progress, speed metrics, step transitions, and streaming logs
directly to the Persistent Operation Dock and Drawer.
"""

from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field
import time
from PySide6.QtCore import QObject, QThread, Signal, QMutex, QMutexLocker


@dataclass
class TaskStep:
    name: str
    status: str = "pending"  # "pending", "running", "done", "failed"


@dataclass
class TaskInfo:
    task_id: str
    title: str
    subtitle: str
    progress: int = 0  # 0 - 100
    steps: List[TaskStep] = field(default_factory=list)
    current_step: str = ""
    status_text: str = ""
    detail_text: str = ""
    logs: List[str] = field(default_factory=list)
    is_running: bool = False
    is_cancelled: bool = False
    start_time: float = 0.0
    error: Optional[str] = None


class WorkerThread(QThread):
    progress_signal = Signal(str, int, str, str)  # task_id, pct, step, detail
    log_signal = Signal(str, str)                 # task_id, log_line
    completed_signal = Signal(str, bool, str)     # task_id, success, message

    def __init__(self, task_id: str, target_fn: Callable, args=(), kwargs=None, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.target_fn = target_fn
        self.args = args
        self.kwargs = kwargs or {}
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            # target_fn receives a reporter callback helper
            def report_progress(pct: int, step: str = "", detail: str = ""):
                self.progress_signal.emit(self.task_id, pct, step, detail)

            def log_line(line: str):
                self.log_signal.emit(self.task_id, line)

            def is_cancelled() -> bool:
                return self._is_cancelled

            self.target_fn(
                *self.args,
                progress_cb=report_progress,
                log_cb=log_line,
                is_cancelled_cb=is_cancelled,
                **self.kwargs
            )
            self.completed_signal.emit(self.task_id, True, "Operation completed successfully.")
        except Exception as e:
            self.completed_signal.emit(self.task_id, False, str(e))


class TaskManager(QObject):
    task_started = Signal(TaskInfo)
    task_progress = Signal(TaskInfo)
    task_log = Signal(str, str)  # task_id, line
    task_finished = Signal(TaskInfo)

    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = TaskManager()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.tasks: Dict[str, TaskInfo] = {}
        self.workers: Dict[str, WorkerThread] = {}
        self.active_task_id: Optional[str] = None
        self._mutex = QMutex()

    def start_task(
        self,
        task_id: str,
        title: str,
        subtitle: str,
        steps: List[str],
        worker_fn: Callable,
        args=(),
        kwargs=None
    ) -> TaskInfo:
        """Register and start a background operation."""
        with QMutexLocker(self._mutex):
            # Reject a restart of an in-flight task: two workers writing the
            # same task_id (and often the same output directory) corrupt the
            # result and make cancellation impossible (active_task_id gets
            # cleared by whichever worker finishes first).
            existing = self.tasks.get(task_id)
            if existing and existing.is_running:
                return existing

            task_steps = [TaskStep(name=s) for s in steps]
            info = TaskInfo(
                task_id=task_id,
                title=title,
                subtitle=subtitle,
                progress=0,
                steps=task_steps,
                current_step=steps[0] if steps else "",
                status_text="Starting...",
                is_running=True,
                start_time=time.time(),
            )
            self.tasks[task_id] = info
            self.active_task_id = task_id

            worker = WorkerThread(task_id, worker_fn, args=args, kwargs=kwargs, parent=self)
            worker.progress_signal.connect(self._on_worker_progress)
            worker.log_signal.connect(self._on_worker_log)
            worker.completed_signal.connect(self._on_worker_completed)
            self.workers[task_id] = worker
            worker.start()

            self.task_started.emit(info)
            return info

    def cancel_active_task(self):
        """Request cancellation of all currently running tasks."""
        with QMutexLocker(self._mutex):
            for task_id, worker in list(self.workers.items()):
                task = self.tasks.get(task_id)
                if task and task.is_running:
                    task.is_cancelled = True
                    task.status_text = "Cancelling..."
                    worker.cancel()
                    self.task_progress.emit(task)

    def is_task_running(self, task_id: str) -> bool:
        """True when a task with this id is registered and still running."""
        with QMutexLocker(self._mutex):
            task = self.tasks.get(task_id)
            return bool(task and task.is_running)

    def shutdown(self, wait_ms: int = 3000) -> None:
        """
        Cooperative shutdown: cancel every running task, then wait (bounded)
        for each worker thread to exit. Called from the window's close path so
        we do not destroy live QThreads.
        """
        running = []
        with QMutexLocker(self._mutex):
            for task_id, worker in list(self.workers.items()):
                if worker.isRunning():
                    task = self.tasks.get(task_id)
                    if task:
                        task.is_cancelled = True
                        task.status_text = "Cancelling..."
                    worker.cancel()
                    running.append(worker)
        for worker in running:
            worker.wait(wait_ms)

    def _on_worker_progress(self, task_id: str, pct: int, step_name: str, detail: str):
        with QMutexLocker(self._mutex):
            task = self.tasks.get(task_id)
            if not task:
                return

            # A negative pct means "indeterminate, leave the bar alone". Callers
            # emit it alongside status text far more often than they emit a real
            # percentage, so clamping it to 0 would pin the bar at zero for the
            # whole operation.
            if pct >= 0:
                task.progress = min(pct, 100)

            if step_name:
                task.current_step = step_name
                # Only re-stage the checklist when the name is actually one of
                # this task's declared steps. Free-form status text (e.g. a tqdm
                # line) matches nothing, and must not mark every step done.
                if any(s.name == step_name for s in task.steps):
                    seen_current = False
                    for s in task.steps:
                        if s.name == step_name:
                            s.status = "running"
                            seen_current = True
                        elif not seen_current:
                            s.status = "done"
                        else:
                            s.status = "pending"
                else:
                    task.status_text = step_name
            if detail:
                task.detail_text = detail

            self.task_progress.emit(task)

    def _on_worker_log(self, task_id: str, line: str):
        with QMutexLocker(self._mutex):
            task = self.tasks.get(task_id)
            if task:
                task.logs.append(line)
        self.task_log.emit(task_id, line)

    def _on_worker_completed(self, task_id: str, success: bool, msg: str):
        with QMutexLocker(self._mutex):
            task = self.tasks.get(task_id)
            if not task:
                return

            task.is_running = False
            if success:
                task.progress = 100
                task.status_text = "Completed"
                for s in task.steps:
                    s.status = "done"
            else:
                task.status_text = "Failed"
                task.error = msg
                for s in task.steps:
                    if s.status == "running":
                        s.status = "failed"

            # Only clear the active pointer when no other worker is still
            # running, otherwise a second in-flight task becomes "invisible"
            # to cancel_all/dock state.
            if self.active_task_id == task_id:
                self.active_task_id = None
                for other_id, w in self.workers.items():
                    if other_id != task_id and w.isRunning():
                        self.active_task_id = other_id
                        break

            self.task_finished.emit(task)
