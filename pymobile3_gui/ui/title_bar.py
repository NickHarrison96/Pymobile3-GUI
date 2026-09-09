"""
Pymobile3-GUI - Custom Title Bar
Apple-inspired custom chrome with traffic lights, centered title, and device status chip.
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QCursor
from pymobile3_gui.ui.theme import Colors


class TrafficLightButton(QPushButton):
    """Circular Apple-style caption button with subtle hover glyphs."""
    def __init__(self, color: str, hover_color: str, glyph: str, parent=None):
        super().__init__(parent)
        self.normal_color = color
        self.hover_color = hover_color
        self.glyph = glyph
        self.setFixedSize(13, 13)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self._update_style(hovered=False)

    def enterEvent(self, event):
        self._update_style(hovered=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._update_style(hovered=False)
        super().leaveEvent(event)

    def _update_style(self, hovered: bool):
        bg = self.hover_color if hovered else self.normal_color
        text = self.glyph if hovered else ""
        self.setText(text)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                border: 1px solid rgba(0, 0, 0, 0.25);
                border-radius: 6px;
                color: rgba(0, 0, 0, 0.65);
                font-size: 9px;
                font-weight: 800;
                padding: 0px;
                margin: 0px;
                text-align: center;
            }}
        """)


class TitleBar(QWidget):
    refresh_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.window_parent = parent
        self.setFixedHeight(40)
        self.setObjectName("TitleBar")
        self.setStyleSheet(f"""
            QWidget#TitleBar {{
                background-color: rgba(18, 22, 32, 0.75);
                border-bottom: 1px solid {Colors.BORDER_DEFAULT};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(10)

        # ── 1. Traffic Lights ──────────────────────────────────────────
        self.dots_container = QWidget(self)
        dots_layout = QHBoxLayout(self.dots_container)
        dots_layout.setContentsMargins(0, 0, 0, 0)
        dots_layout.setSpacing(8)

        self.btn_close = TrafficLightButton("#ff5f57", "#ff433b", "✕", self)
        self.btn_min = TrafficLightButton("#febc2e", "#e8a923", "—", self)
        self.btn_max = TrafficLightButton("#28c840", "#21ab36", "＋", self)

        self.btn_close.clicked.connect(self._on_close)
        self.btn_min.clicked.connect(self._on_min)
        self.btn_max.clicked.connect(self._on_max)

        dots_layout.addWidget(self.btn_close)
        dots_layout.addWidget(self.btn_min)
        dots_layout.addWidget(self.btn_max)
        layout.addWidget(self.dots_container)

        # Left spacer
        layout.addSpacing(16)

        # ── 2. Brand Sub-label ─────────────────────────────────────────
        self.lbl_brand = QLabel("Pymobile3-GUI", self)
        self.lbl_brand.setStyleSheet("font-weight: 700; font-size: 12px; color: #8e9bb3;")
        layout.addWidget(self.lbl_brand)

        self.lbl_edition = QLabel("Windows Edition", self)
        self.lbl_edition.setStyleSheet(f"font-size: 10px; color: {Colors.TEXT_MUTED}; margin-top: 1px;")
        layout.addWidget(self.lbl_edition)

        layout.addStretch()

        # ── 3. Centered Title / Status Chip ───────────────────────────
        self.device_chip = QLabel("○  No device connected", self)
        self.device_chip.setStyleSheet(f"""
            background-color: #161b26;
            color: {Colors.TEXT_SECONDARY};
            border: 1px solid {Colors.BORDER_DEFAULT};
            border-radius: 12px;
            padding: 3px 12px;
            font-size: 11px;
            font-weight: 600;
        """)
        layout.addWidget(self.device_chip)

        layout.addStretch()

        # ── 4. Quick Refresh Action ───────────────────────────────────
        self.btn_refresh = QPushButton("⟳ Refresh", self)
        self.btn_refresh.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background-color: #171d29;
                color: {Colors.TEXT_SECONDARY};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 7px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: #222b3d;
                color: {Colors.TEXT_PRIMARY};
                border-color: {Colors.BORDER_DEFAULT};
            }}
        """)
        self.btn_refresh.clicked.connect(self.refresh_clicked)
        layout.addWidget(self.btn_refresh)

    def set_device_status(self, connected: bool, name: str = "", details: str = ""):
        """Update device connection pill."""
        if connected:
            text = f"●  {name}" if not details else f"●  {name} · {details}"
            self.device_chip.setText(text)
            self.device_chip.setStyleSheet(f"""
                background-color: {Colors.SUCCESS_BG};
                color: {Colors.SUCCESS};
                border: 1px solid {Colors.SUCCESS_BORDER};
                border-radius: 12px;
                padding: 3px 12px;
                font-size: 11px;
                font-weight: 600;
            """)
        else:
            self.device_chip.setText("○  No device connected")
            self.device_chip.setStyleSheet(f"""
                background-color: #161b26;
                color: {Colors.TEXT_SECONDARY};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 12px;
                padding: 3px 12px;
                font-size: 11px;
                font-weight: 600;
            """)

    def _on_close(self):
        if self.window_parent:
            self.window_parent.close()

    def _on_min(self):
        if self.window_parent:
            self.window_parent.showMinimized()

    def _on_max(self):
        if self.window_parent:
            if self.window_parent.isMaximized():
                self.window_parent.showNormal()
            else:
                self.window_parent.showMaximized()

    def mouseDoubleClickEvent(self, event):
        """Double clicking title bar toggles maximize."""
        if event.button() == Qt.LeftButton:
            self._on_max()
        super().mouseDoubleClickEvent(event)
