"""
Pymobile3-GUI - Files & Applications Workspace
Full-page AFC file system browser, installed applications inspector,
and media manager with upload, download, and container inspection.
"""

import os
import sys
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QLabel, QFileDialog, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QFrame,
    QInputDialog
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QCursor
from pymobile3_gui.ui.theme import Colors
from pymobile3_gui.core.backend.file_system import FileSystemManager, AFCException
from pymobile3_gui.core.backend.resource_manager import safe_run_command


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
        ok, out = safe_run_command([sys.executable, "-m", "pymobiledevice3", "apps", "list"], timeout=15)
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
