"""
Pymobile3-GUI - Recovery & IPSW Restore Workspace
Full-page firmware flashing engine (idevicerestore) paired with interactive
Recovery Mode and DFU Mode hardware wizards, plus the checkm8 SSH Ramdisk
tool (build / boot / erase / dump) for A7-A11 and T2 devices.
"""

import os
import json
import subprocess
import threading
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QCheckBox, QFileDialog, QTabWidget,
    QScrollArea, QMessageBox, QTextBrowser, QComboBox
)
from PySide6.QtCore import Qt, QTimer, QProcess, Signal
from PySide6.QtGui import QCursor
from pymobile3_gui.ui.theme import Colors
from pymobile3_gui.core.task_manager import TaskManager
from pymobile3_gui.core.backend.resource_manager import safe_run_command
from pymobile3_gui.core.backend.paths import pmd3_cmd, backups_dir
from pymobile3_gui.core.backend.backup_engine import (
    resolve_backup_source, restore_backup
)
from pymobile3_gui.core.backend import ramdisk_manager as ram


class RestoreView(QWidget):
    _ram_versions_ready = Signal(str, list)  # product, [{version, signed}]
    _ram_wsl_ready = Signal(bool, str)       # ok, detail

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(20)

        # ── Header ───────────────────────────────────────────────────
        header_vbox = QVBoxLayout()
        header_vbox.setSpacing(2)
        lbl_eyebrow = QLabel("FIRMWARE FLASHING & BOOTLOADER RECOVERY", self)
        lbl_eyebrow.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {Colors.TEXT_MUTED}; letter-spacing: 1px;")
        header_vbox.addWidget(lbl_eyebrow)

        lbl_title = QLabel("Recovery & Restore", self)
        lbl_title.setStyleSheet("font-size: 24px; font-weight: 750; color: #ffffff; letter-spacing: -0.5px;")
        header_vbox.addWidget(lbl_title)
        layout.addLayout(header_vbox)

        # ── Tabs ─────────────────────────────────────────────────────
        self.tabs = QTabWidget(self)
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {Colors.BORDER_DEFAULT};
                background: {Colors.BG_SURFACE};
                border-radius: 12px;
                padding: 16px;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {Colors.TEXT_SECONDARY};
                padding: 8px 18px;
                font-weight: 600;
                font-size: 12px;
                border-bottom: 2px solid transparent;
            }}
            QTabBar::tab:selected {{
                color: #ffffff;
                border-bottom: 2px solid {Colors.ACCENT_PRIMARY};
            }}
        """)

        primary_btn_qss = f"""
            QPushButton {{
                background-color: {Colors.ACCENT_PRIMARY};
                color: #ffffff;
                border: 1px solid #3b82f6;
                border-radius: 8px;
                padding: 10px 24px;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {Colors.ACCENT_PRIMARY_HOVER};
            }}
        """

        # ── Tab 1: IPSW Restore ──────────────────────────────────────
        ipsw_tab = QWidget()
        ipsw_layout = QVBoxLayout(ipsw_tab)
        ipsw_layout.setContentsMargins(8, 8, 8, 8)
        ipsw_layout.setSpacing(14)

        lbl_ipsw_desc = QLabel("Flash official signed Apple IPSW firmware files to your device using idevicerestore.", self)
        lbl_ipsw_desc.setStyleSheet(f"font-size: 12px; color: {Colors.TEXT_SECONDARY};")
        ipsw_layout.addWidget(lbl_ipsw_desc)

        file_card = QFrame(self)
        file_card.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 10px;
                padding: 14px;
            }}
        """)
        fc_layout = QVBoxLayout(file_card)
        fc_layout.setSpacing(10)

        lbl_file = QLabel("IPSW Firmware File Path:")
        lbl_file.setStyleSheet("font-weight: 600; font-size: 12px;")
        fc_layout.addWidget(lbl_file)

        browse_row = QHBoxLayout()
        self.txt_ipsw_path = QLineEdit(self)
        self.txt_ipsw_path.setPlaceholderText("Select or enter path to .ipsw file...")
        browse_row.addWidget(self.txt_ipsw_path, stretch=1)

        btn_browse = QPushButton("Browse...", self)
        btn_browse.clicked.connect(self._browse_ipsw)
        browse_row.addWidget(btn_browse)
        fc_layout.addLayout(browse_row)

        self.chk_erase = QCheckBox("Erase all user data (Full clean factory restore)", self)
        self.chk_erase.setStyleSheet("font-size: 12px; color: #fca5a5;")
        fc_layout.addWidget(self.chk_erase)
        ipsw_layout.addWidget(file_card)

        self.btn_flash = QPushButton("⚡ Begin IPSW Firmware Restore", self)
        self.btn_flash.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_flash.setStyleSheet(primary_btn_qss)
        self.btn_flash.clicked.connect(self._start_ipsw_restore)
        ipsw_layout.addWidget(self.btn_flash)
        ipsw_layout.addStretch()

        self.tabs.addTab(ipsw_tab, "⚡ IPSW Restore")

        # ── Tab 2: Backup Restore ─────────────────────────────────────
        backup_tab = QWidget()
        backup_layout = QVBoxLayout(backup_tab)
        backup_layout.setContentsMargins(8, 8, 8, 8)
        backup_layout.setSpacing(14)

        lbl_bk_desc = QLabel(
            "Restore an iTunes/Finder-style backup to the connected device "
            "using mobilebackup2 — no firmware reflash involved.", self)
        lbl_bk_desc.setStyleSheet(f"font-size: 12px; color: {Colors.TEXT_SECONDARY};")
        backup_layout.addWidget(lbl_bk_desc)

        bk_card = QFrame(self)
        bk_card.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 10px;
                padding: 14px;
            }}
        """)
        bk_v = QVBoxLayout(bk_card)
        bk_v.setSpacing(10)

        lbl_bk_folder = QLabel("Backup Folder:")
        lbl_bk_folder.setStyleSheet("font-weight: 600; font-size: 12px;")
        bk_v.addWidget(lbl_bk_folder)

        bk_browse_row = QHBoxLayout()
        self.txt_backup_dir = QLineEdit(self)
        self.txt_backup_dir.setText(backups_dir())
        self.txt_backup_dir.setPlaceholderText(
            "Folder containing the <UDID> backup set...")
        bk_browse_row.addWidget(self.txt_backup_dir, stretch=1)
        btn_browse_bk = QPushButton("Browse...", self)
        btn_browse_bk.clicked.connect(self._browse_backup_dir)
        bk_browse_row.addWidget(btn_browse_bk)
        bk_v.addLayout(bk_browse_row)

        opt_row = QHBoxLayout()
        lbl_pw = QLabel("Password:")
        lbl_pw.setStyleSheet("font-size: 12px;")
        opt_row.addWidget(lbl_pw)
        self.txt_backup_password = QLineEdit(self)
        self.txt_backup_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_backup_password.setPlaceholderText("Encrypted backups only")
        opt_row.addWidget(self.txt_backup_password, stretch=1)
        self.chk_reboot = QCheckBox("Reboot when done", self)
        self.chk_reboot.setChecked(True)
        opt_row.addWidget(self.chk_reboot)
        bk_v.addLayout(opt_row)

        backup_layout.addWidget(bk_card)

        lbl_bk_warn = QLabel(
            "⚠ Restoring overwrites data on the device. Keep it unlocked and connected.",
            self)
        lbl_bk_warn.setStyleSheet(f"font-size: 12px; color: #fca5a5;")
        backup_layout.addWidget(lbl_bk_warn)

        self.btn_backup_restore = QPushButton("⚡ Begin Backup Restore", self)
        self.btn_backup_restore.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_backup_restore.setStyleSheet(primary_btn_qss)
        self.btn_backup_restore.clicked.connect(self._start_backup_restore)
        backup_layout.addWidget(self.btn_backup_restore)
        backup_layout.addStretch()

        self.tabs.addTab(backup_tab, "📤 Backup Restore")

        # ── Tab 3: SSH Ramdisk ─────────────────────────────────────
        self._ram_dev = None
        self._ram_busy = False
        self._ram_probe_running = False
        self._dfu_proc = None
        self._ram_versions_loading = False
        self._ram_versions_product = ""
        self._ram_wsl_state = None  # None=unknown, True=ready, False=missing

        ram_tab = QWidget()
        self._ram_tab = ram_tab
        ram_layout = QVBoxLayout(ram_tab)
        ram_layout.setContentsMargins(8, 8, 8, 8)
        ram_layout.setSpacing(12)

        lbl_ram_desc = QLabel(
            "Build and boot a checkm8 SSH ramdisk (A7–A11 / T2) for filesystem "
            "access, on-board SHSH dumps and recovery utilities. Build steps run "
            "the bundled SSHRD tools inside WSL; DFU and USB steps run natively "
            "through gaster and irecovery.", self)
        lbl_ram_desc.setStyleSheet(f"font-size: 12px; color: {Colors.TEXT_SECONDARY};")
        lbl_ram_desc.setWordWrap(True)
        ram_layout.addWidget(lbl_ram_desc)

        ram_card_qss = f"""
            QFrame {{
                background-color: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 10px;
                padding: 14px;
            }}
        """
        secondary_btn_qss = f"""
            QPushButton {{
                background-color: {Colors.BG_CARD};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {Colors.BG_CARD_HOVER};
                border-color: {Colors.BORDER_HOVER};
            }}
            QPushButton:disabled {{
                color: {Colors.TEXT_MUTED};
            }}
        """
        danger_btn_qss = f"""
            QPushButton {{
                background-color: {Colors.DANGER_BG};
                color: #ffd7d5;
                border: 1px solid {Colors.DANGER_BORDER};
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {Colors.DANGER};
                color: #ffffff;
            }}
            QPushButton:disabled {{
                color: {Colors.TEXT_MUTED};
            }}
        """

        pre_card = QFrame(self)
        pre_card.setStyleSheet(ram_card_qss)
        pre_v = QVBoxLayout(pre_card)
        pre_v.setSpacing(6)

        lbl_pre_title = QLabel("Prerequisites", self)
        lbl_pre_title.setStyleSheet("font-weight: 600; font-size: 12px;")
        pre_v.addWidget(lbl_pre_title)

        self.lbl_ram_wsl = QLabel("WSL (Ubuntu): checking…", self)
        self.lbl_ram_wsl.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {Colors.TEXT_SECONDARY};")
        pre_v.addWidget(self.lbl_ram_wsl)

        self.lbl_ram_dfu = QLabel("DFU device: not detected", self)
        self.lbl_ram_dfu.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {Colors.TEXT_SECONDARY};")
        pre_v.addWidget(self.lbl_ram_dfu)

        lbl_ram_hint = QLabel(
            "Put the device in DFU mode (see the DFU Mode Guide tab) and give "
            "Apple's DFU device a WinUSB/libusbk driver with Zadig.", self)
        lbl_ram_hint.setStyleSheet(
            f"font-size: 11px; color: {Colors.TEXT_MUTED};")
        lbl_ram_hint.setWordWrap(True)
        pre_v.addWidget(lbl_ram_hint)
        ram_layout.addWidget(pre_card)

        fw_card = QFrame(self)
        fw_card.setStyleSheet(ram_card_qss)
        fw_v = QVBoxLayout(fw_card)
        fw_v.setSpacing(8)

        lbl_fw_title = QLabel("Firmware", self)
        lbl_fw_title.setStyleSheet("font-weight: 600; font-size: 12px;")
        fw_v.addWidget(lbl_fw_title)

        fw_row = QHBoxLayout()
        lbl_fw = QLabel("Ramdisk iOS version:", self)
        lbl_fw.setStyleSheet("font-size: 12px;")
        fw_row.addWidget(lbl_fw)
        self.cmb_ram_version = QComboBox(self)
        self.cmb_ram_version.setMinimumWidth(200)
        self.cmb_ram_version.addItem(
            "Connect a DFU device to list versions", "")
        fw_row.addWidget(self.cmb_ram_version, stretch=1)
        btn_fw_refresh = QPushButton("Refresh", self)
        btn_fw_refresh.setCursor(QCursor(Qt.PointingHandCursor))
        btn_fw_refresh.setStyleSheet(secondary_btn_qss)
        btn_fw_refresh.clicked.connect(self._ram_refresh_versions)
        fw_row.addWidget(btn_fw_refresh)
        fw_v.addLayout(fw_row)

        self.lbl_ram_version_warn = QLabel("", self)
        self.lbl_ram_version_warn.setWordWrap(True)
        self.lbl_ram_version_warn.setStyleSheet(
            f"font-size: 12px; color: {Colors.DANGER};")
        self.lbl_ram_version_warn.hide()
        fw_v.addWidget(self.lbl_ram_version_warn)
        self.cmb_ram_version.currentIndexChanged.connect(
            self._update_ram_version_warn)
        ram_layout.addWidget(fw_card)

        opt_card = QFrame(self)
        opt_card.setStyleSheet(ram_card_qss)
        opt_v = QVBoxLayout(opt_card)
        opt_v.setSpacing(8)

        lbl_opt_title = QLabel("Options", self)
        lbl_opt_title.setStyleSheet("font-weight: 600; font-size: 12px;")
        opt_v.addWidget(lbl_opt_title)

        self.chk_trollstore = QCheckBox(
            "Inject TrollStore into the ramdisk boot-args", self)
        self.chk_trollstore.setStyleSheet("font-size: 12px;")
        opt_v.addWidget(self.chk_trollstore)

        self.txt_trollstore_app = QLineEdit(self)
        self.txt_trollstore_app.setPlaceholderText(
            "Path of TrollStore.app inside the ramdisk "
            "(e.g. /var/containers/Bundle/Application/…/TrollStore.app)")
        self.txt_trollstore_app.setEnabled(False)
        self.chk_trollstore.toggled.connect(
            self.txt_trollstore_app.setEnabled)
        opt_v.addWidget(self.txt_trollstore_app)

        dump_row = QHBoxLayout()
        lbl_dump = QLabel("SHSH dump output:", self)
        lbl_dump.setStyleSheet("font-size: 12px;")
        dump_row.addWidget(lbl_dump)
        self.txt_dump_path = QLineEdit(self)
        self.txt_dump_path.setText(ram.default_dump_path())
        dump_row.addWidget(self.txt_dump_path, stretch=1)
        opt_v.addLayout(dump_row)
        ram_layout.addWidget(opt_card)

        self.btn_ram_create = QPushButton("🔐 Create SSH Ramdisk", self)
        self.btn_ram_create.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_ram_create.setStyleSheet(primary_btn_qss)
        self.btn_ram_create.clicked.connect(self._start_ram_create)
        ram_layout.addWidget(self.btn_ram_create)

        ram_row1 = QHBoxLayout()
        ram_row1.setSpacing(8)
        self.btn_ram_boot = QPushButton("▶ Boot Ramdisk", self)
        self.btn_ram_erase = QPushButton("⚠ Erase Device", self)
        self.btn_ram_reboot = QPushButton("↻ Reboot", self)
        for btn in (self.btn_ram_boot, self.btn_ram_reboot):
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setStyleSheet(secondary_btn_qss)
        self.btn_ram_erase.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_ram_erase.setStyleSheet(danger_btn_qss)
        self.btn_ram_boot.clicked.connect(self._start_ram_boot)
        self.btn_ram_erase.clicked.connect(self._start_ram_erase)
        self.btn_ram_reboot.clicked.connect(self._start_ram_reboot)
        ram_row1.addWidget(self.btn_ram_boot, stretch=1)
        ram_row1.addWidget(self.btn_ram_erase, stretch=1)
        ram_row1.addWidget(self.btn_ram_reboot, stretch=1)
        ram_layout.addLayout(ram_row1)

        ram_row2 = QHBoxLayout()
        ram_row2.setSpacing(8)
        self.btn_ram_dump = QPushButton("Dump SHSH Blobs", self)
        self.btn_ram_clean = QPushButton("Clean Workspace", self)
        self.btn_ram_console = QPushButton("Open SSH Console", self)
        for btn in (self.btn_ram_dump, self.btn_ram_clean,
                    self.btn_ram_console):
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setStyleSheet(secondary_btn_qss)
            ram_row2.addWidget(btn, stretch=1)
        self.btn_ram_dump.clicked.connect(self._start_ram_dump)
        self.btn_ram_clean.clicked.connect(self._start_ram_clean)
        self.btn_ram_console.clicked.connect(self._start_ram_console)
        ram_layout.addLayout(ram_row2)

        lbl_ram_note = QLabel(
            "Only the build steps touch the IPSW; Boot / Erase need the device "
            "back in DFU mode and never flash signed firmware.", self)
        lbl_ram_note.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_MUTED};")
        lbl_ram_note.setWordWrap(True)
        ram_layout.addWidget(lbl_ram_note)
        ram_layout.addStretch()

        self._ram_buttons = [
            self.btn_ram_create, self.btn_ram_boot, self.btn_ram_erase,
            self.btn_ram_reboot, self.btn_ram_dump, self.btn_ram_clean,
            self.btn_ram_console,
        ]

        self.tabs.insertTab(2, ram_tab, "🔐 SSH Ramdisk")

        self._dfu_timer = QTimer(self)
        self._dfu_timer.setInterval(1500)
        self._dfu_timer.timeout.connect(self._poll_dfu)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Single-shot watchdog for the DFU probe: a QProcess that fails to start
        # (or hangs on a wedged WinUSB driver) never emits `finished`, so without
        # this _ram_probe_running would latch True and freeze the whole tab.
        self._dfu_probe_timeout = QTimer(self)
        self._dfu_probe_timeout.setSingleShot(True)
        self._dfu_probe_timeout.setInterval(8000)
        self._dfu_probe_timeout.timeout.connect(self._on_dfu_probe_timeout)

        tm = TaskManager.instance()
        tm.task_started.connect(self._on_ram_task_started)
        tm.task_finished.connect(self._on_ram_task_finished)
        tm.task_finished.connect(self._on_restore_task_finished)
        self._ram_versions_ready.connect(self._on_ram_versions_ready)
        self._ram_wsl_ready.connect(self._on_ram_wsl_ready)
        threading.Thread(target=self._ram_probe_wsl, daemon=True).start()

        # ── Tab 4: Recovery Mode Guide ───────────────────────────────
        rec_tab = QWidget()
        rec_layout = QVBoxLayout(rec_tab)
        rec_layout.setContentsMargins(8, 8, 8, 8)
        rec_layout.setSpacing(12)

        browser_rec = QTextBrowser(self)
        browser_rec.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 10px;
                padding: 16px;
                color: #e2e8f0;
                font-size: 13px;
            }}
        """)
        browser_rec.setHtml("""
            <h3 style="color:#60a5fa; margin-top:0;">Entering Recovery Mode</h3>
            <p>Recovery mode allows firmware reinstallation even when iOS fails to boot.</p>
            <hr style="border: 0; border-top: 1px solid #334155; margin: 12px 0;">
            <h4 style="color:#ffffff;">iPhone 8, SE (2nd/3rd gen), iPhone X, 11, 12, 13, 14, 15, 16:</h4>
            <ol>
                <li>Connect device to computer via USB.</li>
                <li>Quickly press and release <b>Volume Up</b>.</li>
                <li>Quickly press and release <b>Volume Down</b>.</li>
                <li>Press and hold the <b>Side Power Button</b> until the recovery screen (computer & cable icon) appears.</li>
            </ol>
            <h4 style="color:#ffffff;">iPhone 7 & iPhone 7 Plus:</h4>
            <ol>
                <li>Connect to computer.</li>
                <li>Press and hold both <b>Volume Down</b> and the <b>Side Power Button</b> simultaneously.</li>
                <li>Keep holding until the recovery screen appears.</li>
            </ol>
            <h4 style="color:#ffffff;">iPads without a Home Button:</h4>
            <ol>
                <li>Press and release <b>Volume button closest to top</b>.</li>
                <li>Press and release <b>Volume button farthest from top</b>.</li>
                <li>Press and hold <b>Top Power button</b> until recovery screen appears.</li>
            </ol>
        """)
        rec_layout.addWidget(browser_rec)
        self.tabs.addTab(rec_tab, "🛠️ Recovery Mode Guide")

        # ── Tab 5: DFU Mode Guide ────────────────────────────────────
        dfu_tab = QWidget()
        dfu_layout = QVBoxLayout(dfu_tab)
        dfu_layout.setContentsMargins(8, 8, 8, 8)
        dfu_layout.setSpacing(12)

        browser_dfu = QTextBrowser(self)
        browser_dfu.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 10px;
                padding: 16px;
                color: #e2e8f0;
                font-size: 13px;
            }}
        """)
        browser_dfu.setHtml("""
            <h3 style="color:#fbbf24; margin-top:0;">Entering DFU Mode (Device Firmware Upgrade)</h3>
            <p>DFU mode bypasses iBoot/OS bootloaders entirely. <b>The screen must remain completely black.</b></p>
            <hr style="border: 0; border-top: 1px solid #334155; margin: 12px 0;">
            <h4 style="color:#ffffff;">iPhone 8, X, XS, 11, 12, 13, 14, 15, 16:</h4>
            <ol>
                <li>Connect device to computer via USB.</li>
                <li>Quickly press <b>Volume Up</b>, then <b>Volume Down</b>.</li>
                <li>Hold the <b>Side Button</b> for 10 seconds until the screen turns black.</li>
                <li>While continuing to hold the <b>Side Button</b>, also press and hold <b>Volume Down</b> for 5 seconds.</li>
                <li>Release the <b>Side Button</b>, but <i>keep holding</i> <b>Volume Down</b> for another 10 seconds.</li>
                <li>If the Apple logo appears, you held too long. Try again.</li>
            </ol>
        """)
        dfu_layout.addWidget(browser_dfu)
        self.tabs.addTab(dfu_tab, "⚡ DFU Mode Guide")

        layout.addWidget(self.tabs)

    def _browse_ipsw(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select Apple IPSW Firmware File", "", "IPSW Files (*.ipsw)")
        if f:
            self.txt_ipsw_path.setText(f)

    def _browse_backup_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "Select Backup Folder",
            self.txt_backup_dir.text().strip() or backups_dir())
        if d:
            self.txt_backup_dir.setText(d)

    def _start_backup_restore(self):
        folder = self.txt_backup_dir.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "Missing Folder", "Please select a valid backup folder.")
            return

        password = self.txt_backup_password.text()
        reboot = self.chk_reboot.isChecked()

        reply = QMessageBox.question(
            self, "Confirm Backup Restore",
            "Restoring overwrites data on the connected device.\n\n"
            f"Backup: {folder}\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        def run_job(progress_cb, log_cb, is_cancelled_cb):
            progress_cb(2, step="Validating Backup", detail=folder)
            try:
                target, source = resolve_backup_source(folder)
            except ValueError as e:
                raise Exception(str(e))
            log_cb(f"Backup set: {source or 'auto-detect (connected device)'}")

            progress_cb(6, step="Connecting to Device", detail="Querying usbmux for a device...")
            ok, out = safe_run_command(
                pmd3_cmd(["usbmux", "list"]), timeout=15, include_stderr=True)
            devices = []
            # Combined output may carry log lines around the JSON — bracket
            # extraction keeps the parse honest either way.
            start, end = out.find("["), out.rfind("]")
            if ok and 0 <= start < end:
                try:
                    devices = json.loads(out[start:end + 1])
                except ValueError:
                    devices = []
            if not isinstance(devices, list) or not devices:
                raise Exception(
                    "No iOS device is visible over USB. Connect and unlock "
                    "the device, accept the trust prompt, then retry.")
            log_cb(f"Device visible ({len(devices)} usbmux entries).")

            progress_cb(10, step="Restoring Backup", detail="Starting mobilebackup2 restore...")
            restore_backup(
                target, password=password, reboot=reboot, source=source,
                base=10, span=85,
                progress_cb=progress_cb, log_cb=log_cb,
                is_cancelled_cb=is_cancelled_cb,
            )
            progress_cb(100, step="Finalizing", detail="Restore completed.")

        tm = TaskManager.instance()
        task_id = "backup_restore_" + str(os.getpid())
        if tm.is_task_running(task_id):
            QMessageBox.information(
                self, "Busy", "A backup restore is already running.")
            return
        self.btn_backup_restore.setEnabled(False)
        tm.start_task(
            task_id=task_id,
            title="Backup Restore",
            subtitle=folder,
            steps=["Validating Backup", "Connecting to Device", "Restoring Backup", "Finalizing"],
            worker_fn=run_job
        )
        QMessageBox.information(
            self, "Restore Queued",
            "Backup restore initiated.\nTrack progress in the bottom operation dock.")

    def _start_ipsw_restore(self):
        path = self.txt_ipsw_path.text().strip()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "Missing File", "Please select a valid .ipsw firmware file.")
            return

        erase = self.chk_erase.isChecked()
        mode_text = "ERASE & Clean Factory Restore" if erase else "Update / In-place Restore"

        reply = QMessageBox.question(
            self, "Confirm Firmware Restore",
            f"Are you sure you want to begin this restore?\n\nFile: {os.path.basename(path)}\nType: {mode_text}",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        def run_restore(progress_cb, log_cb, is_cancelled_cb):
            cmd = ["idevicerestore"]
            if erase:
                cmd.append("-e")
            cmd.append(path)

            progress_cb(5, step="Preparing Firmware", detail="Validating IPSW firmware...")
            log_cb(f"Executing: {' '.join(cmd)}")

            # Stream live so Cancel is honoured during the (potentially ~20 min)
            # flash instead of only after a single 1200s subprocess.run returns.
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                proc = subprocess.Popen(
                    cmd, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    creationflags=creationflags,
                )
            except OSError as e:
                raise Exception(f"Could not start idevicerestore: {e}")

            cancelled = False
            assert proc.stdout is not None
            for line in proc.stdout:
                if is_cancelled_cb and is_cancelled_cb():
                    cancelled = True
                    proc.terminate()
                    break
                for part in line.replace("\r", "\n").split("\n"):
                    part = part.rstrip()
                    if not part:
                        continue
                    log_cb(part)
                    lower = part.lower()
                    if "enter" in lower and "recovery" in lower:
                        progress_cb(-1, step="Entering Restore Mode", detail=part.strip())
                    elif "flash" in lower and "filesystem" in lower:
                        progress_cb(-1, step="Flashing Filesystem", detail=part.strip())
                    elif "kernel" in lower:
                        progress_cb(-1, step="Flashing Kernel", detail=part.strip())
                    elif "done" in lower or "complete" in lower or "finished" in lower:
                        progress_cb(100, step="Finalizing", detail=part.strip())
                    else:
                        progress_cb(-1, detail=part.strip())

            if cancelled:
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                raise Exception("Restore cancelled by user.")

            rc = proc.wait()
            if rc != 0:
                raise Exception(f"Restore failed (exit code {rc}).")

            progress_cb(100, step="Finalizing", detail="Restore completed successfully.")

        tm = TaskManager.instance()
        task_id = "restore_" + str(os.getpid())
        if tm.is_task_running(task_id):
            QMessageBox.information(
                self, "Busy", "A firmware restore is already running.")
            return
        self.btn_flash.setEnabled(False)
        tm.start_task(
            task_id=task_id,
            title="IPSW Firmware Restore",
            subtitle=os.path.basename(path),
            steps=["Preparing Firmware", "Entering Restore Mode", "Flashing Filesystem", "Flashing Kernel", "Finalizing"],
            worker_fn=run_restore
        )
        QMessageBox.information(self, "Restore Queued", "Firmware restore process initiated.\nTrack progress in the bottom operation dock.")

    # ── SSH Ramdisk tab ───────────────────────────────────────────

    def _ram_probe_wsl(self) -> None:
        try:
            ok = ram.wsl_available()
            detail = "ready" if ok else "not found — run: wsl --install"
        except Exception as e:
            ok, detail = False, f"check failed ({e})"
        self._ram_wsl_ready.emit(ok, detail)

    def _on_ram_wsl_ready(self, ok: bool, detail: str) -> None:
        self._ram_wsl_state = ok
        color = Colors.SUCCESS if ok else Colors.DANGER
        self.lbl_ram_wsl.setText(f"WSL (Ubuntu): {detail}")
        self.lbl_ram_wsl.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {color};")

    def _on_tab_changed(self, index: int) -> None:
        timer = getattr(self, "_dfu_timer", None)
        if timer is None:
            return
        if self.tabs.widget(index) is self._ram_tab and not self._ram_busy:
            timer.start()
        else:
            timer.stop()

    def _poll_dfu(self) -> None:
        if self._ram_busy or self._ram_probe_running:
            return
        exe = ram.win_tool("irecovery")
        if not os.path.isfile(exe):
            return
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.finished.connect(self._on_dfu_probe_finished)
        proc.errorOccurred.connect(self._on_dfu_probe_error)
        self._dfu_proc = proc
        self._ram_probe_running = True
        self._dfu_probe_timeout.start()
        proc.start(exe, ["-q"])

    def _clear_dfu_probe(self) -> None:
        proc = self._dfu_proc
        self._dfu_proc = None
        self._ram_probe_running = False
        self._dfu_probe_timeout.stop()
        if proc is not None:
            proc.deleteLater()

    def _on_dfu_probe_error(self, _error) -> None:
        # FailedToStart (and friends) emit errorOccurred but never `finished`;
        # clear the latch so the next poll tick can retry instead of freezing.
        self._clear_dfu_probe()

    def _on_dfu_probe_timeout(self) -> None:
        # A hung irecovery emits neither finished nor errorOccurred — kill it.
        proc = self._dfu_proc
        if proc is not None:
            proc.kill()
        self._clear_dfu_probe()

    def _on_dfu_probe_finished(self, exit_code: int, _exit_status) -> None:
        proc = self._dfu_proc
        if proc is None:
            return
        out = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
        self._clear_dfu_probe()
        dev = None
        if exit_code == 0 or "CPID" in out:
            dev = ram.parse_device_info(out)
        self._ram_dev = dev
        self._update_ram_dfu_label()
        product = (dev or {}).get("product", "")
        if product and product != self._ram_versions_product:
            self._ram_versions_product = product
            self._ram_refresh_versions()

    def _update_ram_dfu_label(self) -> None:
        dev = self._ram_dev
        if not dev:
            self.lbl_ram_dfu.setText(
                "DFU device: not detected — enter DFU mode to continue")
            color = Colors.TEXT_SECONDARY
        elif dev["cpid"] in ram.CHECKM8_CPIDS:
            self.lbl_ram_dfu.setText(
                f"DFU device: {dev.get('product') or '?'} "
                f"({dev.get('model') or '?'}) — CPID {dev['cpid']}, "
                "checkm8 capable")
            color = Colors.SUCCESS
        else:
            self.lbl_ram_dfu.setText(
                f"DFU device: {dev.get('product') or '?'} — CPID "
                f"{dev['cpid']} is not checkm8 (A7–A11 / T2); "
                "ramdisk operations unavailable")
            color = Colors.DANGER
        self.lbl_ram_dfu.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {color};")
        self._update_ram_version_warn()

    def _ram_refresh_versions(self) -> None:
        if self._ram_versions_loading:
            return
        product = (self._ram_dev or {}).get("product") or self._ram_versions_product
        if not product:
            self.cmb_ram_version.clear()
            self.cmb_ram_version.addItem(
                "Connect a DFU device to list versions", "")
            return
        self._ram_versions_loading = True
        self.cmb_ram_version.clear()
        self.cmb_ram_version.addItem(f"Looking up {product} on ipsw.me…", "")
        threading.Thread(
            target=self._ram_fetch_versions, args=(product,),
            daemon=True).start()

    def _ram_fetch_versions(self, product: str) -> None:
        try:
            firmwares = ram.fetch_firmware_versions(product)
        except Exception as e:
            firmwares = [{"version": f"__error__{e}", "signed": False}]
        self._ram_versions_ready.emit(product, firmwares)

    def _on_ram_versions_ready(self, product: str, firmwares: list) -> None:
        self._ram_versions_loading = False
        expected = (self._ram_dev or {}).get("product") or self._ram_versions_product
        if expected and product != expected:
            return
        self.cmb_ram_version.clear()
        if firmwares and str(firmwares[0]["version"]).startswith("__error__"):
            msg = str(firmwares[0]["version"])[len("__error__"):]
            self.cmb_ram_version.addItem("Lookup failed", "")
            self.lbl_ram_version_warn.setText(f"ipsw.me lookup failed: {msg}")
            self.lbl_ram_version_warn.show()
            return
        first_signed = None
        for fw in firmwares:
            ver = str(fw.get("version", ""))
            if not ver:
                continue
            label = ver if fw.get("signed") else f"{ver} (unsigned)"
            self.cmb_ram_version.addItem(label, ver)
            if fw.get("signed") and first_signed is None:
                first_signed = ver
        if self.cmb_ram_version.count() == 0:
            self.cmb_ram_version.addItem("No firmware versions returned", "")
        elif first_signed:
            idx = self.cmb_ram_version.findData(first_signed)
            if idx >= 0:
                self.cmb_ram_version.setCurrentIndex(idx)
        self._update_ram_version_warn()

    def _update_ram_version_warn(self, *_args) -> None:
        ver = self.cmb_ram_version.currentData() or ""
        dev = self._ram_dev
        if not ver or not dev:
            self.lbl_ram_version_warn.hide()
            return
        try:
            major, minor, _patch = ram.parse_version(str(ver))
        except Exception:
            self.lbl_ram_version_warn.hide()
            return
        dm = ram.darwin_major_for(dev["cpid"], major)
        blocked = ram.linux_build_blocked(dm, minor)
        if blocked:
            self.lbl_ram_version_warn.setText(f"⚠ {blocked}")
            self.lbl_ram_version_warn.show()
        else:
            self.lbl_ram_version_warn.hide()

    def _on_ram_task_started(self, info) -> None:
        if not info.task_id.startswith("ramdisk_"):
            return
        self._ram_busy = True
        self._dfu_timer.stop()
        for btn in self._ram_buttons:
            btn.setEnabled(False)

    def _on_ram_task_finished(self, info) -> None:
        if not info.task_id.startswith("ramdisk_"):
            return
        self._ram_busy = False
        for btn in self._ram_buttons:
            btn.setEnabled(True)
        if self.tabs.currentWidget() is self._ram_tab:
            self._dfu_timer.start()

    def _on_restore_task_finished(self, info) -> None:
        if info.task_id.startswith(("restore_", "backup_restore_")):
            self.btn_flash.setEnabled(True)
            self.btn_backup_restore.setEnabled(True)

    def _ram_usb_ok(self) -> bool:
        if self._ram_busy:
            QMessageBox.information(
                self, "Busy", "A ramdisk operation is already running.")
            return False
        dev = self._ram_dev
        if not dev:
            QMessageBox.warning(
                self, "No DFU Device",
                "No device was detected in DFU mode.\n\n"
                "Connect the device in DFU mode (see the DFU Mode Guide tab) "
                "and wait for the status line to turn green.")
            return False
        if dev["cpid"] not in ram.CHECKM8_CPIDS:
            QMessageBox.warning(
                self, "Unsupported Device",
                f"CPID {dev['cpid']} is not a checkm8 target (A7–A11 / T2), "
                "so it cannot build or boot an SSH ramdisk.")
            return False
        return True

    def _ram_wsl_ok(self) -> bool:
        if self._ram_wsl_state is False:
            QMessageBox.warning(
                self, "WSL Missing",
                "WSL (Ubuntu) is required for this operation.\n\n"
                "Install it with: wsl --install")
            return False
        return True

    def _ram_confirm(self, title: str, text: str) -> bool:
        if self._ram_busy:
            QMessageBox.information(
                self, "Busy", "A ramdisk operation is already running.")
            return False
        reply = QMessageBox.question(
            self, title, text, QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)
        return reply == QMessageBox.Yes

    def _ram_require_built(self) -> bool:
        if not os.path.isfile(os.path.join(ram.sshramdisk_dir(), "iBSS.img4")):
            QMessageBox.warning(
                self, "No Ramdisk", "Create an SSH ramdisk first.")
            return False
        return True

    def _start_ram_create(self) -> None:
        if not self._ram_usb_ok() or not self._ram_wsl_ok():
            return
        version = self.cmb_ram_version.currentData()
        if not version:
            QMessageBox.warning(
                self, "Pick a Version",
                "Select the iOS version to build the ramdisk from.")
            return
        dev = self._ram_dev or {}
        try:
            major, minor, _patch = ram.parse_version(str(version))
            dm = ram.darwin_major_for(dev.get("cpid", ""), major)
        except Exception:
            dm, minor = None, 0
        if dm is not None:
            blocked = ram.linux_build_blocked(dm, minor)
            if blocked:
                QMessageBox.warning(self, "Version Not Supported", blocked)
                return
        troll = (self.txt_trollstore_app.text().strip()
                 if self.chk_trollstore.isChecked() else "")

        if not self._ram_confirm(
            "Create SSH Ramdisk",
            f"Build a ramdisk for {dev.get('product', '?')} from iOS "
            f"{version}?\n\nThe device must stay connected in DFU mode. "
            "Firmware parts are downloaded on the first build "
            "(several hundred MB).",
        ):
            return

        def run_job(progress_cb, log_cb, is_cancelled_cb):
            ram.op_create(str(version), troll, progress_cb, log_cb,
                          is_cancelled_cb)

        tm = TaskManager.instance()
        tm.start_task(
            task_id=f"ramdisk_create_{os.getpid()}",
            title="Create SSH Ramdisk",
            subtitle=f"iOS {version} — {dev.get('product', '')}",
            steps=ram.CREATE_STEPS,
            worker_fn=run_job,
        )

    def _start_ram_boot(self) -> None:
        if not self._ram_usb_ok() or not self._ram_require_built():
            return
        if not self._ram_confirm(
            "Boot SSH Ramdisk",
            "Boot the built ramdisk on the connected DFU device?\n\n"
            "The device screen will show verbose boot text; it will not "
            "boot iOS.",
        ):
            return

        def run_job(progress_cb, log_cb, is_cancelled_cb):
            ram.op_boot(progress_cb, log_cb, is_cancelled_cb)

        tm = TaskManager.instance()
        tm.start_task(
            task_id=f"ramdisk_boot_{os.getpid()}",
            title="Boot SSH Ramdisk",
            subtitle=self._ram_dev.get("product", "") if self._ram_dev else "",
            steps=ram.BOOT_STEPS,
            worker_fn=run_job,
        )

    def _start_ram_erase(self) -> None:
        if not self._ram_usb_ok() or not self._ram_require_built():
            return
        if not self._ram_confirm(
            "Erase Device",
            "⚠ This schedules a FULL ERASE of the connected device "
            "(obliteration) on next boot.\n\nAll data and settings are "
            "destroyed. Continue?",
        ):
            return

        def run_job(progress_cb, log_cb, is_cancelled_cb):
            ram.op_reset(progress_cb, log_cb, is_cancelled_cb)

        tm = TaskManager.instance()
        tm.start_task(
            task_id=f"ramdisk_erase_{os.getpid()}",
            title="Erase Device (SSH Ramdisk)",
            subtitle=self._ram_dev.get("product", "") if self._ram_dev else "",
            steps=ram.RESET_STEPS,
            worker_fn=run_job,
        )

    def _start_ram_reboot(self) -> None:
        if not self._ram_confirm(
            "Reboot Ramdisk",
            "Reboot the booted ramdisk over SSH? (Requires the ramdisk to "
            "already be running.)",
        ):
            return

        def run_job(progress_cb, log_cb, is_cancelled_cb):
            ram.op_reboot(progress_cb, log_cb, is_cancelled_cb)

        tm = TaskManager.instance()
        tm.start_task(
            task_id=f"ramdisk_reboot_{os.getpid()}",
            title="Reboot Ramdisk",
            subtitle="ssh /sbin/reboot",
            steps=ram.REBOOT_STEPS,
            worker_fn=run_job,
        )

    def _start_ram_dump(self) -> None:
        output = self.txt_dump_path.text().strip() or ram.default_dump_path()
        if not self._ram_wsl_ok():
            return
        if not self._ram_confirm(
            "Dump SHSH Blobs",
            "Read the on-board blobs from the booted ramdisk via SSH and "
            f"convert them with img4tool?\n\nOutput: {output}",
        ):
            return

        def run_job(progress_cb, log_cb, is_cancelled_cb):
            ram.op_dump_blobs(output, progress_cb, log_cb, is_cancelled_cb)

        tm = TaskManager.instance()
        tm.start_task(
            task_id=f"ramdisk_dump_{os.getpid()}",
            title="Dump SHSH Blobs",
            subtitle=output,
            steps=ram.DUMP_STEPS,
            worker_fn=run_job,
        )

    def _start_ram_clean(self) -> None:
        if not self._ram_confirm(
            "Clean Workspace",
            "Delete the built SSH ramdisk and all scratch files?",
        ):
            return

        def run_job(progress_cb, log_cb, is_cancelled_cb):
            ram.op_clean(progress_cb, log_cb, is_cancelled_cb)

        tm = TaskManager.instance()
        tm.start_task(
            task_id=f"ramdisk_clean_{os.getpid()}",
            title="Clean Ramdisk Workspace",
            subtitle=ram.run_root(),
            steps=ram.CLEAN_STEPS,
            worker_fn=run_job,
        )

    def _start_ram_console(self) -> None:
        if not self._ram_confirm(
            "Open SSH Console",
            "Start iproxy and open an SSH console as root@localhost:2222? "
            "(Requires a booted ramdisk.)",
        ):
            return

        def run_job(progress_cb, log_cb, is_cancelled_cb):
            progress_cb(20, step="Open Console", detail="Starting iproxy...")
            ram.open_ssh_console(log_cb)
            progress_cb(100, step="Open Console", detail="Console launched.")

        tm = TaskManager.instance()
        tm.start_task(
            task_id=f"ramdisk_console_{os.getpid()}",
            title="SSH Console",
            subtitle="root@localhost:2222",
            steps=["Open Console"],
            worker_fn=run_job,
        )
