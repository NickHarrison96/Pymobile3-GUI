"""
Pymobile3-GUI - Developer Tools & DVT Instruments Workspace
Unified developer workspace with progressive readiness flow (Dev Mode -> DDI -> RSD Tunnel)
and interactive DVT instruments (Process Manager, Live Screenshot, GPS Simulator).
"""

import os
import re
import sys
import json
import subprocess
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QTabWidget, QScrollArea, QMessageBox, QDoubleSpinBox, QComboBox,
    QFileDialog, QProgressBar, QMenu, QLineEdit, QPlainTextEdit,
    QApplication
)
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCursor, QPixmap
from pymobile3_gui.ui.theme import Colors
from pymobile3_gui.core.backend.tunnel_manager import (
    run_developer_command, get_tunnel_manager, is_admin
)
from pymobile3_gui.core.backend.resource_manager import safe_run_command
from pymobile3_gui.core.backend.paths import pmd3_cmd


# iOS 17+ auto-mount fetches a personalized DDI from Apple before mounting.
# Generous ceiling so a slow download is not misreported as a mount failure.
DDI_MOUNT_TIMEOUT = 900

# `amfi enable-developer-mode` reboots the device, waits for it to reappear over
# usbmux, then answers the post-restart confirmation prompt. Killing it mid-cycle
# (a short timeout) leaves Developer Mode off despite the reboot.
DEV_MODE_ENABLE_TIMEOUT = 240

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
        if not out.strip():
            # rc=0 with no stdout is how a swallowed pymobiledevice3 failure
            # looks here (stderr was not captured for this JSON command).
            self.error_signal.emit(
                "No process data returned.\n\nCheck that the DDI is mounted "
                "and the RSD tunnel is running, then retry.")
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


