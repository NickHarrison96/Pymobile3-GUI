"""
Pymobile3-GUI - Developer Tools & DVT Instruments Workspace
Unified developer workspace with progressive readiness flow (Dev Mode -> DDI -> RSD Tunnel)
and interactive DVT instruments (Process Manager, Live Screenshot, GPS Simulator).
"""

import os
import sys
import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QTabWidget, QScrollArea, QMessageBox, QDoubleSpinBox, QComboBox,
    QFileDialog, QProgressBar
)
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCursor, QPixmap
from pymobile3_gui.ui.theme import Colors
from pymobile3_gui.core.backend.tunnel_manager import (
    run_developer_command, get_tunnel_manager, is_admin
)
from pymobile3_gui.core.backend.resource_manager import safe_run_command


# iOS 17+ auto-mount fetches a personalized DDI from Apple before mounting.
# Generous ceiling so a slow download is not misreported as a mount failure.
DDI_MOUNT_TIMEOUT = 900

# How often to re-check Developer Mode on the device.
DEV_MODE_POLL_MS = 15000

LOCATION_PRESETS = [
    ("San Francisco", 37.774929, -122.419416),
    ("New York",      40.712776,  -74.005974),
    ("London",        51.507351,   -0.127758),
    ("Tokyo",         35.689487,  139.691711),
    ("Paris",         48.856614,    2.352222),
]


class DvtProcessWorker(QThread):
    """Background worker for DVT process list query."""
    procs_loaded = Signal(list)
    error_signal = Signal(str)

    def run(self):
        ok, out = run_developer_command(["developer", "dvt", "proclist"], timeout=30)
        if not ok:
            self.error_signal.emit(f"Failed to fetch processes:\n{out}")
            return
        try:
            data = json.loads(out)
            procs = []
            if isinstance(data, list):
                for item in data:
                    procs.append({
                        "pid": item.get("pid", 0),
                        "name": item.get("name", "Unknown"),
                        "realName": item.get("realAppName", ""),
                        "isApp": "Yes" if item.get("isApplication") else "No",
                        "startDate": item.get("startDate", "")
                    })
            procs.sort(key=lambda x: x["pid"])
            self.procs_loaded.emit(procs)
        except Exception as e:
            self.error_signal.emit(f"Error parsing process list: {e}")


class ScreenshotWorker(QThread):
    """Background worker for DVT screenshot capture."""
    screenshot_captured = Signal(str)
    error_signal = Signal(str)

    def run(self):
        shot_path = os.path.join(os.path.expanduser("~"), "temp_pymobile_shot.png")
        ok, out = run_developer_command(["developer", "dvt", "screenshot", shot_path], timeout=30)
        if ok and os.path.exists(shot_path):
            self.screenshot_captured.emit(shot_path)
        else:
            self.error_signal.emit(f"Could not capture screen:\n{out}")


class GpsWorker(QThread):
    """Background worker for GPS simulation."""
    finished_ok = Signal(str)
    error_signal = Signal(str)

    def __init__(self, lat: float, lon: float, clear: bool = False):
        super().__init__()
        self.lat = lat
        self.lon = lon
        self.clear = clear

    def run(self):
        if self.clear:
            ok, out = run_developer_command(["developer", "dvt", "simulate-location", "clear"], timeout=15)
            if ok:
                self.finished_ok.emit("Hardware location simulation stopped.")
            else:
                self.error_signal.emit(out)
        else:
            ok, out = run_developer_command(
                ["developer", "dvt", "simulate-location", "set", "--", str(self.lat), str(self.lon)],
                timeout=15
            )
            if ok:
                self.finished_ok.emit(f"Simulated GPS set to:\n{self.lat}, {self.lon}")
            else:
                self.error_signal.emit(out)


class TunnelWorker(QThread):
    """Background worker for tunnel start/stop (blocking operations)."""
    finished = Signal(bool, str)

    def __init__(self, start: bool = True):
        super().__init__()
        self.start_tunnel = start

    def run(self):
        tm = get_tunnel_manager()
        if self.start_tunnel:
            ok, msg = tm.start()
        else:
            ok, msg = tm.stop()
        self.finished.emit(ok, msg)


