"""
Pymobile3-GUI - Transient toast notification.

An in-window banner for events the user did not initiate and must not miss —
principally the RSD tunnel dropping mid-session. Anchored to the top-right of
its parent window so it never steals focus or blocks the workspace, and it
offers actions inline rather than interrupting with a modal.
"""

from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer, Signal

from pymobile3_gui.ui.theme import Colors


TOAST_WIDTH = 340
TOAST_MARGIN = 18


class Toast(QFrame):
    """
    A single reusable notification surface.

    Only one message is shown at a time; a newer message replaces whatever is
    on screen. That is deliberate — a stack of stale tunnel warnings is worse
    than the latest one.
    """

    dismissed = Signal()

    LEVEL_COLORS = {
        "info": (Colors.ACCENT_PRIMARY, Colors.BG_CARD),
        "warning": (Colors.WARNING, Colors.WARNING_BG),
        "error": (Colors.DANGER, Colors.DANGER_BG),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setFixedWidth(TOAST_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)
        # Frameless child overlay: painted above the workspace, never focused.
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        self.lbl_title = QLabel("", self)
        self.lbl_title.setStyleSheet(
            "font-size: 12px; font-weight: 700; color: #ffffff; background: transparent;")
        layout.addWidget(self.lbl_title)

        self.lbl_body = QLabel("", self)
        self.lbl_body.setWordWrap(True)
        self.lbl_body.setStyleSheet(
            f"font-size: 11px; color: {Colors.TEXT_SECONDARY}; background: transparent;")
        layout.addWidget(self.lbl_body)

        self.actions_row = QHBoxLayout()
        self.actions_row.setSpacing(8)
        self.actions_row.addStretch()
        layout.addLayout(self.actions_row)

        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self.dismiss)

        self._action_buttons: list[QPushButton] = []
        self.hide()

    # ------------------------------------------------------------------ API

    def show_message(self, title: str, body: str, actions=None,
                     level: str = "info", timeout_ms: int = 0):
        """
        Display a message.

        actions:    list of (label, callback); the first is styled as primary.
        timeout_ms: 0 keeps it up until the user acts — use that for anything
                    that asks a question, so an unattended machine does not
                    silently discard it.
        """
        accent, background = self.LEVEL_COLORS.get(level, self.LEVEL_COLORS["info"])
        self.setStyleSheet(f"""
            QFrame#Toast {{
                background-color: {background};
                border: 1px solid {accent};
                border-radius: 12px;
            }}
        """)
        self.lbl_title.setText(title)
        self.lbl_body.setText(body)
        self.lbl_body.setVisible(bool(body))

        self._clear_actions()
        for index, (label, callback) in enumerate(actions or []):
            self._add_action(label, callback, primary=(index == 0), accent=accent)
        self._add_action("Dismiss", None, primary=False, accent=accent)

        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()

        self._auto_timer.stop()
        if timeout_ms > 0:
            self._auto_timer.start(timeout_ms)

    def dismiss(self):
        self._auto_timer.stop()
        self.hide()
        self.dismissed.emit()

    def reposition(self):
        """Anchor to the parent's top-right. Call from the parent's resizeEvent."""
        parent = self.parentWidget()
        if not parent:
            return
        self.move(max(TOAST_MARGIN, parent.width() - self.width() - TOAST_MARGIN),
                  TOAST_MARGIN)

    # -------------------------------------------------------------- internals

    def _clear_actions(self):
        for btn in self._action_buttons:
            self.actions_row.removeWidget(btn)
            btn.deleteLater()
        self._action_buttons.clear()

    def _add_action(self, label: str, callback, primary: bool, accent: str):
        btn = QPushButton(label, self)
        btn.setCursor(Qt.PointingHandCursor)
        if primary:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {accent};
                    color: #ffffff;
                    border: none;
                    border-radius: 6px;
                    padding: 5px 12px;
                    font-size: 11px;
                    font-weight: 700;
                }}
            """)
        else:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {Colors.TEXT_SECONDARY};
                    border: 1px solid {Colors.BORDER_DEFAULT};
                    border-radius: 6px;
                    padding: 5px 12px;
                    font-size: 11px;
                    font-weight: 600;
                }}
                QPushButton:hover {{ color: {Colors.TEXT_PRIMARY}; }}
            """)

        def on_click():
            # Dismiss first so a slow callback cannot leave the toast stuck.
            self.dismiss()
            if callback:
                callback()

        btn.clicked.connect(on_click)
        self.actions_row.addWidget(btn)
        self._action_buttons.append(btn)
