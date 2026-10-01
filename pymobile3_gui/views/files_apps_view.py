"""
Pymobile3-GUI - Files & Applications Workspace
Full-page AFC file system browser, installed applications inspector,
and media manager with upload, download, and container inspection.
"""

import os
import re
import sys
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QLabel, QFileDialog, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QFrame,
    QInputDialog, QSplitter, QTextEdit
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QCursor
from pymobile3_gui.ui.theme import Colors
from pymobile3_gui.core.backend.file_system import FileSystemManager, AFCException
from pymobile3_gui.core.backend.resource_manager import safe_run_command
from pymobile3_gui.core.backend.paths import pmd3_cmd


class CrashListWorker(QThread):
    loaded = Signal(list)
    error_signal = Signal(str)

    def run(self):
        ok, out = safe_run_command(pmd3_cmd(["crash", "ls"]), timeout=30)
        if not ok:
            self.error_signal.emit(f"Failed to list crash reports: {out}")
            return
        files = [line.strip() for line in out.splitlines() if line.strip()]
        self.loaded.emit(files)


class CrashViewWorker(QThread):
    loaded = Signal(str, str)
    error_signal = Signal(str)

    def __init__(self, filename: str):
        super().__init__()
        self.filename = filename

    def run(self):
        ok, out = safe_run_command(pmd3_cmd(["crash", "parse", self.filename]), timeout=30)
        if not ok:
            self.error_signal.emit(f"Failed to parse crash: {out}")
            return
        clean = re.sub(r"\x1b\[[0-9;]*m", "", out)
        self.loaded.emit(self.filename, clean)


class CrashPullWorker(QThread):
    finished = Signal(bool, str)

    def __init__(self, output_dir: str, filename: str | None = None):
        super().__init__()
        self.output_dir = output_dir
        self.filename = filename

    def run(self):
        args = ["crash", "pull", self.output_dir]
        if self.filename:
            args += ["--remote-file", self.filename]
        ok, out = safe_run_command(pmd3_cmd(args), timeout=120)
        self.finished.emit(ok, out if ok else f"Pull failed: {out}")


class CrashFlushWorker(QThread):
    finished = Signal(bool, str)

    def run(self):
        ok, out = safe_run_command(pmd3_cmd(["crash", "flush"]), timeout=30)
        self.finished.emit(ok, "Crashes flushed" if ok else f"Flush failed: {out}")


class CrashClearWorker(QThread):
    finished = Signal(bool, str)

    def run(self):
        ok, out = safe_run_command(pmd3_cmd(["crash", "clear"]), timeout=30)
        self.finished.emit(ok, "All crashes cleared" if ok else f"Clear failed: {out}")


class IosFileLoadWorker(QThread):
    items_loaded = Signal(list, str)   # items [(name, is_dir)], path
    error_signal = Signal(str)

    def __init__(self, path="/"):
        super().__init__()
        self.path = path

    def run(self):
        try:
            fs = FileSystemManager()
            names = fs.list_dir(self.path)
            items = []
            for name in names:
                if name in (".", ".."):
                    continue
                item_path = (self.path.rstrip("/") + "/" + name).replace("//", "/")
                is_directory = fs.is_dir(item_path)
                items.append((name, is_directory))
            items.sort(key=lambda x: (not x[1], x[0].lower()))
            self.items_loaded.emit(items, self.path)
        except Exception as e:
            self.error_signal.emit(str(e))


class IosAppsWorker(QThread):
    apps_loaded = Signal(list)
    error_signal = Signal(str)

    def run(self):
        ok, out = safe_run_command(pmd3_cmd(["apps", "list"]), timeout=15)
        if not ok:
            ok, out = safe_run_command(["pymobiledevice3", "apps", "list"], timeout=15)

        if not ok:
            self.error_signal.emit(f"Failed to query installed apps: {out}")
            return

        import json
        try:
            data = json.loads(out)
            apps = []
            if isinstance(data, dict):
                for bundle_id, info in data.items():
                    if isinstance(info, dict):
                        apps.append({
                            "name": info.get("CFBundleDisplayName") or info.get("CFBundleName", bundle_id),
                            "bundle_id": bundle_id,
                            "version": info.get("CFBundleShortVersionString", "Unknown"),
                            "type": info.get("ApplicationType", "User"),
                            "container": info.get("Container", info.get("Path", "N/A"))
                        })
            apps.sort(key=lambda x: str(x["name"]).lower())
            self.apps_loaded.emit(apps)
        except Exception as e:
            self.error_signal.emit(f"Failed parsing apps list: {e}")


class FilesAppsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_path = "/"
        self.worker = None
        self.apps_worker = None
        self.crash_list = []
        self.crash_workers = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(18)

        # ── Header ───────────────────────────────────────────────────
        header_layout = QHBoxLayout()
        header_vbox = QVBoxLayout()
        header_vbox.setSpacing(2)

        lbl_eyebrow = QLabel("STORAGE & APPLICATION SYSTEM", self)
        lbl_eyebrow.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {Colors.TEXT_MUTED}; letter-spacing: 1px;")
        header_vbox.addWidget(lbl_eyebrow)

        lbl_title = QLabel("Files & Applications", self)
        lbl_title.setStyleSheet("font-size: 24px; font-weight: 750; color: #ffffff; letter-spacing: -0.5px;")
        header_vbox.addWidget(lbl_title)

        header_layout.addLayout(header_vbox)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # ── Tabs ─────────────────────────────────────────────────────
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

        # ── Tab 1: AFC File Explorer ─────────────────────────────────
        afc_widget = QWidget()
        afc_layout = QVBoxLayout(afc_widget)
        afc_layout.setContentsMargins(8, 8, 8, 8)
        afc_layout.setSpacing(10)

        # Nav bar
        nav_box = QHBoxLayout()
        btn_up = QPushButton("⬆ Up", self)
        btn_up.clicked.connect(self._navigate_up)
        nav_box.addWidget(btn_up)

        self.path_input = QLineEdit(self.current_path, self)
        self.path_input.returnPressed.connect(self._on_go_clicked)
        nav_box.addWidget(self.path_input, stretch=1)

        btn_go = QPushButton("Go", self)
        btn_go.clicked.connect(self._on_go_clicked)
        nav_box.addWidget(btn_go)

        btn_refresh = QPushButton("⟳", self)
        btn_refresh.setToolTip("Refresh current directory")
        btn_refresh.clicked.connect(lambda: self._load_directory(self.current_path))
        nav_box.addWidget(btn_refresh)
        afc_layout.addLayout(nav_box)

        # File list
        self.file_list = QListWidget(self)
        self.file_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        afc_layout.addWidget(self.file_list, stretch=1)

        # Action bar
        act_box = QHBoxLayout()
        self.lbl_afc_status = QLabel("Ready", self)
        self.lbl_afc_status.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 11px;")
        act_box.addWidget(self.lbl_afc_status, stretch=1)

        btn_pull = QPushButton("📥 Pull File to PC", self)
        btn_pull.clicked.connect(self._pull_file)
        act_box.addWidget(btn_pull)

        btn_push = QPushButton("📤 Push File to Device", self)
        btn_push.clicked.connect(self._push_file)
        act_box.addWidget(btn_push)

        btn_mkdir = QPushButton("📁 New Folder", self)
        btn_mkdir.clicked.connect(self._make_folder)
        act_box.addWidget(btn_mkdir)
        afc_layout.addLayout(act_box)

        self.tabs.addTab(afc_widget, "📂 File System (AFC)")

        # ── Tab 2: Apps & Containers ─────────────────────────────────
        apps_widget = QWidget()
        apps_layout = QVBoxLayout(apps_widget)
        apps_layout.setContentsMargins(8, 8, 8, 8)
        apps_layout.setSpacing(10)

        apps_top = QHBoxLayout()
        self.lbl_apps_status = QLabel("Click 'Load Apps' to list installed packages.", self)
        self.lbl_apps_status.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 11px;")
        apps_top.addWidget(self.lbl_apps_status, stretch=1)

        btn_load_apps = QPushButton("⟳ Load Installed Apps", self)
        btn_load_apps.clicked.connect(self._load_apps)
        apps_top.addWidget(btn_load_apps)
        apps_layout.addLayout(apps_top)

        self.apps_table = QTableWidget(0, 5, self)
        self.apps_table.setHorizontalHeaderLabels(["App Name", "Bundle ID", "Version", "Type", "Container Path"])
        self.apps_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.apps_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        apps_layout.addWidget(self.apps_table, stretch=1)

        self.tabs.addTab(apps_widget, "📦 Installed Applications")

        # ── Tab 3: DCIM Media ────────────────────────────────────────
        dcim_widget = QWidget()
        dcim_layout = QVBoxLayout(dcim_widget)
        dcim_layout.setContentsMargins(14, 14, 14, 14)
        dcim_layout.setSpacing(12)

        lbl_dcim_title = QLabel("📷 DCIM Media Quick Access", self)
        lbl_dcim_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #fff;")
        dcim_layout.addWidget(lbl_dcim_title)

        lbl_dcim_desc = QLabel("Instantly jump to /DCIM to view, pull, and archive camera photos and video recordings.", self)
        lbl_dcim_desc.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;")
        dcim_layout.addWidget(lbl_dcim_desc)

        btn_jump_dcim = QPushButton("🖼️ Open /DCIM Directory", self)
        btn_jump_dcim.setFixedWidth(220)
        btn_jump_dcim.clicked.connect(lambda: (self.tabs.setCurrentIndex(0), self._load_directory("/DCIM")))
        dcim_layout.addWidget(btn_jump_dcim)
        dcim_layout.addStretch()

        self.tabs.addTab(dcim_widget, "🖼️ Camera Roll (/DCIM)")

        # ── Tab 4: Crash Reports ─────────────────────────────────────
        crash_widget = QWidget()
        crash_layout = QVBoxLayout(crash_widget)
        crash_layout.setContentsMargins(8, 8, 8, 8)
        crash_layout.setSpacing(10)

        # Controls
        crash_controls = QHBoxLayout()
        self.lbl_crash_status = QLabel("Click 'Load Crash Reports' to list them.", self)
        self.lbl_crash_status.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 11px;")
        crash_controls.addWidget(self.lbl_crash_status, stretch=1)

        btn_crash_load = QPushButton("⟳ Load Crash Reports", self)
        btn_crash_load.clicked.connect(self._load_crashes)
        crash_controls.addWidget(btn_crash_load)

        btn_crash_flush = QPushButton("Flush Pending", self)
        btn_crash_flush.clicked.connect(self._flush_crashes)
        crash_controls.addWidget(btn_crash_flush)

        btn_crash_clear = QPushButton("🗑️ Clear All", self)
        btn_crash_clear.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.DANGER_BG};
                color: {Colors.DANGER};
                border: 1px solid {Colors.DANGER_BORDER};
            }}
            QPushButton:hover {{
                background-color: #5c1515;
                border-color: {Colors.DANGER};
            }}
        """)
        btn_crash_clear.clicked.connect(self._clear_crashes)
        crash_controls.addWidget(btn_crash_clear)
        crash_layout.addLayout(crash_controls)

        # Splitter: list + viewer
        crash_splitter = QSplitter(Qt.Horizontal, self)

        self.crash_list_widget = QListWidget(self)
        self.crash_list_widget.itemDoubleClicked.connect(self._on_crash_selected)
        crash_splitter.addWidget(self.crash_list_widget)

        self.crash_viewer = QTextEdit(self)
        self.crash_viewer.setReadOnly(True)
        self.crash_viewer.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Colors.BG_TERMINAL};
                border: 1px solid {Colors.BORDER_DEFAULT};
                border-radius: 8px;
                padding: 8px;
                font-family: 'JetBrains Mono', 'Consolas', monospace;
                font-size: 11px;
            }}
        """)
        self.crash_viewer.setPlaceholderText("Double-click a crash report to view it.")
        crash_splitter.addWidget(self.crash_viewer)
        crash_splitter.setStretchFactor(0, 1)
        crash_splitter.setStretchFactor(1, 3)
        crash_layout.addWidget(crash_splitter, stretch=1)

        # Action bar
        crash_actions = QHBoxLayout()
        btn_crash_export = QPushButton("📄 Export Selected", self)
        btn_crash_export.clicked.connect(self._export_crash)
        crash_actions.addWidget(btn_crash_export)

        btn_crash_pull = QPushButton("📥 Pull Selected to PC", self)
        btn_crash_pull.clicked.connect(self._pull_crash)
        crash_actions.addWidget(btn_crash_pull)

        btn_crash_pull_all = QPushButton("📥 Pull All to PC", self)
        btn_crash_pull_all.clicked.connect(self._pull_all_crashes)
        crash_actions.addWidget(btn_crash_pull_all)
        crash_actions.addStretch()
        crash_layout.addLayout(crash_actions)

        self.tabs.addTab(crash_widget, "🔥 Crash Reports")

        layout.addWidget(self.tabs)

    def _load_directory(self, path: str):
        self.current_path = path
        self.path_input.setText(path)
        self.lbl_afc_status.setText(f"Loading {path}...")
        self.file_list.clear()

        self.worker = IosFileLoadWorker(path)
        self.worker.items_loaded.connect(self._on_items_loaded)
        self.worker.error_signal.connect(self._on_load_error)
        self.worker.start()

    def _on_items_loaded(self, items: list, path: str):
        self.file_list.clear()
        for name, is_dir in items:
            prefix = "📁 " if is_dir else "📄 "
            item = QListWidgetItem(prefix + name)
            item.setData(Qt.UserRole, (name, is_dir))
            self.file_list.addItem(item)
        self.lbl_afc_status.setText(f"Loaded {len(items)} items in {path}")

    def _on_load_error(self, err: str):
        self.lbl_afc_status.setText(f"Error: {err}")

    def _on_item_double_clicked(self, item: QListWidgetItem):
        name, is_dir = item.data(Qt.UserRole)
        if is_dir:
            next_path = (self.current_path.rstrip("/") + "/" + name).replace("//", "/")
            self._load_directory(next_path)

    def _navigate_up(self):
        if self.current_path in ("/", ""):
            return
        parent_dir = os.path.dirname(self.current_path.rstrip("/"))
        if not parent_dir:
            parent_dir = "/"
        self._load_directory(parent_dir)

    def _on_go_clicked(self):
        target = self.path_input.text().strip() or "/"
        self._load_directory(target)

    def _pull_file(self):
        selected = self.file_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "Selection Required", "Select a file to pull from the device.")
            return

        name, is_dir = selected.data(Qt.UserRole)
        if is_dir:
            QMessageBox.information(self, "Directory Selected", "Please select a single file to pull.")
            return

        dest_dir = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
        if not dest_dir:
            return

        dev_path = (self.current_path.rstrip("/") + "/" + name).replace("//", "/")
        local_path = os.path.join(dest_dir, name)

        try:
            fs = FileSystemManager()
            fs.pull_file(dev_path, local_path)
            QMessageBox.information(self, "Success", f"File saved to:\n{local_path}")
        except Exception as e:
            QMessageBox.critical(self, "Pull Failed", str(e))

    def _push_file(self):
        local_file, _ = QFileDialog.getOpenFileName(self, "Select File to Push to Device")
        if not local_file:
            return

        file_name = os.path.basename(local_file)
        dest_path = (self.current_path.rstrip("/") + "/" + file_name).replace("//", "/")

        try:
            fs = FileSystemManager()
            fs.push_file(local_file, dest_path)
            QMessageBox.information(self, "Success", f"Uploaded:\n{dest_path}")
            self._load_directory(self.current_path)
        except Exception as e:
            QMessageBox.critical(self, "Push Failed", str(e))

    def _make_folder(self):
        name, ok = QInputDialog.getText(self, "New Folder", "Enter folder name:")
        if ok and name.strip():
            target = (self.current_path.rstrip("/") + "/" + name.strip()).replace("//", "/")
            try:
                fs = FileSystemManager()
                fs.mkdir(target)
                self._load_directory(self.current_path)
            except Exception as e:
                QMessageBox.critical(self, "Mkdir Failed", str(e))

    def _load_apps(self):
        self.lbl_apps_status.setText("Querying installed applications...")
        self.apps_table.setRowCount(0)
        self.apps_worker = IosAppsWorker()
        self.apps_worker.apps_loaded.connect(self._on_apps_loaded)
        self.apps_worker.error_signal.connect(lambda e: self.lbl_apps_status.setText(f"Error: {e}"))
        self.apps_worker.start()

    def _on_apps_loaded(self, apps: list):
        self.apps_table.setRowCount(len(apps))
        for row, app in enumerate(apps):
            self.apps_table.setItem(row, 0, QTableWidgetItem(str(app.get("name", ""))))
            self.apps_table.setItem(row, 1, QTableWidgetItem(str(app.get("bundle_id", ""))))
            self.apps_table.setItem(row, 2, QTableWidgetItem(str(app.get("version", ""))))
            self.apps_table.setItem(row, 3, QTableWidgetItem(str(app.get("type", ""))))
            self.apps_table.setItem(row, 4, QTableWidgetItem(str(app.get("container", ""))))
        self.lbl_apps_status.setText(f"Loaded {len(apps)} installed packages.")

    # ── Crash Reports ────────────────────────────────────────────────

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

    def _track_worker(self, worker: QThread):
        self.crash_workers.append(worker)
        worker.finished.connect(lambda: self.crash_workers.remove(worker) if worker in self.crash_workers else None)
        worker.start()

    def _load_crashes(self):
        self.lbl_crash_status.setText("Loading crash reports...")
        self.crash_list_widget.clear()
        self.crash_viewer.clear()
        worker = CrashListWorker()
        worker.loaded.connect(self._on_crashes_loaded)
        worker.error_signal.connect(lambda e: self.lbl_crash_status.setText(f"Error: {e}"))
        self._track_worker(worker)

    def _on_crashes_loaded(self, files: list):
        self.crash_list = files
        for f in files:
            item = QListWidgetItem(f"📄 {f}")
            item.setData(Qt.UserRole, f)
            self.crash_list_widget.addItem(item)
        self.lbl_crash_status.setText(f"Found {len(files)} crash reports")

    def _on_crash_selected(self, item: QListWidgetItem):
        filename = item.data(Qt.UserRole)
        if not filename:
            return
        self.lbl_crash_status.setText(f"Parsing {filename}...")
        worker = CrashViewWorker(filename)
        worker.loaded.connect(self._on_crash_viewed)
        worker.error_signal.connect(lambda e: self.lbl_crash_status.setText(f"Error: {e}"))
        self._track_worker(worker)

    def _on_crash_viewed(self, filename: str, content: str):
        self.crash_viewer.setPlainText(content)
        self.lbl_crash_status.setText(f"Viewing {filename}")

    def _export_crash(self):
        item = self.crash_list_widget.currentItem()
        if not item:
            QMessageBox.warning(self, "Selection Required", "Select a crash report first.")
            return
        filename = item.data(Qt.UserRole)
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export Crash Report",
            filename.replace("/", "_"),
            "Crash Reports (*.ips);;All Files (*)"
        )
        if not dest:
            return
        try:
            with open(dest, "w", encoding="utf-8") as f:
                f.write(self.crash_viewer.toPlainText())
            self._toast(True, f"Saved to:\n{dest}")
        except Exception as e:
            self._toast(False, str(e))

    def _pull_crash(self):
        item = self.crash_list_widget.currentItem()
        if not item:
            QMessageBox.warning(self, "Selection Required", "Select a crash report first.")
            return
        filename = item.data(Qt.UserRole)
        dest_dir = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
        if not dest_dir:
            return
        self.lbl_crash_status.setText(f"Pulling {filename}...")
        worker = CrashPullWorker(dest_dir, filename)
        worker.finished.connect(self._on_crash_pulled)
        self._track_worker(worker)

    def _pull_all_crashes(self):
        if not self.crash_list:
            QMessageBox.warning(self, "No Reports", "Load crash reports first.")
            return
        dest_dir = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
        if not dest_dir:
            return
        self.lbl_crash_status.setText("Pulling all crash reports...")
        worker = CrashPullWorker(dest_dir)
        worker.finished.connect(self._on_crash_pulled)
        self._track_worker(worker)

    def _on_crash_pulled(self, ok: bool, msg: str):
        self.lbl_crash_status.setText(msg)
        self._toast(ok, msg)

    def _flush_crashes(self):
        reply = QMessageBox.question(
            self, "Flush Pending",
            "Flush pending crashes to CrashReports directory?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        worker = CrashFlushWorker()
        worker.finished.connect(self._on_flush_done)
        self._track_worker(worker)

    def _on_flush_done(self, ok: bool, msg: str):
        self._toast(ok, msg)
        if ok:
            self._load_crashes()

    def _clear_crashes(self):
        reply = QMessageBox.warning(
            self, "Clear All Crashes",
            "This will permanently delete ALL crash reports from the device.\n\nAre you sure?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        worker = CrashClearWorker()
        worker.finished.connect(self._on_clear_done)
        self._track_worker(worker)

    def _on_clear_done(self, ok: bool, msg: str):
        self._toast(ok, msg)
        if ok:
            self._load_crashes()
