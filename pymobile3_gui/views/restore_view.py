"""
Pymobile3-GUI - Recovery & IPSW Restore Workspace
Full-page firmware flashing engine (idevicerestore) paired with interactive
Recovery Mode and DFU Mode hardware wizards.
"""

import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QCheckBox, QFileDialog, QTabWidget,
    QScrollArea, QMessageBox, QTextBrowser
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor
from pymobile3_gui.ui.theme import Colors
from pymobile3_gui.core.task_manager import TaskManager
from pymobile3_gui.core.backend.resource_manager import safe_run_command


class RestoreView(QWidget):
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

        btn_flash = QPushButton("⚡ Begin IPSW Firmware Restore", self)
        btn_flash.setCursor(QCursor(Qt.PointingHandCursor))
        btn_flash.setStyleSheet(f"""
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
        """)
        btn_flash.clicked.connect(self._start_ipsw_restore)
        ipsw_layout.addWidget(btn_flash)
        ipsw_layout.addStretch()

        self.tabs.addTab(ipsw_tab, "⚡ IPSW Restore")

        # ── Tab 2: Recovery Mode Guide ───────────────────────────────
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

        # ── Tab 3: DFU Mode Guide ────────────────────────────────────
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

            progress_cb(10, step="Initializing Restore", detail="Starting idevicerestore...")
            log_cb(f"Executing: {' '.join(cmd)}")

            ok, out = safe_run_command(cmd, timeout=1200)
            log_cb(out)
            if not ok:
                raise Exception(f"Restore failed:\n{out}")

        tm = TaskManager.instance()
        tm.start_task(
            task_id="restore_" + str(os.getpid()),
            title="IPSW Firmware Restore",
            subtitle=os.path.basename(path),
            steps=["Preparing Firmware", "Entering Restore Mode", "Flashing Filesystem", "Flashing Kernel", "Finalizing"],
            worker_fn=run_restore
        )
        QMessageBox.information(self, "Restore Queued", "Firmware restore process initiated.\nTrack progress in the bottom operation dock.")
