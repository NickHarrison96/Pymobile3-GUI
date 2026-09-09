"""
Pymobile3-GUI - Navigation Sidebar
Apple-styled vertical navigation bar with category grouping, active glow,
and persistent live device connection card.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QFont
from pymobile3_gui.ui.theme import Colors


class NavButton(QPushButton):
    """Sidebar navigation item with active highlight and optional count pill."""
    def __init__(self, icon: str, title: str, count: str = "", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setFixedHeight(38)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(10)

        self.lbl_icon = QLabel(icon, self)
        self.lbl_icon.setStyleSheet("font-size: 14px; font-weight: 700; color: inherit;")

        self.lbl_title = QLabel(title, self)
        self.lbl_title.setStyleSheet("font-size: 12px; font-weight: 600; color: inherit;")

        layout.addWidget(self.lbl_icon)
        layout.addWidget(self.lbl_title)
        layout.addStretch()

        if count:
            self.lbl_count = QLabel(count, self)
            self.lbl_count.setStyleSheet(f"""
                background-color: #242c3d;
                color: #9ca6ba;
                border-radius: 8px;
                padding: 1px 6px;
                font-size: 10px;
                font-weight: 700;
            """)
            layout.addWidget(self.lbl_count)

        self._apply_style(False)

    def setChecked(self, checked: bool):
        super().setChecked(checked)
        self._apply_style(checked)

    def _apply_style(self, active: bool):
        if active:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: #1e3a8a;
                    border: 1px solid #3b82f6;
                    border-radius: 8px;
                    color: #ffffff;
                    text-align: left;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    border: 1px solid transparent;
                    border-radius: 8px;
                    color: {Colors.TEXT_SECONDARY};
                    text-align: left;
                }}
                QPushButton:hover {{
                    background-color: #171b26;
                    border-color: {Colors.BORDER_DEFAULT};
                    color: {Colors.TEXT_PRIMARY};
                }}
            """)


class DeviceStatusCard(QFrame):
    """Bottom card displaying connected device summary and battery."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DeviceCard")
        self.setStyleSheet(f"""
            QFrame#DeviceCard {{
                background-color: #131722;
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 12px;
                padding: 10px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)

        self.lbl_name = QLabel("No Device", self)
        self.lbl_name.setStyleSheet("font-size: 12px; font-weight: 700; color: #f6f7fb;")
        layout.addWidget(self.lbl_name)

        self.lbl_sub = QLabel("Connect an iPhone or iPad", self)
        self.lbl_sub.setStyleSheet(f"font-size: 10px; color: {Colors.TEXT_MUTED};")
        layout.addWidget(self.lbl_sub)

        self.lbl_status = QLabel("USB / Wi-Fi disconnected", self)
        self.lbl_status.setStyleSheet(f"font-size: 10px; color: {Colors.TEXT_MUTED};")
        layout.addWidget(self.lbl_status)

    def set_device(self, info: dict):
        if info and info.get("Trusted") is not None:
            name = info.get("DeviceName") or info.get("Model") or "iOS Device"
            os_ver = info.get("OS", "iOS")
            conn = info.get("Connection", "USB")
            batt = info.get("Battery", "")
            trusted = "Trusted" if info.get("Trusted") else "Untrusted"

            self.lbl_name.setText(f"● {name}")
            self.lbl_name.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {Colors.SUCCESS};")
            self.lbl_sub.setText(f"{os_ver} · {trusted}")
            self.lbl_status.setText(f"{batt} battery · {conn}")
            self.setStyleSheet(f"""
                QFrame#DeviceCard {{
                    background-color: {Colors.SUCCESS_BG};
                    border: 1px solid {Colors.SUCCESS_BORDER};
                    border-radius: 12px;
                    padding: 10px;
                }}
            """)
        else:
            self.lbl_name.setText("○ Disconnected")
            self.lbl_name.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {Colors.TEXT_MUTED};")
            self.lbl_sub.setText("Connect an iPhone or iPad")
            self.lbl_status.setText("USB / Wi-Fi disconnected")
            self.setStyleSheet(f"""
                QFrame#DeviceCard {{
                    background-color: #131722;
                    border: 1px solid {Colors.BORDER_DEFAULT};
                    border-radius: 12px;
                    padding: 10px;
                }}
            """)


class NavigationSidebar(QWidget):
    workspace_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        self.setObjectName("Sidebar")
        self.setStyleSheet(f"""
            QWidget#Sidebar {{
                background-color: {Colors.BG_SIDEBAR};
                border-right: 1px solid {Colors.BORDER_DEFAULT};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 16, 14, 16)
        layout.setSpacing(6)

        # ── Group 1: Workspace ─────────────────────────────────────────
        lbl_ws = QLabel("WORKSPACE", self)
        lbl_ws.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {Colors.TEXT_MUTED}; letter-spacing: 1px; padding: 6px 6px 2px;")
        layout.addWidget(lbl_ws)

        self.btn_device = NavButton("⌂", "Device", "", self)
        self.btn_files = NavButton("▣", "Files & Apps", "", self)
        self.btn_acquisition = NavButton("◈", "Acquisition", "", self)

        layout.addWidget(self.btn_device)
        layout.addWidget(self.btn_files)
        layout.addWidget(self.btn_acquisition)

        layout.addSpacing(12)

        # ── Group 2: Advanced ──────────────────────────────────────────
        lbl_adv = QLabel("ADVANCED", self)
        lbl_adv.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {Colors.TEXT_MUTED}; letter-spacing: 1px; padding: 6px 6px 2px;")
        layout.addWidget(lbl_adv)

        self.btn_developer = NavButton("⌘", "Developer Tools", "DDI", self)
        self.btn_restore = NavButton("↯", "Recovery & Restore", "", self)
        self.btn_syslog = NavButton("≋", "Live Syslog", "", self)

        layout.addWidget(self.btn_developer)
        layout.addWidget(self.btn_restore)
        layout.addWidget(self.btn_syslog)

        layout.addStretch()

        # ── Bottom Connection Card ────────────────────────────────────
        self.device_card = DeviceStatusCard(self)
        layout.addWidget(self.device_card)

        # Hook up signals
        self.nav_buttons = [
            self.btn_device,
            self.btn_files,
            self.btn_acquisition,
            self.btn_developer,
            self.btn_restore,
            self.btn_syslog,
        ]

        for idx, btn in enumerate(self.nav_buttons):
            btn.clicked.connect(lambda checked=False, i=idx: self._on_btn_clicked(i))

        # Default select Device
        self.btn_device.setChecked(True)

    def _on_btn_clicked(self, index: int):
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
        self.workspace_changed.emit(index)

    def set_device_info(self, info: dict):
        self.device_card.set_device(info)
