"""
Pymobile3-GUI - Persistent Operation Dock
Bottom-anchored dock visible across all pages displaying live progress,
status, ETA, and quick actions without blocking navigation.
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QCursor
from pymobile3_gui.ui.theme import Colors
from pymobile3_gui.core.task_manager import TaskManager, TaskInfo


class OperationDock(QFrame):
    toggle_drawer = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("OperationDock")
        self.setFixedHeight(54)
        self.setStyleSheet(f"""
            QFrame#OperationDock {{
                background-color: {Colors.BG_DOCK};
                border-top: 1px solid {Colors.BORDER_DEFAULT};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(16)

        # ── 1. Pulse Indicator ─────────────────────────────────────────
        self.pulse_dot = QLabel("●", self)
        self.pulse_dot.setStyleSheet(f"""
            color: {Colors.SUCCESS};
            font-size: 14px;
            font-weight: 800;
        """)
        layout.addWidget(self.pulse_dot)

        # ── 2. Task Details ───────────────────────────────────────────
        details_layout = QVBoxLayout()
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(2)

        self.lbl_title = QLabel("Ready", self)
        self.lbl_title.setStyleSheet("font-size: 12px; font-weight: 700; color: #f6f7fb;")
        details_layout.addWidget(self.lbl_title)

        self.lbl_status = QLabel("No active operations", self)
        self.lbl_status.setStyleSheet(f"font-size: 10px; color: {Colors.TEXT_MUTED};")
        details_layout.addWidget(self.lbl_status)

        layout.addLayout(details_layout)

        # ── 3. Progress Bar ───────────────────────────────────────────
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(240)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        self.lbl_pct = QLabel("0%", self)
        self.lbl_pct.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {Colors.TEXT_SECONDARY}; min-width: 32px;")
        layout.addWidget(self.lbl_pct)

        layout.addStretch()

        # ── 4. Actions ────────────────────────────────────────────────
        self.btn_details = QPushButton("View Details", self)
        self.btn_details.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_details.setStyleSheet(f"""
            QPushButton {{
                background-color: #2563eb;
                color: #ffffff;
                border: 1px solid #3b82f6;
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: #1d4ed8;
            }}
        """)
        self.btn_details.clicked.connect(self.toggle_drawer.emit)
        layout.addWidget(self.btn_details)

        self.btn_cancel = QPushButton("Cancel", self)
        self.btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: #2a1616;
                color: #f87171;
                border: 1px solid #5a2323;
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: #3b1b1b;
                color: #fca5a5;
            }}
        """)
        self.btn_cancel.clicked.connect(self._on_cancel)
        layout.addWidget(self.btn_cancel)

        # Wire to TaskManager instance
        tm = TaskManager.instance()
        tm.task_started.connect(self.update_task)
        tm.task_progress.connect(self.update_task)
        tm.task_finished.connect(self._on_task_finished)

        # Initial state: hidden when idle
        self.hide()

    def update_task(self, task: TaskInfo):
        self.show()
        self.lbl_title.setText(task.title)
        sub = task.current_step if task.current_step else task.subtitle
        if task.detail_text:
            sub += f" · {task.detail_text}"
        self.lbl_status.setText(sub)

        self.progress_bar.setValue(task.progress)
        self.lbl_pct.setText(f"{task.progress}%")

        if task.is_cancelled:
            self.pulse_dot.setStyleSheet(f"color: {Colors.WARNING}; font-size: 14px;")
            self.btn_cancel.setEnabled(False)
        else:
            self.pulse_dot.setStyleSheet(f"color: {Colors.SUCCESS}; font-size: 14px;")
            self.btn_cancel.setEnabled(True)

    def _on_task_finished(self, task: TaskInfo):
        self.progress_bar.setValue(task.progress)
        self.lbl_pct.setText(f"{task.progress}%")

        if task.error:
            self.pulse_dot.setStyleSheet(f"color: {Colors.DANGER}; font-size: 14px;")
            self.lbl_status.setText(f"Failed: {task.error}")
        else:
            self.pulse_dot.setStyleSheet(f"color: {Colors.SUCCESS}; font-size: 14px;")
            self.lbl_status.setText("Complete")

        self.btn_cancel.setEnabled(False)

        # Auto-hide dock after 8 seconds of inactivity if closed
        QTimer.singleShot(8000, self._maybe_hide)

    def _maybe_hide(self):
        tm = TaskManager.instance()
        if not tm.active_task_id:
            self.hide()

    def _on_cancel(self):
        TaskManager.instance().cancel_active_task()
