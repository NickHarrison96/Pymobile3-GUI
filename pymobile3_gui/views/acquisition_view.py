"""
Pymobile3-GUI - Forensic Acquisition Workspace
Full-page acquisition suite supporting Logical, Logical+, and PRFS workflows
with live progress orchestration via the Persistent Operation Dock.
"""

import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QGridLayout, QCheckBox, QFileDialog,
    QScrollArea, QMessageBox, QRadioButton, QButtonGroup
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from pymobile3_gui.ui.theme import Colors
from pymobile3_gui.core.task_manager import TaskManager
from pymobile3_gui.core.backend.paths import backups_dir
from pymobile3_gui.core.backend.backup_engine import AcquisitionWorker, ACQUISITION_MODES, DEFAULT_OPTIONS


class ModeSelectCard(QFrame):
    clicked = Signal()

    def __init__(self, mode_id: str, label: str, summary: str, desc: str, parent=None):
        super().__init__(parent)
        self.mode_id = mode_id
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self._is_selected = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(6)

        top = QHBoxLayout()
        self.lbl_label = QLabel(label, self)
        self.lbl_label.setStyleSheet("font-size: 14px; font-weight: 750; color: #f6f7fb;")
        top.addWidget(self.lbl_label)
        top.addStretch()

        self.radio = QRadioButton(self)
        self.radio.setAttribute(Qt.WA_TransparentForMouseEvents)
        top.addWidget(self.radio)
        layout.addLayout(top)

        lbl_sum = QLabel(summary, self)
        lbl_sum.setStyleSheet("font-size: 11px; font-weight: 600; color: #60a5fa;")
        layout.addWidget(lbl_sum)

        lbl_desc = QLabel(desc, self)
        lbl_desc.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_MUTED};")
        lbl_desc.setWordWrap(True)
        layout.addWidget(lbl_desc)

        self.set_selected(False)

    def set_selected(self, selected: bool):
        self._is_selected = selected
        self.radio.setChecked(selected)
        if selected:
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: #17243a;
                    border: 1px solid #3b82f6;
                    border-radius: 12px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {Colors.BG_CARD};
                    border: 1px solid {Colors.BORDER_DEFAULT};
                    border-radius: 12px;
                }}
                QFrame:hover {{
                    background-color: {Colors.BG_CARD_HOVER};
                    border-color: {Colors.BORDER_HOVER};
                }}
            """)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class AcquisitionView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_mode = "logical_plus"
        self.worker = None

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")

        content = QWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(22)

        # ── Header ───────────────────────────────────────────────────
        header_vbox = QVBoxLayout()
        header_vbox.setSpacing(2)
        lbl_eyebrow = QLabel("FORENSIC EXTRACTION & EVIDENCE ARCHIVING", self)
        lbl_eyebrow.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {Colors.TEXT_MUTED}; letter-spacing: 1px;")
        header_vbox.addWidget(lbl_eyebrow)

        lbl_title = QLabel("Device Acquisition", self)
        lbl_title.setStyleSheet("font-size: 24px; font-weight: 750; color: #ffffff; letter-spacing: -0.5px;")
        header_vbox.addWidget(lbl_title)
        layout.addLayout(header_vbox)

        # ── 1. Acquisition Mode Selector ──────────────────────────────
        lbl_modes = QLabel("SELECT ACQUISITION PROFILE", self)
        lbl_modes.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {Colors.TEXT_MUTED}; letter-spacing: 1px;")
        layout.addWidget(lbl_modes)

        self.cards_layout = QHBoxLayout()
        self.cards_layout.setSpacing(14)
        self.mode_cards = {}

        for mode_key, meta in ACQUISITION_MODES.items():
            if mode_key == "ffs":
                continue  # Jailbreak SSH only
            card = ModeSelectCard(mode_key, meta["label"], meta["summary"], meta["detail"], self)
            card.clicked.connect(lambda k=mode_key: self._select_mode(k))
            self.mode_cards[mode_key] = card
            self.cards_layout.addWidget(card)

        layout.addLayout(self.cards_layout)
        self._select_mode("logical_plus")

        # ── 2. Destination & Case Metadata ────────────────────────────
        lbl_meta = QLabel("DESTINATION & CASE METADATA", self)
        lbl_meta.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {Colors.TEXT_MUTED}; letter-spacing: 1px;")
        layout.addWidget(lbl_meta)

        meta_frame = QFrame(self)
        meta_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 12px;
                padding: 16px;
            }}
        """)
        meta_layout = QGridLayout(meta_frame)
        meta_layout.setContentsMargins(14, 14, 14, 14)
        meta_layout.setSpacing(12)

        # Output Folder
        meta_layout.addWidget(QLabel("Output Directory:"), 0, 0)
        self.txt_out_dir = QLineEdit(backups_dir(), self)
        meta_layout.addWidget(self.txt_out_dir, 0, 1)
        btn_browse = QPushButton("Browse...", self)
        btn_browse.clicked.connect(self._browse_dir)
        meta_layout.addWidget(btn_browse, 0, 2)

        # Case ID
        meta_layout.addWidget(QLabel("Case / Tag ID:"), 1, 0)
        self.txt_case = QLineEdit(self)
        self.txt_case.setPlaceholderText("Optional e.g. CASE-2026-09A")
        meta_layout.addWidget(self.txt_case, 1, 1, 1, 2)

        # Examiner Name
        meta_layout.addWidget(QLabel("Examiner Name:"), 2, 0)
        self.txt_examiner = QLineEdit(self)
        self.txt_examiner.setPlaceholderText("Optional examiner identification")
        meta_layout.addWidget(self.txt_examiner, 2, 1, 1, 2)

        layout.addWidget(meta_frame)

        # ── 3. Artifact Options ───────────────────────────────────────
        lbl_opts = QLabel("ARTIFACT INCLUSIONS", self)
        lbl_opts.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {Colors.TEXT_MUTED}; letter-spacing: 1px;")
        layout.addWidget(lbl_opts)

        opts_box = QHBoxLayout()
        opts_box.setSpacing(20)

        self.chk_media = QCheckBox("Camera Media (DCIM)", self)
        self.chk_media.setChecked(True)
        self.chk_crash = QCheckBox("Crash Reports (/DiagnosticLogs)", self)
        self.chk_crash.setChecked(True)
        self.chk_apps = QCheckBox("Installed App Inventory", self)
        self.chk_apps.setChecked(True)

        opts_box.addWidget(self.chk_media)
        opts_box.addWidget(self.chk_crash)
        opts_box.addWidget(self.chk_apps)
        opts_box.addStretch()
        layout.addLayout(opts_box)

        layout.addSpacing(10)

        # ── 4. Start Button ───────────────────────────────────────────
        btn_box = QHBoxLayout()
        self.btn_start = QPushButton("🚀 Start Forensic Acquisition", self)
        self.btn_start.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_start.setStyleSheet(f"""
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
            QPushButton:disabled {{
                background-color: #1e293b;
                color: {Colors.TEXT_MUTED};
                border-color: {Colors.BORDER_SUBTLE};
            }}
        """)
        self.btn_start.clicked.connect(self._start_acquisition)
        btn_box.addWidget(self.btn_start)
        btn_box.addStretch()
        layout.addLayout(btn_box)

        layout.addStretch()
        scroll.setWidget(content)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _select_mode(self, mode: str):
        self.selected_mode = mode
        for k, card in self.mode_cards.items():
            card.set_selected(k == mode)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory", self.txt_out_dir.text())
        if d:
            self.txt_out_dir.setText(d)

    def _start_acquisition(self):
        out_dir = self.txt_out_dir.text().strip()
        if not out_dir or not os.path.exists(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(self, "Invalid Path", f"Could not create output directory: {e}")
                return

        opts = {
            "incl_media": self.chk_media.isChecked(),
            "incl_crash": self.chk_crash.isChecked(),
            "incl_apps": self.chk_apps.isChecked(),
            "keep_intermediate": False,
        }

        # Step list for the task manager
        if self.selected_mode == "logical":
            steps = ["Device Verification", "MobileBackup2 Creation", "Validation"]
        elif self.selected_mode == "prfs":
            steps = ["Device Verification", "File System Traversal", "Media & Crash Dump", "Archive Packaging"]
        else:  # logical_plus
            steps = ["Device Verification", "MobileBackup2 Creation", "Camera Media Dump", "Crash Reports", "TAR Packaging"]

        mode_name = ACQUISITION_MODES[self.selected_mode]["label"]

        # Run via TaskManager worker function
        def run_job(progress_cb, log_cb, is_cancelled_cb):
            self.worker = AcquisitionWorker(
                mode=self.selected_mode,
                output_dir=out_dir,
                options=opts
            )

            # Bridge AcquisitionWorker signals to TaskManager callbacks
            def on_progress(p):
                progress_cb(p)

            def on_status(s):
                progress_cb(-1, step=s)

            def on_output(line):
                log_cb(line)

            self.worker.progress.connect(on_progress)
            self.worker.status.connect(on_status)
            self.worker.output.connect(on_output)

            self.worker.start()
            while self.worker.isRunning():
                if is_cancelled_cb():
                    self.worker.cancel()
                    break
                self.worker.wait(100)

            if is_cancelled_cb():
                raise Exception("Acquisition cancelled by user.")

        tm = TaskManager.instance()
        tm.start_task(
            task_id="acquisition_" + str(os.getpid()),
            title=f"{mode_name} Acquisition",
            subtitle=f"Writing to {out_dir}",
            steps=steps,
            worker_fn=run_job
        )

        QMessageBox.information(
            self, "Acquisition Started",
            f"{mode_name} acquisition launched.\nProgress is live in the bottom operation dock."
        )
