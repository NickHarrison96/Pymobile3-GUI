"""
Pymobile3-GUI - Device Overview Workspace
Displays high-fidelity device information, hardware specs, battery metrics,
and direct lockdown management controls.
"""

import sys
import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGridLayout, QScrollArea, QSizePolicy, QMessageBox,
    QProgressBar
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QFont, QCursor
from pymobile3_gui.ui.theme import Colors


class SpecCard(QFrame):
    """Grid card for hardware/software parameters."""
    def __init__(self, title: str, value: str = "—", parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 10px;
                padding: 10px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        self.lbl_title = QLabel(title.upper(), self)
        self.lbl_title.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {Colors.TEXT_SECONDARY}; letter-spacing: 0.5px;")
        
        self.lbl_val = QLabel(value, self)
        self.lbl_val.setStyleSheet("font-size: 13px; font-weight: 600; color: #ffffff;")
        self.lbl_val.setTextInteractionFlags(Qt.TextSelectableByMouse)

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_val)

    def set_value(self, val: str):
        self.lbl_val.setText(val or "—")


class ActionCard(QFrame):
    """Clickable shortcut card for frequent destinations."""
    clicked = Signal()

    def __init__(self, icon: str, title: str, desc: str, parent=None):
        super().__init__(parent)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 12px;
                padding: 14px;
            }}
            QFrame:hover {{
                background-color: {Colors.BG_CARD_HOVER};
                border-color: {Colors.BORDER_HOVER};
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        top = QHBoxLayout()
        lbl_icon = QLabel(icon, self)
        lbl_icon.setStyleSheet(f"""
            background-color: #1c2433; color: #58a6ff;
            border-radius: 6px; padding: 4px 8px; font-size: 14px; font-weight: 700;
        """)
        top.addWidget(lbl_icon)
        top.addStretch()
        layout.addLayout(top)

        lbl_title = QLabel(title, self)
        lbl_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #ffffff;")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel(desc, self)
        lbl_desc.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_SECONDARY};")
        lbl_desc.setWordWrap(True)
        layout.addWidget(lbl_desc)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class DeviceWorker(QThread):
    """Background worker for device operations (reboot, shutdown, sync)."""
    finished = Signal(bool, str)

    def __init__(self, operation: str, udid: str):
        super().__init__()
        self.operation = operation
        self.udid = udid

    def run(self):
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.diagnostics import DiagnosticsService

            ld = create_using_usbmux(serial=self.udid)
            diag = DiagnosticsService(ld)

            if self.operation == "restart":
                diag.restart()
                self.finished.emit(True, "Device restart command sent.")
            elif self.operation == "shutdown":
                diag.shutdown()
                self.finished.emit(True, "Device shutdown command sent.")
            elif self.operation == "sync_time":
                ld.set_value(key="TimeIntervalSince1970", value=int(time.time()))
                self.finished.emit(True, "Device time synchronized with host PC.")
            else:
                self.finished.emit(False, f"Unknown operation: {self.operation}")
        except Exception as e:
            self.finished.emit(False, str(e))


class DeviceView(QWidget):
    navigate_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_device_info = {}
        self._workers = []

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")

        content_widget = QWidget(scroll)
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(24)

        # ── 1. Hero Device Header ─────────────────────────────────────
        self.hero_frame = QFrame(self)
        self.hero_frame.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #1a2438, stop:1 #141a25);
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 16px;
                padding: 16px;
            }}
        """)
        hero_layout = QHBoxLayout(self.hero_frame)
        hero_layout.setContentsMargins(18, 16, 18, 16)
        hero_layout.setSpacing(20)

        # Device silhouette icon
        self.phone_icon = QLabel("📱", self)
        self.phone_icon.setStyleSheet("font-size: 44px; padding: 4px;")
        hero_layout.addWidget(self.phone_icon)

        # Title & Subtitle
        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(4)
        self.lbl_hero_name = QLabel("No Device Connected", self)
        self.lbl_hero_name.setStyleSheet("font-size: 22px; font-weight: 750; color: #ffffff; letter-spacing: -0.5px;")
        self.lbl_hero_sub = QLabel("Plug in an iPhone or iPad via USB or Wi-Fi to start inspecting and managing.", self)
        self.lbl_hero_sub.setStyleSheet(f"font-size: 12px; color: {Colors.TEXT_SECONDARY};")
        title_vbox.addWidget(self.lbl_hero_name)
        title_vbox.addWidget(self.lbl_hero_sub)
        hero_layout.addLayout(title_vbox)

        hero_layout.addStretch()

        # Status badge
        self.lbl_ready_badge = QLabel("○ Standby", self)
        self.lbl_ready_badge.setStyleSheet(f"""
            background-color: {Colors.BG_CARD}; color: {Colors.TEXT_SECONDARY};
            border: 1px solid {Colors.BORDER_DEFAULT}; border-radius: 12px;
            padding: 5px 14px; font-size: 11px; font-weight: 700;
        """)
        hero_layout.addWidget(self.lbl_ready_badge)

        layout.addWidget(self.hero_frame)

        # ── 2. Quick Action Cards ──────────────────────────────────────
        lbl_shortcuts = QLabel("START HERE", self)
        lbl_shortcuts.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {Colors.TEXT_SECONDARY}; letter-spacing: 1px;")
        layout.addWidget(lbl_shortcuts)

        actions_grid = QHBoxLayout()
        actions_grid.setSpacing(14)

        card_syslog = ActionCard("≋", "Live Syslog", "Stream, filter and copy device syslog in real time.", self)
        card_syslog.clicked.connect(lambda: self.navigate_requested.emit(5))

        card_acq = ActionCard("◈", "Forensic Acquisition", "Generate standard Logical, Logical+, or PRFS archives.", self)
        card_acq.clicked.connect(lambda: self.navigate_requested.emit(2))

        card_files = ActionCard("▣", "Files & Applications", "Browse media, sandboxes, and installed app bundles.", self)
        card_files.clicked.connect(lambda: self.navigate_requested.emit(1))

        actions_grid.addWidget(card_syslog)
        actions_grid.addWidget(card_acq)
        actions_grid.addWidget(card_files)
        layout.addLayout(actions_grid)

        # ── 3. Hardware & Identity Specs Grid ──────────────────────────
        lbl_specs = QLabel("DEVICE IDENTITY & SYSTEM SPECIFICATIONS", self)
        lbl_specs.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {Colors.TEXT_SECONDARY}; letter-spacing: 1px;")
        layout.addWidget(lbl_specs)

        specs_layout = QGridLayout()
        specs_layout.setSpacing(12)

        self.spec_model = SpecCard("Model", "—", self)
        self.spec_os = SpecCard("iOS Version", "—", self)
        self.spec_udid = SpecCard("Serial / UDID", "—", self)
        self.spec_ecid = SpecCard("ECID", "—", self)
        self.spec_imei = SpecCard("IMEI", "—", self)
        self.spec_battery = SpecCard("Battery Health", "—", self)
        self.spec_activation = SpecCard("Activation State", "—", self)
        self.spec_devmode = SpecCard("Developer Mode", "—", self)

        specs_layout.addWidget(self.spec_model, 0, 0)
        specs_layout.addWidget(self.spec_os, 0, 1)
        specs_layout.addWidget(self.spec_udid, 0, 2)
        specs_layout.addWidget(self.spec_ecid, 0, 3)
        specs_layout.addWidget(self.spec_imei, 1, 0)
        specs_layout.addWidget(self.spec_battery, 1, 1)
        specs_layout.addWidget(self.spec_activation, 1, 2)
        specs_layout.addWidget(self.spec_devmode, 1, 3)

        layout.addLayout(specs_layout)

        # ── 4. Quick Lockdown Controls ────────────────────────────────
        lbl_ctrl = QLabel("DEVICE ACTIONS & LOCKDOWN CONTROLS", self)
        lbl_ctrl.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {Colors.TEXT_SECONDARY}; letter-spacing: 1px;")
        layout.addWidget(lbl_ctrl)

        ctrl_box = QHBoxLayout()
        ctrl_box.setSpacing(10)

        self.btn_reboot = QPushButton("⟳ Restart Device", self)
        self.btn_reboot.clicked.connect(self._restart_device)
        self.btn_shutdown = QPushButton("⏻ Shut Down", self)
        self.btn_shutdown.clicked.connect(self._shutdown_device)
        self.btn_sync_time = QPushButton("⏰ Sync Time", self)
        self.btn_sync_time.clicked.connect(self._sync_time)

        ctrl_box.addWidget(self.btn_reboot)
        ctrl_box.addWidget(self.btn_shutdown)
        ctrl_box.addWidget(self.btn_sync_time)
        ctrl_box.addStretch()

        layout.addLayout(ctrl_box)

        layout.addStretch()
        scroll.setWidget(content_widget)

        main_vbox = QVBoxLayout(self)
        main_vbox.setContentsMargins(0, 0, 0, 0)
        main_vbox.addWidget(scroll)

    def update_device(self, info: dict):
        self.current_device_info = info or {}
        if info and info.get("Trusted"):
            name = info.get("DeviceName") or info.get("Model") or "iPhone"
            os_ver = info.get("OS", "iOS")
            conn = info.get("Connection", "USB")

            self.lbl_hero_name.setText(name)
            self.lbl_hero_sub.setText(f"{os_ver} · Connected via {conn} · Device Paired & Trusted")
            self.lbl_ready_badge.setText("● Connected & Secure")
            self.lbl_ready_badge.setStyleSheet(f"""
                background-color: {Colors.SUCCESS_BG}; color: {Colors.SUCCESS};
                border: 1px solid {Colors.SUCCESS_BORDER}; border-radius: 12px;
                padding: 5px 14px; font-size: 11px; font-weight: 700;
            """)

            self.spec_model.set_value(f"{info.get('Model', '—')} ({info.get('ProductType', '—')})")
            self.spec_os.set_value(info.get("OS", "—"))
            self.spec_udid.set_value(info.get("Serial_UDID", "—"))
            self.spec_ecid.set_value(info.get("ECID", "—"))
            self.spec_imei.set_value(info.get("IMEI", "—"))
            self.spec_battery.set_value(info.get("Battery", "—"))
            self.spec_activation.set_value(info.get("Activation", "—"))
            self.spec_devmode.set_value("Enabled" if info.get("DeveloperMode") else "Disabled")
        else:
            self.lbl_hero_name.setText("No Device Connected")
            self.lbl_hero_sub.setText("Plug in an iPhone or iPad via USB or Wi-Fi to start inspecting and managing.")
            self.lbl_ready_badge.setText("○ Standby")
            self.lbl_ready_badge.setStyleSheet(f"""
                background-color: {Colors.BG_CARD}; color: {Colors.TEXT_SECONDARY};
                border: 1px solid {Colors.BORDER_DEFAULT}; border-radius: 12px;
                padding: 5px 14px; font-size: 11px; font-weight: 700;
            """)

            for card in (self.spec_model, self.spec_os, self.spec_udid, self.spec_ecid,
                         self.spec_imei, self.spec_battery, self.spec_activation, self.spec_devmode):
                card.set_value("—")

    def _get_udid(self) -> str | None:
        udid = self.current_device_info.get("Serial_UDID")
        if not udid:
            QMessageBox.warning(self, "No Device", "Please connect a device first.")
            return None
        return udid

    def _run_device_op(self, operation: str, confirm_msg: str) -> bool:
        udid = self._get_udid()
        if not udid:
            return False
        reply = QMessageBox.question(self, operation.title(), confirm_msg,
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return False
        worker = DeviceWorker(operation, udid)
        worker.finished.connect(lambda ok, msg: self._on_device_op_done(ok, msg))
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()
        self._set_buttons_enabled(False)
        return True

    def _set_buttons_enabled(self, enabled: bool):
        self.btn_reboot.setEnabled(enabled)
        self.btn_shutdown.setEnabled(enabled)
        self.btn_sync_time.setEnabled(enabled)

    def _on_device_op_done(self, ok: bool, msg: str):
        self._set_buttons_enabled(True)
        if ok:
            QMessageBox.information(self, "Success", msg)
        else:
            QMessageBox.critical(self, "Error", f"Failed: {msg}")

    def _restart_device(self):
        self._run_device_op("restart", "Are you sure you want to reboot this device?")

    def _shutdown_device(self):
        self._run_device_op("shutdown", "Are you sure you want to power off this device?")

    def _sync_time(self):
        udid = self._get_udid()
        if not udid:
            return
        worker = DeviceWorker("sync_time", udid)
        worker.finished.connect(lambda ok, msg: self._on_device_op_done(ok, msg))
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()
        self._set_buttons_enabled(False)