class DeveloperView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc_worker = None
        self.screenshot_worker = None
        self.gps_worker = None
        self.tunnel_worker = None

        # Developer Mode polling. The timer is created here but only runs while
        # this page is the visible workspace — see showEvent/hideEvent. Each tick
        # spawns a pymobiledevice3 subprocess, so polling a page nobody is
        # looking at is pure cost.
        self._dev_mode_timer = QTimer(self)
        self._dev_mode_timer.setInterval(DEV_MODE_POLL_MS)
        self._dev_mode_timer.timeout.connect(self._check_dev_mode_status)

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
        lbl_eyebrow = QLabel("DEVELOPER SERVICES & DVT INSTRUMENTATION", self)
        lbl_eyebrow.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {Colors.TEXT_MUTED}; letter-spacing: 1px;")
        header_vbox.addWidget(lbl_eyebrow)

        lbl_title = QLabel("Developer Tools", self)
        lbl_title.setStyleSheet("font-size: 24px; font-weight: 750; color: #ffffff; letter-spacing: -0.5px;")
        header_vbox.addWidget(lbl_title)
        layout.addLayout(header_vbox)

        # ── 1. Progressive Readiness Flow ─────────────────────────────
        lbl_flow = QLabel("DEVELOPER READINESS PIPELINE", self)
        lbl_flow.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {Colors.TEXT_MUTED}; letter-spacing: 1px;")
        layout.addWidget(lbl_flow)

        readiness_frame = QFrame(self)
        readiness_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 14px;
                padding: 16px;
            }}
        """)
        readiness_layout = QHBoxLayout(readiness_frame)
        readiness_layout.setContentsMargins(14, 12, 14, 12)
        readiness_layout.setSpacing(16)

        # Step 1: Dev Mode
        box_step1 = QVBoxLayout()
        lbl_s1_t = QLabel("1. Developer Mode", self)
        lbl_s1_t.setStyleSheet("font-size: 12px; font-weight: 700; color: #fff;")
        lbl_s1_d = QLabel("Enable AMFI developer mode on device", self)
        lbl_s1_d.setStyleSheet(f"font-size: 10px; color: {Colors.TEXT_SECONDARY};")
        self.lbl_dev_mode_status = QLabel("Status: Checking...", self)
        self.lbl_dev_mode_status.setStyleSheet(f"font-size: 10px; color: {Colors.TEXT_MUTED};")
        btn_s1 = QPushButton("Enable Dev Mode", self)
        btn_s1.clicked.connect(self._enable_dev_mode)
        box_step1.addWidget(lbl_s1_t)
        box_step1.addWidget(lbl_s1_d)
        box_step1.addWidget(self.lbl_dev_mode_status)
        box_step1.addWidget(btn_s1)
        readiness_layout.addLayout(box_step1)

        # Step 2: DDI Mount
        box_step2 = QVBoxLayout()
        lbl_s2_t = QLabel("2. DDI Image", self)
        lbl_s2_t.setStyleSheet("font-size: 12px; font-weight: 700; color: #fff;")
        lbl_s2_d = QLabel("Mount Developer Disk Image", self)
        lbl_s2_d.setStyleSheet(f"font-size: 10px; color: {Colors.TEXT_SECONDARY};")
        btn_s2 = QPushButton("Auto-Mount DDI", self)
        btn_s2.clicked.connect(self._mount_ddi)
        box_step2.addWidget(lbl_s2_t)
        box_step2.addWidget(lbl_s2_d)
        box_step2.addWidget(btn_s2)
        readiness_layout.addLayout(box_step2)

        # Step 3: Tunneld (RSD)
        box_step3 = QVBoxLayout()
        lbl_s3_t = QLabel("3. RSD Tunnel", self)
        lbl_s3_t.setStyleSheet("font-size: 12px; font-weight: 700; color: #fff;")
        lbl_s3_d = QLabel("Start RemoteXPC tunnel (iOS 17+)", self)
        lbl_s3_d.setStyleSheet(f"font-size: 10px; color: {Colors.TEXT_SECONDARY};")
        self.btn_tunnel = QPushButton("Start Tunnel", self)
        self.btn_tunnel.clicked.connect(self._toggle_tunnel)
        box_step3.addWidget(lbl_s3_t)
        box_step3.addWidget(lbl_s3_d)
        box_step3.addWidget(self.btn_tunnel)
        readiness_layout.addLayout(box_step3)

        layout.addWidget(readiness_frame)

        # ── 2. Progress Bar for Operations ────────────────────────────
        self.op_progress = QProgressBar(self)
        self.op_progress.setRange(0, 0)  # Indeterminate
        self.op_progress.setFixedHeight(6)
        self.op_progress.setVisible(False)
        self.op_progress.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                background-color: {Colors.BG_SURFACE};
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 {Colors.ACCENT_PRIMARY}, stop:1 {Colors.ACCENT_PRIMARY_HOVER});
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self.op_progress)

        # ── 3. Instruments Tabs ───────────────────────────────────────
        self.tabs = QTabWidget(self)
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {Colors.BORDER_DEFAULT};
                background: {Colors.BG_SURFACE};
                border-radius: 12px;
                padding: 12px;
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
            QTabBar::tab:hover {{
                color: {Colors.TEXT_PRIMARY};
            }}
        """)

        # ── Tab A: Process Monitor ───────────────────────────────────
        proc_widget = QWidget()
        proc_layout = QVBoxLayout(proc_widget)
        proc_layout.setContentsMargins(8, 8, 8, 8)
        proc_layout.setSpacing(10)

        proc_top = QHBoxLayout()
        self.lbl_proc_status = QLabel("Requires mounted DDI (and RSD tunnel on iOS 17+).", self)
        self.lbl_proc_status.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_SECONDARY};")
        proc_top.addWidget(self.lbl_proc_status, stretch=1)

        btn_refresh_procs = QPushButton("⟳ Query Processes", self)
        btn_refresh_procs.clicked.connect(self._fetch_processes)
        proc_top.addWidget(btn_refresh_procs)
        proc_layout.addLayout(proc_top)

        self.proc_table = QTableWidget(0, 4, self)
        self.proc_table.setHorizontalHeaderLabels(["PID", "Process Name", "Application Name", "App?"])
        self.proc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        proc_layout.addWidget(self.proc_table)
        self.tabs.addTab(proc_widget, "⚡ Process Monitor")

        # ── Tab B: Screenshot Capture ─────────────────────────────────
        shot_widget = QWidget()
        shot_layout = QVBoxLayout(shot_widget)
        shot_layout.setContentsMargins(14, 14, 14, 14)
        shot_layout.setSpacing(12)

        shot_top = QHBoxLayout()
        self.btn_take_shot = QPushButton("📸 Capture Screen", self)
        self.btn_take_shot.clicked.connect(self._take_screenshot)
        shot_top.addWidget(self.btn_take_shot)
        shot_top.addStretch()
        shot_layout.addLayout(shot_top)

        self.lbl_shot_preview = QLabel("No screenshot captured yet.", self)
        self.lbl_shot_preview.setAlignment(Qt.AlignCenter)
        self.lbl_shot_preview.setStyleSheet(f"""
            background-color: {Colors.BG_CARD};
            border: 1px dashed {Colors.BORDER_MUTED};
            border-radius: 10px;
            color: {Colors.TEXT_SECONDARY};
            min-height: 280px;
        """)
        shot_layout.addWidget(self.lbl_shot_preview)
        self.tabs.addTab(shot_widget, "📷 Screen Capture")

        # ── Tab C: GPS Simulator ──────────────────────────────────────
        gps_widget = QWidget()
        gps_layout = QVBoxLayout(gps_widget)
        gps_layout.setContentsMargins(14, 14, 14, 14)
        gps_layout.setSpacing(12)

        lbl_gps_d = QLabel("Override device location hardware readings with custom coordinates.", self)
        lbl_gps_d.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_SECONDARY};")
        gps_layout.addWidget(lbl_gps_d)

        form_box = QGridLayout()
        form_box.addWidget(QLabel("Preset:"), 0, 0)
        self.cmb_presets = QComboBox(self)
        for label, lat, lon in LOCATION_PRESETS:
            self.cmb_presets.addItem(label, (lat, lon))
        self.cmb_presets.currentIndexChanged.connect(self._on_preset_changed)
        form_box.addWidget(self.cmb_presets, 0, 1)

        form_box.addWidget(QLabel("Latitude:"), 1, 0)
        self.spin_lat = QDoubleSpinBox(self)
        self.spin_lat.setRange(-90.0, 90.0)
        self.spin_lat.setDecimals(6)
        self.spin_lat.setValue(37.774929)
        form_box.addWidget(self.spin_lat, 1, 1)

        form_box.addWidget(QLabel("Longitude:"), 2, 0)
        self.spin_lon = QDoubleSpinBox(self)
        self.spin_lon.setRange(-180.0, 180.0)
        self.spin_lon.setDecimals(6)
        self.spin_lon.setValue(-122.419416)
        form_box.addWidget(self.spin_lon, 2, 1)
        gps_layout.addLayout(form_box)

        gps_btns = QHBoxLayout()
        self.btn_apply_gps = QPushButton("📍 Set Simulated Location", self)
        self.btn_apply_gps.clicked.connect(self._set_location)
        btn_clear_gps = QPushButton("✕ Stop Simulation", self)
        btn_clear_gps.clicked.connect(self._clear_location)
        gps_btns.addWidget(self.btn_apply_gps)
        gps_btns.addWidget(btn_clear_gps)
        gps_btns.addStretch()
        gps_layout.addLayout(gps_btns)
        gps_layout.addStretch()

        self.tabs.addTab(gps_widget, "📍 GPS Location Simulation")
        layout.addWidget(self.tabs)

        layout.addStretch()
        scroll.setWidget(content)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _show_busy(self, msg: str = "Working..."):
        self.op_progress.setVisible(True)
        self.lbl_proc_status.setText(msg)

    def _hide_busy(self):
        self.op_progress.setVisible(False)

    def _enable_dev_mode(self):
        self._show_busy("Enabling developer mode...")
        def run():
            ok, out = safe_run_command(
                [sys.executable, "-m", "pymobiledevice3", "amfi", "enable-developer-mode"],
                timeout=30
            )
            return ok, out
        self._run_async(run, self._on_dev_mode_done)

    def _on_dev_mode_done(self, result):
        ok, out = result
        self._hide_busy()
        if ok:
            QMessageBox.information(self, "Developer Mode",
                "Command sent. Device may prompt to reboot and confirm in Settings > Privacy & Security.")
        else:
            QMessageBox.critical(self, "Error", f"Failed: {out}")

    def _mount_ddi(self):
        # On iOS 17+ auto-mount downloads a personalized DDI from Apple before it
        # mounts anything, which routinely takes minutes on a slow link. The old
        # 60s ceiling killed the download and reported it as a mount failure.
        self._show_busy("Mounting Developer Disk Image (may download, please wait)...")
        def run():
            ok, out = safe_run_command(
                [sys.executable, "-m", "pymobiledevice3", "mounter", "auto-mount"],
                timeout=DDI_MOUNT_TIMEOUT
            )
            return ok, out
        self._run_async(run, self._on_ddi_done)

    def _on_ddi_done(self, result):
        ok, out = result
        if ok:
            # Verify mount by checking if DDI is actually mounted
            self._show_busy("Verifying DDI mount...")
            def verify():
                ok2, out2 = safe_run_command(
                    [sys.executable, "-m", "pymobiledevice3", "mounter", "list"],
                    timeout=30
                )
                return ok2, out2
            self._run_async(verify, self._on_ddi_verified)
        else:
            self._hide_busy()
            QMessageBox.critical(self, "Mount Failed", f"Error mounting DDI: {out}")

    @staticmethod
    def _parse_mounted_images(out: str) -> list | None:
        """
        `mounter list` prints a JSON array of mounted image signatures — an empty
        array when nothing is mounted. Returns None when the output isn't JSON.
        """
        try:
            parsed = json.loads(out)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, list) else None

    def _on_ddi_verified(self, result):
        ok, out = result
        self._hide_busy()
        images = self._parse_mounted_images(out) if ok else None
        if images:
            QMessageBox.information(
                self, "DDI Mounted",
                f"Developer Disk Image mounted and verified "
                f"({len(images)} image{'s' if len(images) != 1 else ''} mounted)."
            )
        else:
            QMessageBox.warning(self, "Mount Uncertain", f"Mount command succeeded but verification unclear:\n{out}")

    def _toggle_tunnel(self):
        tm = get_tunnel_manager()
        if tm.is_running():
            self._show_busy("Stopping RSD tunnel...")
            self.tunnel_worker = TunnelWorker(start=False)
            self.tunnel_worker.finished.connect(self._on_tunnel_stopped)
            self.tunnel_worker.start()
        else:
            self._show_busy("Starting RSD tunnel (may prompt for elevation)...")
            self.tunnel_worker = TunnelWorker(start=True)
            self.tunnel_worker.finished.connect(self._on_tunnel_started)
            self.tunnel_worker.start()

    def _on_tunnel_started(self, ok, msg):
        self._hide_busy()
        if ok:
            self.btn_tunnel.setText("Stop Tunnel")
            QMessageBox.information(self, "Tunnel", "RSD Tunnel active.")
        else:
            QMessageBox.critical(self, "Tunnel Error", msg)

    def _on_tunnel_stopped(self, ok, msg):
        self._hide_busy()
        self.btn_tunnel.setText("Start Tunnel")
        if ok:
            QMessageBox.information(self, "Tunnel", "RSD Tunnel stopped.")
        else:
            QMessageBox.warning(self, "Tunnel", msg)

    def _fetch_processes(self):
        self._show_busy("Querying processes via DVT...")
        self.proc_table.setRowCount(0)
        self.proc_worker = DvtProcessWorker()
        self.proc_worker.procs_loaded.connect(self._on_procs_loaded)
        self.proc_worker.error_signal.connect(self._on_procs_error)
        self.proc_worker.start()

    def _on_procs_loaded(self, procs: list):
        self._hide_busy()
        self.proc_table.setRowCount(len(procs))
        for row, p in enumerate(procs):
            self.proc_table.setItem(row, 0, QTableWidgetItem(str(p.get("pid", ""))))
            self.proc_table.setItem(row, 1, QTableWidgetItem(str(p.get("name", ""))))
            self.proc_table.setItem(row, 2, QTableWidgetItem(str(p.get("realName", ""))))
            self.proc_table.setItem(row, 3, QTableWidgetItem(str(p.get("isApp", ""))))
        self.lbl_proc_status.setText(f"Loaded {len(procs)} active processes.")

    def _on_procs_error(self, err: str):
        self._hide_busy()
        self.lbl_proc_status.setText(f"Error: {err}")

    def _take_screenshot(self):
        self._show_busy("Capturing screenshot...")
        self.btn_take_shot.setEnabled(False)
        self.screenshot_worker = ScreenshotWorker()
        self.screenshot_worker.screenshot_captured.connect(self._on_screenshot)
        self.screenshot_worker.error_signal.connect(self._on_screenshot_error)
        self.screenshot_worker.start()

    def _on_screenshot(self, path: str):
        self._hide_busy()
        self.btn_take_shot.setEnabled(True)
        pix = QPixmap(path)
        if not pix.isNull():
            scaled = pix.scaledToHeight(380, Qt.SmoothTransformation)
            self.lbl_shot_preview.setPixmap(scaled)
            try:
                os.remove(path)
            except:
                pass
        else:
            self.lbl_shot_preview.setText("Failed to load screenshot image.")

    def _on_screenshot_error(self, err: str):
        self._hide_busy()
        self.btn_take_shot.setEnabled(True)
        QMessageBox.critical(self, "Screenshot Failed", err)

    def _on_preset_changed(self, index: int):
        data = self.cmb_presets.currentData()
        if data:
            lat, lon = data
            self.spin_lat.setValue(lat)
            self.spin_lon.setValue(lon)

    def _set_location(self):
        lat = self.spin_lat.value()
        lon = self.spin_lon.value()
        self._show_busy(f"Setting simulated location to {lat}, {lon}...")
        self.btn_apply_gps.setEnabled(False)
        self.gps_worker = GpsWorker(lat, lon, clear=False)
        self.gps_worker.finished_ok.connect(self._on_gps_ok)
        self.gps_worker.error_signal.connect(self._on_gps_error)
        self.gps_worker.start()

    def _clear_location(self):
        self._show_busy("Clearing location simulation...")
        self.gps_worker = GpsWorker(0, 0, clear=True)
        self.gps_worker.finished_ok.connect(self._on_gps_ok)
        self.gps_worker.error_signal.connect(self._on_gps_error)
        self.gps_worker.start()

    def _on_gps_ok(self, msg: str):
        self._hide_busy()
        self.btn_apply_gps.setEnabled(True)
        QMessageBox.information(self, "Location", msg)

    def _on_gps_error(self, err: str):
        self._hide_busy()
        self.btn_apply_gps.setEnabled(True)
        QMessageBox.critical(self, "Error", err)

    def _run_async(self, target_fn, callback):
        """Run a blocking function in a thread and call back with result on the main thread."""
        class AsyncWorker(QThread):
            result = Signal(object)
            def __init__(self, fn):
                super().__init__()
                self.fn = fn
            def run(self):
                try:
                    res = self.fn()
                except Exception as e:
                    res = (False, str(e))
                self.result.emit(res)

        worker = AsyncWorker(target_fn)
        worker.result.connect(callback)
        # Hold a reference so the QThread is not collected mid-run, and drop it
        # again on completion. Without the discard this list grew for the life of
        # the window — one dead entry per poll tick.
        if not hasattr(self, '_async_workers'):
            self._async_workers = []
        self._async_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._retire_async_worker(w))
        worker.start()

    def _retire_async_worker(self, worker):
        try:
            self._async_workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()

    # -------------------------------------------------------------------------
    # Developer Mode polling
    # -------------------------------------------------------------------------

    def showEvent(self, event):
        """Poll only while this workspace is on screen."""
        super().showEvent(event)
        self._check_dev_mode_status()
        self._dev_mode_timer.start()

    def hideEvent(self, event):
        # closeEvent never fires for a page inside a QStackedWidget, so this is
        # the hook that actually stops the polling when the user navigates away.
        self._dev_mode_timer.stop()
        super().hideEvent(event)

    def _check_dev_mode_status(self):
        """Check Developer Mode status on device and update UI."""
        def check():
            return safe_run_command(
                [sys.executable, "-m", "pymobiledevice3", "amfi", "developer-mode-status"],
                timeout=15
            )

        def on_result(result):
            ok, out = result
            # `amfi developer-mode-status` prints a bare JSON boolean. Match it
            # exactly rather than looking for a "1" substring, which any digit in
            # an error string would satisfy.
            if ok and out.strip().lower() == "true":
                self.lbl_dev_mode_status.setText("Status: Enabled")
                self.lbl_dev_mode_status.setStyleSheet(
                    f"font-size: 10px; color: {Colors.SUCCESS};")
            elif ok and out.strip().lower() == "false":
                self.lbl_dev_mode_status.setText(
                    "Status: Disabled (Settings > Privacy & Security)")
                self.lbl_dev_mode_status.setStyleSheet(
                    f"font-size: 10px; color: {Colors.DANGER};")
            else:
                self.lbl_dev_mode_status.setText("Status: Unknown (no device?)")
                self.lbl_dev_mode_status.setStyleSheet(
                    f"font-size: 10px; color: {Colors.TEXT_MUTED};")

        self._run_async(check, on_result)