class DvtActionWorker(QThread):
    """
    One-shot developer command (launch, kill, sysmon, arbitration).

    Runs with stderr captured and treats an ERROR line as failure —
    pymobiledevice3 logs failures to stderr while exiting 0.
    """
    finished = Signal(bool, str)

    def __init__(self, args: list[str], timeout: int = 30):
        super().__init__()
        self.args = args
        self.timeout = timeout

    @staticmethod
    def _strip_ansi(text: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", text or "")

    def run(self):
        ok, out = run_developer_command(
            self.args, timeout=self.timeout, include_stderr=True)
        out = self._strip_ansi(out)
        error_lines = [ln.strip() for ln in out.splitlines()
                       if re.search(r"\bERROR\b", ln)]
        if ok and error_lines:
            # Log lines are timestamp/host-prefixed; the message follows ERROR.
            detail = "\n".join(ln.split("ERROR", 1)[-1].strip(" \t:|")
                               for ln in error_lines)
            self.finished.emit(False, detail)
            return
        self.finished.emit(ok, out)


class MountLookupWorker(QThread):
    """Second-opinion mount check: LookupImage answers what CopyDevices cannot."""
    finished = Signal(bool, str)

    @staticmethod
    def _strip_ansi(text: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", text or "")

    def run(self):
        ok, out = safe_run_command(
            pmd3_cmd(["mounter", "lookup", "Personalized"]),
            timeout=30,
            include_stderr=True
        )
        out = self._strip_ansi(out)
        if not ok:
            self.finished.emit(False, out)
        elif "is not mounted" in out.lower():
            self.finished.emit(False, out)
        elif out.strip():
            self.finished.emit(True, out)
        else:
            self.finished.emit(False, "LookupImage returned no data.")


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
        self._action_workers: list[DvtActionWorker] = []
        self._power_proc = None  # detached arbitration check-in; holds the assertion
        self._all_procs: list[dict] = []  # last full proclist, for search filtering
        self._bundle_index: dict[str, str] | None = None  # name -> bundle id cache
        self._bundle_partial: dict[str, str] = {}
        self._bundle_source_idx = 0
        self._bundle_loading = False
        self._pending_bundle_lookup: tuple | None = None

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

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("Search:", self))
        self.input_proc_filter = QLineEdit(self)
        self.input_proc_filter.setPlaceholderText(
            "Filter by process name, app name, or PID…")
        self.input_proc_filter.setClearButtonEnabled(True)
        self.input_proc_filter.textChanged.connect(self._apply_proc_filter)
        filter_row.addWidget(self.input_proc_filter, stretch=1)
        proc_layout.addLayout(filter_row)

        self.proc_table = QTableWidget(0, 4, self)
        self.proc_table.setHorizontalHeaderLabels(["PID", "Process Name", "Application Name", "App?"])
        self.proc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.proc_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.proc_table.customContextMenuRequested.connect(self._on_proc_context_menu)
        proc_layout.addWidget(self.proc_table)

        launch_row = QHBoxLayout()
        launch_row.setSpacing(8)
        launch_row.addWidget(QLabel("Bundle ID:", self))
        self.input_bundle = QLineEdit(self)
        self.input_bundle.setPlaceholderText("e.g. com.apple.mobilesafari")
        self.input_bundle.returnPressed.connect(self._launch_app)
        self.input_bundle.setContextMenuPolicy(Qt.CustomContextMenu)
        self.input_bundle.customContextMenuRequested.connect(self._on_bundle_context_menu)
        launch_row.addWidget(self.input_bundle, stretch=1)
        btn_launch = QPushButton("🚀 Launch App", self)
        btn_launch.clicked.connect(self._launch_app)
        launch_row.addWidget(btn_launch)
        proc_layout.addLayout(launch_row)

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

        # ── Tab D: System Monitor ────────────────────────────────────
        sysmon_widget = QWidget()
        sysmon_layout = QVBoxLayout(sysmon_widget)
        sysmon_layout.setContentsMargins(8, 8, 8, 8)
        sysmon_layout.setSpacing(10)

        sysmon_top = QHBoxLayout()
        self.lbl_sysmon_status = QLabel("Snapshot of device-wide stats via DVT sysmon.", self)
        self.lbl_sysmon_status.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_SECONDARY};")
        sysmon_top.addWidget(self.lbl_sysmon_status, stretch=1)
        btn_sysmon = QPushButton("⟳ Refresh System Stats", self)
        btn_sysmon.clicked.connect(self._fetch_sysmon)
        sysmon_top.addWidget(btn_sysmon)
        sysmon_layout.addLayout(sysmon_top)

        self.sysmon_view = QPlainTextEdit(self)
        self.sysmon_view.setReadOnly(True)
        self.sysmon_view.setPlaceholderText("System statistics appear here…")
        self.sysmon_view.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {Colors.BG_TERMINAL};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 8px;
                padding: 8px;
                font-family: 'JetBrains Mono', 'Consolas', monospace;
                font-size: 11px;
                color: {Colors.SUCCESS};
            }}
        """)
        sysmon_layout.addWidget(self.sysmon_view)
        self.tabs.addTab(sysmon_widget, "📈 System Monitor")

        # ── Tab E: Power Assertion ───────────────────────────────────
        power_widget = QWidget()
        power_layout = QVBoxLayout(power_widget)
        power_layout.setContentsMargins(14, 14, 14, 14)
        power_layout.setSpacing(12)

        lbl_power_d = QLabel(
            "Checks in as the device owner via developer arbitration, marking it "
            "'in-use'. The assertion holds only while the check-in process runs, "
            "which keeps the device awake during long operations.", self)
        lbl_power_d.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_SECONDARY};")
        lbl_power_d.setWordWrap(True)
        power_layout.addWidget(lbl_power_d)

        owner_row = QHBoxLayout()
        owner_row.addWidget(QLabel("Owner name:", self))
        self.input_power_owner = QLineEdit("Pymobile3-GUI", self)
        self.input_power_owner.setToolTip("Identifier reported to the device as the current owner.")
        owner_row.addWidget(self.input_power_owner, stretch=1)
        power_layout.addLayout(owner_row)

        power_btns = QHBoxLayout()
        self.btn_power_hold = QPushButton("⚡ Hold Assertion (Check-In)", self)
        self.btn_power_hold.clicked.connect(self._start_power_assertion)
        self.btn_power_release = QPushButton("⏹ Release (Check-Out)", self)
        self.btn_power_release.clicked.connect(self._stop_power_assertion)
        self.btn_power_release.setEnabled(False)
        power_btns.addWidget(self.btn_power_hold)
        power_btns.addWidget(self.btn_power_release)
        power_btns.addStretch()
        power_layout.addLayout(power_btns)

        self.lbl_power_status = QLabel("No assertion held.", self)
        self.lbl_power_status.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_MUTED};")
        self.lbl_power_status.setWordWrap(True)
        power_layout.addWidget(self.lbl_power_status)
        power_layout.addStretch()
        self.tabs.addTab(power_widget, "🔋 Power Assertion")

        layout.addWidget(self.tabs)

        layout.addStretch()
        scroll.setWidget(content)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _show_busy(self, msg: str = "Working...", label: QLabel | None = None):
        self.op_progress.setVisible(True)
        (label or self.lbl_proc_status).setText(msg)

    def _hide_busy(self):
        self.op_progress.setVisible(False)

    def _enable_dev_mode(self):
        self._show_busy("Enabling developer mode — the device reboots; "
                        "keep it connected (can take a few minutes)...")
        def run():
            ok, out = safe_run_command(
                pmd3_cmd(["amfi", "enable-developer-mode"]),
                timeout=DEV_MODE_ENABLE_TIMEOUT,
                include_stderr=True
            )
            out = self._strip_ansi(out)
            if "passcode" in out.lower():
                # Programmatic enable is refused while a passcode is set. Make
                # sure the manual toggle is visible in Settings either way.
                safe_run_command(
                    pmd3_cmd(["amfi", "reveal-developer-mode"]),
                    timeout=30,
                    include_stderr=True
                )
            return ok, out
        self._run_async(run, self._on_dev_mode_done)

    def _on_dev_mode_done(self, result):
        ok, out = result
        self._hide_busy()
        # pymobiledevice3 logs failures to stderr and still exits 0 — check text,
        # not the exit status.
        error_line = next((ln for ln in out.splitlines() if re.search(r"\bERROR\b", ln)), "")
        if ok and not error_line:
            self._check_dev_mode_status()
            QMessageBox.information(self, "Developer Mode",
                "Enable completed — the device restarted and the confirmation was "
                "answered automatically. Status updates below.")
            return
        detail = error_line.split("ERROR", 1)[-1].strip(" \t:|") if error_line else out
        if "passcode" in detail.lower():
            QMessageBox.warning(self, "Developer Mode",
                "Developer Mode can't be enabled from here while the device has a passcode set.\n\n"
                "Enable it manually instead:\n"
                "1. On the device open Settings > Privacy & Security > Developer Mode\n"
                "   (at the bottom of the list).\n"
                "2. Turn it on, then reboot when prompted.\n"
                "3. Confirm after the restart.\n\n"
                "The option has been revealed in Settings if it wasn't visible before.")
        elif detail.lower().startswith("command timed out"):
            QMessageBox.warning(self, "Developer Mode",
                "The enable cycle did not finish in time — if the device rebooted, "
                "the post-restart confirmation may have been missed.\n\n"
                "After the device is back, check the status below. If it still says "
                "Disabled, tap the Developer Mode confirmation alert on the device "
                "(or press Enable again).")
        else:
            QMessageBox.critical(self, "Developer Mode", detail)

    @staticmethod
    def _strip_ansi(text: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", text or "")

    def _mount_ddi(self):
        # On iOS 17+ auto-mount downloads a personalized DDI from Apple before it
        # mounts anything, which routinely takes minutes on a slow link. The old
        # 60s ceiling killed the download and reported it as a mount failure.
        # stderr must be captured: pymobiledevice3 reports mount failures there
        # while still exiting 0, so exit status alone always looks successful.
        self._show_busy("Mounting Developer Disk Image (may download, please wait)...")
        def run():
            ok, out = safe_run_command(
                pmd3_cmd(["mounter", "auto-mount"]),
                timeout=DDI_MOUNT_TIMEOUT,
                include_stderr=True
            )
            return ok, self._strip_ansi(out)
        self._run_async(run, self._on_ddi_done)

    def _on_ddi_done(self, result):
        ok, out = result
        self._last_mount_output = out
        if not ok:
            self._hide_busy()
            QMessageBox.critical(self, "Mount Failed", f"Error mounting DDI: {out}")
            return
        # Log lines carry a timestamp/host prefix, so match ERROR anywhere in the line.
        error_line = next((ln for ln in out.splitlines() if re.search(r"\bERROR\b", ln)), "")
        if error_line:
            self._hide_busy()
            detail = error_line.split("ERROR", 1)[-1].strip(" \t:|")
            if "developer mode is disabled" in detail.lower():
                detail += ("\n\nUse the 'Enable Developer Mode' button in this tab, "
                           "reboot the device, then mount again.")
            QMessageBox.critical(self, "Mount Failed", detail)
            return
        # Verify mount by checking if DDI is actually mounted
        self._show_busy("Verifying DDI mount...")
        def verify():
            ok2, out2 = safe_run_command(
                pmd3_cmd(["mounter", "list"]),
                timeout=30
            )
            return ok2, out2
        self._run_async(verify, self._on_ddi_verified)

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
        elif images == []:
            # Valid JSON, empty list: CopyDevices shows nothing. Ask LookupImage
            # before deciding — it answers "mounted?" directly.
            self._show_busy("Confirming mount via LookupImage...")
            self.lookup_worker = MountLookupWorker()
            self.lookup_worker.finished.connect(self._on_mount_lookup)
            self.lookup_worker.start()
        else:
            QMessageBox.warning(
                self, "Mount Uncertain",
                f"Mount command succeeded but verification output was not understood:\n{out}"
            )

    def _on_mount_lookup(self, mounted: bool, detail: str):
        self._hide_busy()
        if mounted:
            QMessageBox.information(
                self, "DDI Mounted",
                "Developer Disk Image is mounted (confirmed via LookupImage)."
            )
            return
        base = ("The device reports no mounted developer image."
                if "not mounted" in detail.lower()
                else "Could not confirm the mount.")
        output = getattr(self, "_last_mount_output", "").strip()
        QMessageBox.warning(
            self, "Mount Uncertain",
            f"{base}\n\n{detail}".strip()
            + (f"\n\nauto-mount output:\n{output}" if output else "")
        )

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
        self._all_procs = procs
        if self.input_proc_filter.text().strip():
            # A filter is active — apply it to the fresh data instead of
            # flooding the table with rows the user asked to hide.
            self._apply_proc_filter(self.input_proc_filter.text())
            return
        self._populate_proc_table(procs)
        self.lbl_proc_status.setText(f"Loaded {len(procs)} active processes.")

    def _populate_proc_table(self, procs: list):
        self.proc_table.setRowCount(len(procs))
        for row, p in enumerate(procs):
            self.proc_table.setItem(row, 0, QTableWidgetItem(str(p.get("pid", ""))))
            self.proc_table.setItem(row, 1, QTableWidgetItem(str(p.get("name", ""))))
            self.proc_table.setItem(row, 2, QTableWidgetItem(str(p.get("realName", ""))))
            self.proc_table.setItem(row, 3, QTableWidgetItem(str(p.get("isApp", ""))))

    def _apply_proc_filter(self, text: str):
        """Case-insensitive substring match across every displayed column."""
        needle = text.strip().lower()
        if not needle:
            self._populate_proc_table(self._all_procs)
            if self._all_procs:
                self.lbl_proc_status.setText(
                    f"Loaded {len(self._all_procs)} active processes.")
            return
        matches = [
            p for p in self._all_procs
            if needle in str(p.get("pid", "")).lower()
            or needle in str(p.get("name", "")).lower()
            or needle in str(p.get("realName", "")).lower()
            or needle in str(p.get("isApp", "")).lower()
        ]
        self._populate_proc_table(matches)
        self.lbl_proc_status.setText(
            f"Showing {len(matches)} of {len(self._all_procs)} processes.")

    def _on_bundle_context_menu(self, pos):
        text = self.input_bundle.text().strip()
        menu = QMenu(self)
        act_copy = menu.addAction("Copy Bundle ID")
        act_copy.setEnabled(bool(text))
        act_paste = menu.addAction("Paste")
        act_select = menu.addAction("Select All")
        act_clear = menu.addAction("Clear")
        act_clear.setEnabled(bool(self.input_bundle.text()))
        chosen = menu.exec(self.input_bundle.mapToGlobal(pos))
        if chosen is act_copy:
            QApplication.clipboard().setText(text)
            self.lbl_proc_status.setText(f"Copied {text}")
        elif chosen is act_paste:
            self.input_bundle.paste()
        elif chosen is act_select:
            self.input_bundle.selectAll()
        elif chosen is act_clear:
            self.input_bundle.clear()

    def _on_procs_error(self, err: str):
        self._hide_busy()
        self.lbl_proc_status.setText(f"Error: {err}")

    # ------------------------------------------------------------------
    # Process control (context menu kill, app launcher)
    # ------------------------------------------------------------------

    def _on_proc_context_menu(self, pos):
        row = self.proc_table.rowAt(pos.y())
        pid_item = self.proc_table.item(row, 0) if row >= 0 else None
        if pid_item is None:
            return
        pid = pid_item.text()
        name_item = self.proc_table.item(row, 1)
        name = name_item.text() if name_item else pid
        real_item = self.proc_table.item(row, 2)
        real_name = real_item.text() if real_item else ""

        menu = QMenu(self)
        act_kill = menu.addAction(f"⛔ Kill {name} (PID {pid})")
        menu.addSeparator()
        act_bundle = menu.addAction("📋 Copy Bundle ID")
        act_set = menu.addAction("▶ Use as Launch Target")
        menu.addSeparator()
        act_copy = menu.addAction("Copy PID")
        chosen = menu.exec(self.proc_table.viewport().mapToGlobal(pos))
        if chosen is act_bundle:
            self._resolve_bundle_id(name, real_name, set_field=False)
        elif chosen is act_set:
            self._resolve_bundle_id(name, real_name, set_field=True)
        elif chosen is act_copy:
            QApplication.clipboard().setText(pid)
            self.lbl_proc_status.setText(f"PID {pid} copied to clipboard.")
        elif chosen is act_kill:
            reply = QMessageBox.question(
                self, "Kill Process",
                f"Terminate {name} (PID {pid}) on the device?",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            self._run_action(
                ["developer", "dvt", "kill", pid],
                lambda ok, out, p=pid, n=name: self._on_kill_done(ok, out, p, n),
                timeout=20,
                busy_msg=f"Killing PID {pid}...")

    # ------------------------------------------------------------------
    # Bundle id resolution (proclist has no bundle ids; applist does)
    # ------------------------------------------------------------------

    # Neither source alone is complete: core-device list-apps has system
    # apps (Calculator, Safari) but misses some third-party ones, while
    # dvt applist has plugins/user apps but no stock system apps.
    BUNDLE_SOURCES = (
        (["developer", "core-device", "list-apps"], "_merge_core_device_apps"),
        (["developer", "dvt", "applist"], "_merge_dvt_applist"),
    )

    def _resolve_bundle_id(self, name: str, real_name: str, set_field: bool):
        if self._bundle_index is not None:
            self._deliver_bundle_id(name, real_name, set_field)
            return
        # Latest request wins while sources load.
        self._pending_bundle_lookup = (name, real_name, set_field)
        if not self._bundle_loading:
            self._bundle_loading = True
            self._bundle_partial = {}
            self._bundle_source_idx = 0
            self._fetch_next_bundle_source()

    def _fetch_next_bundle_source(self):
        if self._bundle_source_idx >= len(self.BUNDLE_SOURCES):
            self._finish_bundle_sources()
            return
        cmd, _ = self.BUNDLE_SOURCES[self._bundle_source_idx]
        self._run_action(
            cmd,
            self._on_bundle_source_loaded,
            timeout=60,
            busy_msg="Loading installed apps to resolve bundle id...")

    def _on_bundle_source_loaded(self, ok: bool, out: str):
        self._hide_busy()
        _, merger = self.BUNDLE_SOURCES[self._bundle_source_idx]
        self._bundle_source_idx += 1
        if ok:
            try:
                data = json.loads(out)
            except (ValueError, TypeError):
                data = None
            if isinstance(data, list):
                getattr(self, merger)(data)
        # A failed source is skipped silently — the other one may still
        # answer; total failure is handled in _finish_bundle_sources.
        self._fetch_next_bundle_source()

    def _finish_bundle_sources(self):
        self._bundle_loading = False
        pending, self._pending_bundle_lookup = self._pending_bundle_lookup, None
        if not self._bundle_partial:
            self._toast(False, "Could not load the app list from the device.")
            return
        self._bundle_index = self._bundle_partial
        if pending:
            self._deliver_bundle_id(*pending)

    def _merge_core_device_apps(self, data: list):
        for item in data:
            bundle_id = str(item.get("bundleIdentifier") or "")
            if not bundle_id:
                continue
            keys = (item.get("name"), bundle_id.rsplit(".", 1)[-1])
            for key in keys:
                if key:
                    self._bundle_partial.setdefault(str(key).lower(), bundle_id)

    def _merge_dvt_applist(self, data: list):
        # Two passes so main .app entries register first and plugin .appex
        # entries (same DisplayName, different bundle id) only fill gaps.
        for want_apps in (True, False):
            for item in data:
                bundle_id = str(item.get("CFBundleIdentifier") or "")
                path = str(item.get("BundlePath") or "")
                if not bundle_id or (path.endswith(".app") != want_apps):
                    continue
                for key in (item.get("ExecutableName"), item.get("DisplayName")):
                    if key:
                        self._bundle_partial.setdefault(str(key).lower(), bundle_id)

    def _deliver_bundle_id(self, name: str, real_name: str, set_field: bool):
        index = self._bundle_index or {}
        bundle_id = (index.get((name or "").lower())
                     or index.get((real_name or "").lower()))
        if not bundle_id:
            self._toast(False, f"No bundle id found for '{name}'.")
            return
        if set_field:
            self.input_bundle.setText(bundle_id)
            self.input_bundle.setFocus()
            self.input_bundle.selectAll()
            self.lbl_proc_status.setText(f"Launch target set: {bundle_id}")
            return
        QApplication.clipboard().setText(bundle_id)
        self._toast(True, f"Copied {bundle_id}")

    def _on_kill_done(self, ok: bool, out: str, pid: str, name: str):
        self._hide_busy()
        if ok:
            self._toast(True, f"Terminated {name} (PID {pid}).")
            self._fetch_processes()
        else:
            QMessageBox.critical(self, "Kill Failed", out)

    def _launch_app(self):
        bundle = self.input_bundle.text().strip()
        if not bundle:
            QMessageBox.warning(self, "Bundle ID Required",
                                "Enter an app bundle identifier, e.g. com.apple.mobilesafari.")
            return
        self._run_action(
            ["developer", "dvt", "launch", bundle],
            self._on_launch_done,
            timeout=30,
            busy_msg=f"Launching {bundle}...")

    def _on_launch_done(self, ok: bool, out: str):
        self._hide_busy()
        if ok:
            self._toast(True, out.strip() or "Process launched.")
        else:
            QMessageBox.critical(self, "Launch Failed", out)

    def _run_action(self, args: list[str], on_done, timeout: int = 30,
                    busy_msg: str = "Working...", label: QLabel | None = None):
        """Run a one-shot DVT command on a worker; retire it when done."""
        self._show_busy(busy_msg, label=label)
        worker = DvtActionWorker(args, timeout=timeout)
        worker.finished.connect(on_done)
        worker.finished.connect(
            lambda _ok, _out, w=worker: self._retire_action_worker(w))
        self._action_workers.append(worker)
        worker.start()

    def _retire_action_worker(self, worker):
        try:
            self._action_workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()

    def _toast(self, ok: bool, body: str):
        window = self.window()
        toast = getattr(window, "toast", None)
        if toast is None:
            (QMessageBox.information if ok else QMessageBox.critical)(
                self, "Success!" if ok else "Failed", body)
            return
        toast.show_message(
            title="Success!" if ok else "Failed",
            body=body,
            level="info" if ok else "error",
            timeout_ms=5000,
        )

    # ------------------------------------------------------------------
    # System monitor
    # ------------------------------------------------------------------

    def _fetch_sysmon(self):
        self._run_action(
            ["developer", "dvt", "sysmon", "system"],
            self._on_sysmon_done,
            timeout=40,
            busy_msg="Sampling system stats...",
            label=self.lbl_sysmon_status)

    def _on_sysmon_done(self, ok: bool, out: str):
        self._hide_busy()
        if not ok:
            self.lbl_sysmon_status.setText("Failed to sample.")
            self.sysmon_view.setPlainText(out)
            return
        items: list[tuple[str, object]] = []
        try:
            data = json.loads(out)
            if isinstance(data, dict):
                items = [(str(k), v) for k, v in data.items()]
        except (ValueError, TypeError):
            pass
        if not items:
            # `sysmon system` prints plain `key: value` lines, not JSON.
            for line in out.splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip()
                    if key:
                        items.append((key, value.strip()))
        if not items:
            self.lbl_sysmon_status.setText("Sampled (raw output).")
            self.sysmon_view.setPlainText(out)
            return
        items.sort(key=lambda kv: kv[0])
        width = max(len(key) for key, _ in items)
        self.sysmon_view.setPlainText(
            "\n".join(f"{key:<{width}}  {value}" for key, value in items))
        self.lbl_sysmon_status.setText(f"{len(items)} metric(s) sampled.")

    # ------------------------------------------------------------------
    # Power assertion (developer arbitration check-in)
    # ------------------------------------------------------------------

    def _start_power_assertion(self):
        tm = get_tunnel_manager()
        if not tm.is_running():
            QMessageBox.warning(self, "Tunnel Required",
                                "Power assertion is a developer service and needs "
                                "an active RSD tunnel.")
            return
        env = tm.tunnel_env()
        if not env:
            QMessageBox.warning(self, "No Device",
                                "The tunnel has no device yet — unlock the phone, "
                                "then retry.")
            return
        hostname = self.input_power_owner.text().strip() or "Pymobile3-GUI"
        cmd = pmd3_cmd(["developer", "arbitration", "check-in", hostname, "--force"])
        run_env = {**os.environ, **env, "PYTHONUNBUFFERED": "1"}

        def run():
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            try:
                proc = subprocess.Popen(
                    cmd,
                    # check-in ends in input(); an open pipe keeps the process —
                    # and with it the assertion — alive. Close the pipe and the
                    # device is released automatically.
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=run_env,
                    creationflags=creationflags,
                )
            except Exception as e:
                return False, str(e)
            try:
                proc.wait(timeout=2.5)
            except subprocess.TimeoutExpired:
                return True, proc  # still running — assertion held
            err = (proc.stderr.read() if proc.stderr else "").strip()
            try:
                proc.kill()
            except Exception:
                pass
            return False, err or "Arbitration check-in exited immediately."

        def on_result(result):
            ok, payload = result
            self._hide_busy()
            if ok:
                self._power_proc = payload
                self.lbl_power_status.setText(
                    f"Assertion held as '{hostname}' — device marked in-use.")
                self.lbl_power_status.setStyleSheet(
                    f"font-size: 11px; color: {Colors.SUCCESS};")
                self.btn_power_hold.setEnabled(False)
                self.btn_power_release.setEnabled(True)
            else:
                self.lbl_power_status.setText("Check-in failed.")
                self.lbl_power_status.setStyleSheet(
                    f"font-size: 11px; color: {Colors.DANGER};")
                msg = str(payload)
                # iOS 26 no longer exposes com.apple.dt.devicearbitration
                # (verified: InvalidService / "Failed to start service").
                if any(marker in msg for marker in
                       ("Failed to start service", "InvalidService",
                        "MessageNotSupported", "not supported")):
                    msg = (
                        "Device arbitration isn't available on this device's iOS "
                        "version — Apple no longer exposes the "
                        "'com.apple.dt.devicearbitration' service.\n\n"
                        "This tab only works on older iOS versions. For long "
                        "operations on this device, keep the screen on manually.")
                QMessageBox.warning(self, "Power Assertion Failed", msg)

        self._show_busy("Checking in as device owner...", label=self.lbl_power_status)
        self._run_async(run, on_result)

    def _stop_power_assertion(self):
        proc, self._power_proc = self._power_proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._run_action(
            ["developer", "arbitration", "check-out"],
            self._on_checkout_done,
            timeout=20,
            busy_msg="Releasing assertion...",
            label=self.lbl_power_status)

    def _on_checkout_done(self, ok: bool, out: str):
        self._hide_busy()
        self.btn_power_hold.setEnabled(True)
        self.btn_power_release.setEnabled(False)
        if ok:
            self.lbl_power_status.setText("Assertion released.")
            self.lbl_power_status.setStyleSheet(
                f"font-size: 11px; color: {Colors.TEXT_MUTED};")
        else:
            self.lbl_power_status.setText(
                "Check-out failed — the local process is stopped, but the device "
                "may still consider it in-use.")
            self.lbl_power_status.setStyleSheet(
                f"font-size: 11px; color: {Colors.DANGER};")
            QMessageBox.warning(self, "Check-Out Failed", out)

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
                pmd3_cmd(["amfi", "developer-mode-status"]),
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