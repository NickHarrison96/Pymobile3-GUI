"""
Pymobile3-GUI - Operation Drawer
Expandable detailed sheet showing step progression, metrics, and live logs for active tasks.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QFrame, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QCursor
from pymobile3_gui.ui.theme import Colors
from pymobile3_gui.ui.assets import icon
from pymobile3_gui.core.task_manager import TaskInfo


class StepBadge(QFrame):
    """Visual pill representing a single task step."""
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("StepBadge")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        self.lbl_icon = QLabel("○", self)
        self.lbl_icon.setStyleSheet("font-weight: 700; font-size: 11px;")
        self.lbl_name = QLabel(name, self)
        self.lbl_name.setStyleSheet("font-size: 11px; font-weight: 500;")

        layout.addWidget(self.lbl_icon)
        layout.addWidget(self.lbl_name)
        self.set_state("pending")

    def _set_icon(self, name: str, color: str):
        self.lbl_icon.setPixmap(icon(name, color, 16).pixmap(16, 16))

    def set_state(self, status: str):
        if status == "done":
            self._set_icon("circle-check", Colors.SUCCESS)
            self.lbl_name.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: 500;")
            self.setStyleSheet(f"""
                QFrame#StepBadge {{
                    background-color: {Colors.SUCCESS_BG};
                    border: 1px solid {Colors.SUCCESS_BORDER};
                    border-radius: 8px;
                }}
            """)
        elif status == "running":
            self._set_icon("loader", "#60a5fa")
            self.lbl_name.setStyleSheet("color: #ffffff; font-weight: 600;")
            self.setStyleSheet(f"""
                QFrame#StepBadge {{
                    background-color: #1e293b;
                    border: 1px solid #3b82f6;
                    border-radius: 8px;
                }}
            """)
        elif status == "failed":
            self._set_icon("circle-x", Colors.DANGER)
            self.lbl_name.setStyleSheet(f"color: {Colors.DANGER}; font-weight: 500;")
            self.setStyleSheet(f"""
                QFrame#StepBadge {{
                    background-color: {Colors.DANGER_BG};
                    border: 1px solid {Colors.DANGER_BORDER};
                    border-radius: 8px;
                }}
            """)
        else:  # pending
            self._set_icon("chevron-right", Colors.TEXT_MUTED)
            self.lbl_name.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-weight: 500;")
            self.setStyleSheet(f"""
                QFrame#StepBadge {{
                    background-color: #151922;
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    border-radius: 8px;
                }}
            """)


class OperationDrawer(QFrame):
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("OperationDrawer")
        self.setFixedHeight(260)
        self.setStyleSheet(f"""
            QFrame#OperationDrawer {{
                background-color: {Colors.BG_DRAWER};
                border-top: 1px solid {Colors.BORDER_DEFAULT};
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 14, 20, 14)
        main_layout.setSpacing(12)

        # ── Header ───────────────────────────────────────────────────
        header_layout = QHBoxLayout()
        self.lbl_title = QLabel("Operation Details", self)
        self.lbl_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #f6f7fb;")
        header_layout.addWidget(self.lbl_title)

        header_layout.addStretch()

        self.btn_copy = QPushButton("Copy Logs", self)
        self.btn_copy.setStyleSheet("""
            QPushButton {
                background: #1a202c; color: #9ca6ba; border: 1px solid #2d3748;
                border-radius: 6px; padding: 4px 10px; font-size: 11px;
            }
            QPushButton:hover { background: #2d3748; color: #fff; }
        """)
        self.btn_copy.clicked.connect(self._copy_logs)
        header_layout.addWidget(self.btn_copy)

        self.btn_close = QPushButton("✕", self)
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setStyleSheet("""
            QPushButton {
                background: transparent; color: #9ca6ba; border: none;
                border-radius: 12px; font-size: 12px; font-weight: 700;
            }
            QPushButton:hover { background: #242c3d; color: #fff; }
        """)
        self.btn_close.clicked.connect(self.closed.emit)
        header_layout.addWidget(self.btn_close)

        main_layout.addLayout(header_layout)

        # ── Steps Flow Bar ───────────────────────────────────────────
        self.steps_scroll = QScrollArea(self)
        self.steps_scroll.setWidgetResizable(True)
        self.steps_scroll.setFixedHeight(44)
        self.steps_scroll.setStyleSheet("background: transparent; border: none;")
        self.steps_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.steps_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.steps_widget = QWidget(self.steps_scroll)
        self.steps_layout = QHBoxLayout(self.steps_widget)
        self.steps_layout.setContentsMargins(0, 0, 0, 0)
        self.steps_layout.setSpacing(10)
        self.steps_layout.addStretch()
        self.steps_scroll.setWidget(self.steps_widget)

        main_layout.addWidget(self.steps_scroll)

        # ── Terminal Log Console ─────────────────────────────────────
        self.log_console = QPlainTextEdit(self)
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {Colors.BG_TERMINAL};
                color: #a5b4fc;
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 8px;
                font-family: 'JetBrains Mono', 'Consolas', monospace;
                font-size: 11px;
                padding: 8px;
            }}
        """)
        main_layout.addWidget(self.log_console)

        self.step_badges: dict = {}

    def update_task(self, task: TaskInfo):
        self.lbl_title.setText(f"{task.title} — {task.progress}% ({task.current_step})")

        # Rebuild steps if not already present
        if len(self.step_badges) != len(task.steps):
            # Clear old
            while self.steps_layout.count() > 1:
                item = self.steps_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.step_badges.clear()

            for step in task.steps:
                badge = StepBadge(step.name, self.steps_widget)
                badge.set_state(step.status)
                self.step_badges[step.name] = badge
                self.steps_layout.insertWidget(self.steps_layout.count() - 1, badge)
        else:
            # Update states
            for step in task.steps:
                if step.name in self.step_badges:
                    self.step_badges[step.name].set_state(step.status)

    def append_log(self, text: str):
        self.log_console.appendPlainText(text)
        self.log_console.verticalScrollBar().setValue(
            self.log_console.verticalScrollBar().maximum()
        )

    def _copy_logs(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.log_console.toPlainText())
        self.btn_copy.setText("Copied!")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: self.btn_copy.setText("Copy Logs"))
