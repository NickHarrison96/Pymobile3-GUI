"""
Pymobile3-GUI - Device Overview Workspace
Displays high-fidelity device information, hardware specs, battery metrics,
and direct lockdown management controls.
"""

import sys
import asyncio
import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGridLayout, QScrollArea, QSizePolicy, QMessageBox,
    QProgressBar, QLineEdit, QCheckBox, QTextBrowser
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QFont, QCursor
from pymobile3_gui.ui.theme import Colors
from pymobile3_gui.core.backend.lockdown_ops import LockdownOps


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

    async def _execute(self) -> str:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.diagnostics import DiagnosticsService

        lockdown = await create_using_usbmux(serial=self.udid)

        if self.operation == "sync_time":
            await lockdown.set_value(key="TimeIntervalSince1970",
                                     value=int(time.time()))
            return "Device time synchronized with host PC."

        async with DiagnosticsService(lockdown) as diag:
            if self.operation == "restart":
                await diag.restart()
                return "Device restart command sent."
            if self.operation == "shutdown":
                await diag.shutdown()
                return "Device shutdown command sent."
        raise ValueError(f"Unknown operation: {self.operation}")

    def run(self):
        # pymobiledevice3 10.x is async throughout: create_using_usbmux,
        # DiagnosticsService.restart/shutdown and set_value are all coroutine
        # functions. Calling them without awaiting returned un-awaited
        # coroutines, so this reported "restart command sent" while doing
        # nothing at all. This QThread has no running loop, so asyncio.run is
        # the correct bridge.
        try:
            self.finished.emit(True, asyncio.run(self._execute()))
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

        # ── 5. Lockdown Control Panel ──────────────────────────────────
        lbl_lockdown = QLabel("LOCKDOWN CONTROL PANEL", self)
        lbl_lockdown.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {Colors.TEXT_SECONDARY}; letter-spacing: 1px;")
        layout.addWidget(lbl_lockdown)

        lockdown_frame = QFrame(self)
        lockdown_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 12px;
                padding: 16px;
            }}
        """)
        ld_layout = QVBoxLayout(lockdown_frame)
        ld_layout.setContentsMargins(14, 14, 14, 14)
        ld_layout.setSpacing(14)

        # Device Name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Device Name:"))
        self.txt_device_name = QLineEdit(self)
        self.txt_device_name.setPlaceholderText("Enter new device name...")
        name_row.addWidget(self.txt_device_name, stretch=1)
        btn_get_name = QPushButton("Get", self)
        btn_get_name.clicked.connect(self._get_device_name)
        name_row.addWidget(btn_get_name)
        btn_set_name = QPushButton("Set", self)
        btn_set_name.clicked.connect(self._set_device_name)
        name_row.addWidget(btn_set_name)
        ld_layout.addLayout(name_row)

        # Info Grid
        info_grid = QGridLayout()
        info_grid.setSpacing(8)

        info_grid.addWidget(QLabel("Date:"), 0, 0)
        self.lbl_date = QLabel("Unknown", self)
        self.lbl_date.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        info_grid.addWidget(self.lbl_date, 0, 1)

        info_grid.addWidget(QLabel("Language:"), 1, 0)
        self.lbl_language = QLabel("Unknown", self)
        self.lbl_language.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        info_grid.addWidget(self.lbl_language, 1, 1)

        info_grid.addWidget(QLabel("Locale:"), 2, 0)
        self.lbl_locale = QLabel("Unknown", self)
        self.lbl_locale.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        info_grid.addWidget(self.lbl_locale, 2, 1)

        info_box = QFrame(self)
        info_box.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_SURFACE};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 8px;
                padding: 8px;
            }}
        """)
        info_btn_layout = QHBoxLayout(info_box)
        info_btn_layout.setContentsMargins(8, 4, 8, 4)
        btn_refresh_info = QPushButton("Refresh Info", self)
        btn_refresh_info.clicked.connect(self._refresh_info)
        info_btn_layout.addWidget(btn_refresh_info)
        info_grid.addWidget(info_box, 0, 2, 3, 1)

        ld_layout.addLayout(info_grid)

        # Toggles
        toggles_row = QHBoxLayout()
        self.chk_assistive = QCheckBox("Assistive Touch", self)
        self.chk_assistive.clicked.connect(self._toggle_assistive_touch)
        toggles_row.addWidget(self.chk_assistive)

        self.chk_wifi = QCheckBox("WiFi Connections", self)
        self.chk_wifi.clicked.connect(self._toggle_wifi)
        toggles_row.addWidget(self.chk_wifi)

        toggles_box = QFrame(self)
        toggles_box.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_SURFACE};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 8px;
                padding: 8px;
            }}
        """)
        toggles_btn_layout = QHBoxLayout(toggles_box)
        toggles_btn_layout.setContentsMargins(8, 4, 8, 4)
        btn_read_toggles = QPushButton("Read States", self)
        btn_read_toggles.clicked.connect(self._read_toggles)
        toggles_btn_layout.addWidget(btn_read_toggles)
        toggles_row.addWidget(toggles_box)
        toggles_row.addStretch()
        ld_layout.addLayout(toggles_row)

        # Toggle status output
        self.lbl_toggle_status = QLabel("wifi: unknown | assistive: unknown", self)
        self.lbl_toggle_status.setStyleSheet(f"font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 11px; color: {Colors.TEXT_SECONDARY};")
        ld_layout.addWidget(self.lbl_toggle_status)

        # Battery & Activation
        bottom_row = QHBoxLayout()

        battery_box = QFrame(self)
        battery_box.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_SURFACE};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 8px;
                padding: 8px;
            }}
        """)
        battery_btn_layout = QHBoxLayout(battery_box)
        battery_btn_layout.setContentsMargins(8, 4, 8, 4)
        btn_battery = QPushButton("Get Battery Info", self)
        btn_battery.clicked.connect(self._get_battery)
        battery_btn_layout.addWidget(btn_battery)
        bottom_row.addWidget(battery_box)

        activation_box = QFrame(self)
        activation_box.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_SURFACE};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 8px;
                padding: 8px;
            }}
        """)
        activation_btn_layout = QHBoxLayout(activation_box)
        activation_btn_layout.setContentsMargins(8, 4, 8, 4)
        btn_activation = QPushButton("Check Activation", self)
        btn_activation.clicked.connect(self._check_activation)
        activation_btn_layout.addWidget(btn_activation)
        bottom_row.addWidget(activation_box)

        self.lbl_activation = QLabel("Status: Not Checked", self)
        self.lbl_activation.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        bottom_row.addWidget(self.lbl_activation)
        bottom_row.addStretch()
        ld_layout.addLayout(bottom_row)

        # Battery text
        self.battery_text = QTextBrowser(self)
        self.battery_text.setMaximumHeight(100)
        self.battery_text.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {Colors.BG_SURFACE};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 8px;
                padding: 8px;
                font-family: 'JetBrains Mono', 'Consolas', monospace;
                font-size: 11px;
            }}
        """)
        self.battery_text.setPlaceholderText("Click 'Get Battery Info' to view battery details...")
        ld_layout.addWidget(self.battery_text)

        layout.addWidget(lockdown_frame)

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

    def _get_lockdown_ops(self) -> LockdownOps | None:
        udid = self._get_udid()
        if not udid:
            return None
        return LockdownOps(udid)

    def _get_device_name(self):
        ops = self._get_lockdown_ops()
        if not ops:
            return

        class _Worker(QThread):
            finished = Signal(bool, str)
            def __init__(self, ops):
                super().__init__()
                self.ops = ops
            def run(self):
                try:
                    name = asyncio.run(self.ops.get_device_name())
                    self.finished.emit(True, name)
                except Exception as e:
                    self.finished.emit(False, str(e))

        worker = _Worker(ops)
        worker.finished.connect(lambda ok, name: self.txt_device_name.setText(name) if ok else QMessageBox.critical(self, "Error", name))
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _set_device_name(self):
        ops = self._get_lockdown_ops()
        if not ops:
            return
        name = self.txt_device_name.text().strip()
        if not name:
            QMessageBox.warning(self, "No Name", "Please enter a device name.")
            return

        class _Worker(QThread):
            finished = Signal(bool, str)
            def __init__(self, ops, name):
                super().__init__()
                self.ops = ops
                self.name = name
            def run(self):
                try:
                    msg = asyncio.run(self.ops.set_device_name(self.name))
                    self.finished.emit(True, msg)
                except Exception as e:
                    self.finished.emit(False, str(e))

        worker = _Worker(ops, name)
        worker.finished.connect(lambda ok, msg: QMessageBox.information(self, "Result", msg) if ok else QMessageBox.critical(self, "Error", msg))
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _refresh_info(self):
        ops = self._get_lockdown_ops()
        if not ops:
            return

        class _Worker(QThread):
            finished = Signal(bool, str, str, str)
            def __init__(self, ops):
                super().__init__()
                self.ops = ops
            def run(self):
                async def _fetch():
                    return await asyncio.gather(
                        self.ops.get_date(),
                        self.ops.get_language(),
                        self.ops.get_locale(),
                    )
                try:
                    date, lang, locale = asyncio.run(_fetch())
                    self.finished.emit(True, date, lang, locale)
                except Exception as e:
                    self.finished.emit(False, str(e), "", "")

        worker = _Worker(ops)
        worker.finished.connect(self._on_info_refreshed)
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _on_info_refreshed(self, ok, date, lang, locale):
        if ok:
            self.lbl_date.setText(date)
            self.lbl_language.setText(lang)
            self.lbl_locale.setText(locale)
        else:
            QMessageBox.critical(self, "Error", date)

    def _read_toggles(self):
        ops = self._get_lockdown_ops()
        if not ops:
            return

        class _Worker(QThread):
            finished = Signal(bool, bool, object)
            def __init__(self, ops):
                super().__init__()
                self.ops = ops
            def run(self):
                try:
                    at = asyncio.run(self.ops.get_assistive_touch())
                    wifi = asyncio.run(self.ops.get_wifi_connections())
                    self.finished.emit(True, at, wifi)
                except Exception:
                    self.finished.emit(False, False, False)

        worker = _Worker(ops)
        worker.finished.connect(self._on_toggles_read)
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _on_toggles_read(self, ok, at, wifi):
        if ok:
            self.chk_assistive.setChecked(at)
            conn_type = self.current_device_info.get("Connection", "")
            if wifi is not None:
                wifi_str = "on" if wifi else "off"
                self.chk_wifi.setChecked(wifi)
                self.chk_wifi.setEnabled(True)
            elif conn_type == "Wi-Fi":
                wifi_str = "on"
                self.chk_wifi.setChecked(True)
                self.chk_wifi.setEnabled(True)
            else:
                wifi_str = "off"
                self.chk_wifi.setChecked(False)
                self.chk_wifi.setEnabled(False)
            at_str = "on" if at else "off"
            self.lbl_toggle_status.setText(f"wifi: {wifi_str} | assistive: {at_str}")

    def _toggle_assistive_touch(self):
        ops = self._get_lockdown_ops()
        if not ops:
            return
        state = self.chk_assistive.isChecked()

        class _Worker(QThread):
            finished = Signal(bool, str)
            def __init__(self, ops, state):
                super().__init__()
                self.ops = ops
                self.state = state
            def run(self):
                try:
                    msg = asyncio.run(self.ops.set_assistive_touch(self.state))
                    self.finished.emit(True, msg)
                except Exception as e:
                    self.finished.emit(False, str(e))

        worker = _Worker(ops, state)
        worker.finished.connect(lambda ok, msg: QMessageBox.information(self, "Result", msg) if ok else QMessageBox.critical(self, "Error", msg))
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _toggle_wifi(self):
        ops = self._get_lockdown_ops()
        if not ops:
            return
        state = self.chk_wifi.isChecked()

        class _Worker(QThread):
            finished = Signal(bool, str)
            def __init__(self, ops, state):
                super().__init__()
                self.ops = ops
                self.state = state
            def run(self):
                try:
                    msg = asyncio.run(self.ops.set_wifi_connections(self.state))
                    self.finished.emit(True, msg)
                except Exception as e:
                    self.finished.emit(False, str(e))

        worker = _Worker(ops, state)
        worker.finished.connect(lambda ok, msg: QMessageBox.information(self, "Result", msg) if ok else QMessageBox.critical(self, "Error", msg))
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _get_battery(self):
        ops = self._get_lockdown_ops()
        if not ops:
            return

        class _Worker(QThread):
            finished = Signal(bool, str)
            def __init__(self, ops):
                super().__init__()
                self.ops = ops
            def run(self):
                try:
                    info = asyncio.run(self.ops.get_battery_info())
                    if info:
                        text = "Battery Information:\n" + "-" * 30 + "\n"
                        for k, v in info.items():
                            text += f"{k}: {v}\n"
                        self.finished.emit(True, text)
                    else:
                        self.finished.emit(False, "No battery information available.")
                except Exception as e:
                    self.finished.emit(False, str(e))

        worker = _Worker(ops)
        worker.finished.connect(lambda ok, text: self.battery_text.setPlainText(text) if ok else QMessageBox.critical(self, "Error", text))
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _check_activation(self):
        ops = self._get_lockdown_ops()
        if not ops:
            return

        class _Worker(QThread):
            finished = Signal(bool, str)
            def __init__(self, ops):
                super().__init__()
                self.ops = ops
            def run(self):
                try:
                    state = asyncio.run(self.ops.get_activation_state())
                    self.finished.emit(True, state)
                except Exception as e:
                    self.finished.emit(False, str(e))

        worker = _Worker(ops)
        worker.finished.connect(self._on_activation_checked)
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _on_activation_checked(self, ok, state):
        if ok:
            is_activated = state == "Activated"
            color = Colors.SUCCESS if is_activated else Colors.DANGER
            self.lbl_activation.setText(f"Status: {state}")
            self.lbl_activation.setStyleSheet(f"color: {color};")
        else:
            self.lbl_activation.setText(f"Status: Error - {state}")
            self.lbl_activation.setStyleSheet(f"color: {Colors.DANGER};")
