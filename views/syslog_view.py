"""
Pymobile3-GUI - Live Syslog Workspace
High-performance streaming log console with live search, regex filtering,
buffer limits, pause/resume, and export capabilities.
"""

import sys
import shutil
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QPlainTextEdit, QFileDialog, QMessageBox, QFrame
)
from PySide6.QtCore import Qt, QProcess
from PySide6.QtGui import QFont, QCursor
from pymobile3_gui.ui.theme import Colors


class SyslogView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.is_paused = False
        self.all_logs = []
        self._startup_failed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(14)

        # ── Header ───────────────────────────────────────────────────
        header_vbox = QVBoxLayout()
        header_vbox.setSpacing(2)
        lbl_eyebrow = QLabel("REAL-TIME DIAGNOSTIC TELEMETRY", self)
        lbl_eyebrow.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {Colors.TEXT_MUTED}; letter-spacing: 1px;")
        header_vbox.addWidget(lbl_eyebrow)

        lbl_title = QLabel("Live Syslog Stream", self)
        lbl_title.setStyleSheet("font-size: 24px; font-weight: 750; color: #ffffff; letter-spacing: -0.5px;")
        header_vbox.addWidget(lbl_title)
        layout.addLayout(header_vbox)

        # ── Controls & Filter Bar ────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        self.btn_stream_toggle = QPushButton("▶ Start Stream", self)
        self.btn_stream_toggle.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_stream_toggle.setProperty("class", "primary")
        self.btn_stream_toggle.clicked.connect(self._toggle_stream)
        toolbar.addWidget(self.btn_stream_toggle)

        self.filter_input = QLineEdit(self)
        self.filter_input.setPlaceholderText("Filter syslog lines (text or subsystem tag)...")
        self.filter_input.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.filter_input, stretch=1)

        self.btn_pause = QPushButton("⏸ Pause", self)
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_pause.setEnabled(False)
        toolbar.addWidget(self.btn_pause)

        self.btn_clear = QPushButton("🗑 Clear", self)
        self.btn_clear.clicked.connect(self._clear_logs)
        toolbar.addWidget(self.btn_clear)

        self.btn_export = QPushButton("💾 Export", self)
        self.btn_export.clicked.connect(self._export_logs)
        toolbar.addWidget(self.btn_export)

        layout.addLayout(toolbar)

        # ── Terminal Output ──────────────────────────────────────────
        self.console = QPlainTextEdit(self)
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(10000)
        self.console.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {Colors.BG_TERMINAL};
                color: #86efac;
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 12px;
                font-family: 'Consolas', 'Cascadia Code', monospace;
                font-size: 11px;
                padding: 12px;
            }}
        """)
        layout.addWidget(self.console, stretch=1)

        # ── Status Bar ───────────────────────────────────────────────
        status_box = QHBoxLayout()
        self.lbl_status = QLabel("Stream standby. Connect device and click Start Stream.", self)
        self.lbl_status.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_MUTED};")
        status_box.addWidget(self.lbl_status)
        status_box.addStretch()

        self.lbl_count = QLabel("0 lines logged", self)
        self.lbl_count.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_MUTED};")
        status_box.addWidget(self.lbl_count)
        layout.addLayout(status_box)

    def _toggle_stream(self):
        if self.process and self.process.state() == QProcess.Running:
            self._stop_stream()
        else:
            self._start_stream()

    def _start_stream(self):
        # Check if pymobiledevice3 is available
        if not shutil.which("pymobiledevice3") and not self._find_pymobiledevice3_module():
            self._show_error("pymobiledevice3 not found. Install with: pip install pymobiledevice3")
            return

        self._startup_failed = False
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._on_ready_read)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_error)
        self.process.started.connect(self._on_started)

        # Launch pymobiledevice3 syslog live
        cmd = [sys.executable, "-m", "pymobiledevice3", "syslog", "live"]
        self.process.start(cmd[0], cmd[1:])

        if not self.process.waitForStarted(5000):
            self._show_error("Failed to start syslog process. Is a device connected and trusted?")
            self.process = None
            return

        self.btn_stream_toggle.setText("■ Stop Stream")
        self.btn_stream_toggle.setProperty("class", "danger")
        self.btn_stream_toggle.style().unpolish(self.btn_stream_toggle)
        self.btn_stream_toggle.style().polish(self.btn_stream_toggle)
        self.btn_pause.setEnabled(True)
        self.lbl_status.setText("Live syslog connection active...")

    def _find_pymobiledevice3_module(self) -> bool:
        """Check if pymobiledevice3 is importable as a module."""
        try:
            __import__("pymobiledevice3")
            return True
        except ImportError:
            return False

    def _stop_stream(self):
        if self.process:
            self.process.kill()
            self.process.waitForFinished(1000)
            self.process = None

        self.btn_stream_toggle.setText("▶ Start Stream")
        self.btn_stream_toggle.setProperty("class", "primary")
        self.btn_stream_toggle.style().unpolish(self.btn_stream_toggle)
        self.btn_stream_toggle.style().polish(self.btn_stream_toggle)
        self.btn_pause.setEnabled(False)
        if not self._startup_failed:
            self.lbl_status.setText("Stream stopped.")

    def _on_started(self):
        self._startup_failed = False
        self.console.appendPlainText("[syslog] Connected — streaming live...")

    def _on_ready_read(self):
        if not self.process:
            return
        data = self.process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        lines = data.splitlines()
        filter_text = self.filter_input.text().strip().lower()

        for line in lines:
            self.all_logs.append(line)
            if not self.is_paused:
                if not filter_text or filter_text in line.lower():
                    self.console.appendPlainText(line)

        self.lbl_count.setText(f"{len(self.all_logs)} lines logged")

    def _toggle_pause(self):
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.btn_pause.setText("▶ Resume")
            self.lbl_status.setText("Log rendering paused (buffer still recording)")
        else:
            self.btn_pause.setText("⏸ Pause")
            self._apply_filter()

    def _apply_filter(self):
        filter_text = self.filter_input.text().strip().lower()
        self.console.clear()
        matching = [l for l in self.all_logs if not filter_text or filter_text in l.lower()]
        # Display last 3000 matching lines to keep UI fluid
        self.console.setPlainText("\n".join(matching[-3000:]))

    def _clear_logs(self):
        self.all_logs.clear()
        self.console.clear()
        self.lbl_count.setText("0 lines logged")

    def _export_logs(self):
        if not self.all_logs:
            QMessageBox.information(self, "Empty Log", "No logs recorded to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Syslog", "ios_syslog.log", "Log Files (*.log *.txt)")
        if path:
            try:
                with open(path, "w", encoding="utf-8", errors="replace") as f:
                    f.write("\n".join(self.all_logs))
                QMessageBox.information(self, "Export Complete", f"Saved {len(self.all_logs)} lines to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", str(e))

    def _on_finished(self, code, status):
        if self._startup_failed:
            return
        if self.process:
            # Read any remaining output
            data = self.process.readAllStandardOutput().data().decode("utf-8", errors="replace")
            if data.strip():
                for line in data.splitlines():
                    self.all_logs.append(line)
                    if not self.is_paused:
                        self.console.appendPlainText(line)
        self._stop_stream()
        if code != 0:
            self._show_error(f"Syslog process exited with code {code}. Device may have disconnected.")

    def _on_error(self, err):
        self._startup_failed = True
        err_msg = {
            QProcess.ProcessError.FailedToStart: "Failed to start — is Python or pymobiledevice3 available?",
            QProcess.ProcessError.Crashed: "The process crashed.",
            QProcess.ProcessError.Timedout: "The process timed out.",
            QProcess.ProcessError.WriteError: "Write error.",
            QProcess.ProcessError.ReadError: "Read error.",
        }.get(err, f"Unknown process error: {err}")
        self._show_error(err_msg)

    def _show_error(self, msg: str):
        self.console.appendPlainText(f"[ERROR] {msg}")
        self.lbl_status.setText(f"Error: {msg}")
        self.btn_stream_toggle.setText("▶ Start Stream")
        self.btn_stream_toggle.setProperty("class", "primary")
        self.btn_stream_toggle.style().unpolish(self.btn_stream_toggle)
        self.btn_stream_toggle.style().polish(self.btn_stream_toggle)
        self.btn_pause.setEnabled(False)
