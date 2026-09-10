"""
Pymobile3-GUI - Main Application Entry Point
Standalone desktop application engineered for Windows 10 & 11
with native Mica/Acrylic glass backdrop, full-page workspaces,
and real-time background operation telemetry.
"""

import sys

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer, QObject, QThread, Signal
from PySide6.QtGui import QIcon, QFont

from pymobile3_gui.ui.theme import get_application_stylesheet, Colors
from pymobile3_gui.ui.assets import load_fonts
from pymobile3_gui.ui.native_window import NativeFramelessWindow
from pymobile3_gui.ui.title_bar import TitleBar
from pymobile3_gui.ui.sidebar import NavigationSidebar
from pymobile3_gui.ui.operation_dock import OperationDock
from pymobile3_gui.ui.operation_drawer import OperationDrawer
from pymobile3_gui.ui.toast import Toast
from pymobile3_gui.core.device_poller import DevicePoller
from pymobile3_gui.core.task_manager import TaskManager
from pymobile3_gui.core.backend.tunnel_manager import get_tunnel_manager
from pymobile3_gui.core.backend.elevation import is_admin, relaunch_as_admin

from pymobile3_gui.views.device_view import DeviceView
from pymobile3_gui.views.files_apps_view import FilesAppsView
from pymobile3_gui.views.acquisition_view import AcquisitionView
from pymobile3_gui.views.developer_view import DeveloperView
from pymobile3_gui.views.restore_view import RestoreView
from pymobile3_gui.views.syslog_view import SyslogView


APP_USER_MODEL_ID = "Pymobile3GUI.Windows.v1"


def _set_windows_app_id():
    """Sets explicit AppUserModelID so Windows taskbar groups and icons properly."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


class LogBridge(QObject):
    """
    Thread-safe funnel for events produced off the GUI thread.

    TunneldManager's health monitor runs in a plain Python thread; touching a
    widget from there is undefined behaviour in Qt. Emitting a signal is safe
    from any thread, and the queued connection delivers on the GUI thread.
    """
    message = Signal(str)
    tunnel_lost = Signal(str)


class MainWindow(NativeFramelessWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pymobile3-GUI")
        self.resize(1180, 780)

        # ── Central Widget & Main VBox ────────────────────────────────
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Custom Apple Title Bar ────────────────────────────────────
        self.title_bar = TitleBar(self)
        self.set_title_bar(self.title_bar)
        main_layout.addWidget(self.title_bar)

        # ── Middle Work Area: Sidebar + Stacked Workspaces ────────────
        body_widget = QWidget(self)
        body_layout = QHBoxLayout(body_widget)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.sidebar = NavigationSidebar(self)
        body_layout.addWidget(self.sidebar)

        self.stack = QStackedWidget(self)
        self.stack.setStyleSheet("background-color: transparent;")

        # Initialize the 6 full-page views
        self.view_device = DeviceView(self)
        self.view_files = FilesAppsView(self)
        self.view_acquisition = AcquisitionView(self)
        self.view_developer = DeveloperView(self)
        self.view_restore = RestoreView(self)
        self.view_syslog = SyslogView(self)

        self.stack.addWidget(self.view_device)       # Index 0
        self.stack.addWidget(self.view_files)        # Index 1
        self.stack.addWidget(self.view_acquisition)  # Index 2
        self.stack.addWidget(self.view_developer)    # Index 3
        self.stack.addWidget(self.view_restore)      # Index 4
        self.stack.addWidget(self.view_syslog)       # Index 5

        body_layout.addWidget(self.stack, stretch=1)
        main_layout.addWidget(body_widget, stretch=1)

        # ── Bottom Drawers & Persistent Operation Dock ────────────────
        self.operation_drawer = OperationDrawer(self)
        self.operation_drawer.hide()
        self.operation_drawer.closed.connect(self.operation_drawer.hide)
        main_layout.addWidget(self.operation_drawer)

        self.operation_dock = OperationDock(self)
        self.operation_dock.toggle_drawer.connect(self._toggle_operation_drawer)
        main_layout.addWidget(self.operation_dock)

        # ── Core Services & Signals ───────────────────────────────────
        self.poller = DevicePoller(self)
        self.poller.device_discovered.connect(self._on_device_discovered)
        self.poller.device_disconnected.connect(self._on_device_disconnected)

        self.title_bar.refresh_clicked.connect(self._refresh_device)
        self.sidebar.workspace_changed.connect(self._on_workspace_changed)
        self.view_device.navigate_requested.connect(self._on_navigate_requested)

        # Task manager log routing to drawer
        tm = TaskManager.instance()
        tm.task_progress.connect(self.operation_drawer.update_task)
        tm.task_log.connect(lambda tid, line: self.operation_drawer.append_log(line))

        # Tunnel diagnostics into the same drawer, so a tunnel that dies mid-session
        # says so instead of failing silently.
        self.log_bridge = LogBridge(self)
        self.log_bridge.message.connect(self.operation_drawer.append_log)
        self.log_bridge.tunnel_lost.connect(self._on_tunnel_lost)
        get_tunnel_manager(
            log_callback=self.log_bridge.message.emit,
            on_lost=self.log_bridge.tunnel_lost.emit,
        )

        # Toast overlay, created last so it paints above the workspace.
        self.toast = Toast(self)
        self._tunnel_reconnect_worker = None

        # Initial device poll after window is presented
        QTimer.singleShot(400, self._refresh_device)

    def _on_workspace_changed(self, index: int):
        self.stack.setCurrentIndex(index)

    def _on_navigate_requested(self, index: int):
        self.sidebar._on_btn_clicked(index)

    def _refresh_device(self):
        if not self.poller.isRunning():
            self.title_bar.set_device_status(False, "", "Querying usbmuxd...")
            self.poller.start()

    def _on_device_discovered(self, info: dict):
        name = info.get("DeviceName") or info.get("Model") or "iPhone"
        os_ver = info.get("OS", "iOS")
        conn = info.get("Connection", "USB")

        self.title_bar.set_device_status(True, name, f"{os_ver} · {conn}")
        self.sidebar.set_device_info(info)
        self.view_device.update_device(info)

    def _on_device_disconnected(self):
        self.title_bar.set_device_status(False)
        self.sidebar.set_device_info({})
        self.view_device.update_device({})

    def _toggle_operation_drawer(self):
        self.operation_drawer.setVisible(not self.operation_drawer.isVisible())

    # ── Tunnel loss handling ──────────────────────────────────────────
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "toast", None):
            self.toast.reposition()

    def _on_tunnel_lost(self, detail: str):
        """
        Offer a reconnect rather than performing one. No timeout: an unattended
        machine should still find the prompt waiting.
        """
        self.toast.show_message(
            title="RSD tunnel lost",
            body=f"{detail}\n\nReconnect now?",
            actions=[("Reconnect", self._reconnect_tunnel)],
            level="warning",
            timeout_ms=0,
        )

    def _reconnect_tunnel(self):
        if self._tunnel_reconnect_worker and self._tunnel_reconnect_worker.isRunning():
            return
        self.operation_drawer.append_log("[tunnel] reconnect requested by user")

        # start() blocks on elevation and readiness polling, so it cannot run on
        # the GUI thread.
        class _ReconnectWorker(QThread):
            done = Signal(bool, str)

            def run(self):
                ok, msg = get_tunnel_manager().start()
                self.done.emit(ok, msg)

        self._tunnel_reconnect_worker = _ReconnectWorker(self)
        self._tunnel_reconnect_worker.done.connect(self._on_tunnel_reconnected)
        self._tunnel_reconnect_worker.start()

    def _on_tunnel_reconnected(self, ok: bool, msg: str):
        self.operation_drawer.append_log(f"[tunnel] reconnect: {msg}")
        if ok:
            self.toast.show_message(
                title="Tunnel reconnected",
                body="Developer services are available again.",
                level="info",
                timeout_ms=5000,
            )
        else:
            self.toast.show_message(
                title="Reconnect failed",
                body=msg,
                actions=[("Try again", self._reconnect_tunnel)],
                level="error",
                timeout_ms=0,
            )


# Passed to the elevated relaunch so a failed elevation cannot loop forever.
NO_ELEVATE_FLAG = "--no-elevate"


def _ensure_elevated() -> bool:
    """
    Relaunch elevated on Windows so the RSD tunnel can start without a second
    UAC prompt mid-session.

    Returns True when this process should exit because an elevated instance is
    taking over. A declined prompt is not fatal — the app still runs, and the
    tunnel falls back to elevating just the tunneld process on demand.
    """
    if sys.platform != "win32" or is_admin() or NO_ELEVATE_FLAG in sys.argv:
        return False

    started, message = relaunch_as_admin(extra_args=[NO_ELEVATE_FLAG])
    if started:
        return True
    print(f"[elevation] {message} Continuing unelevated.", file=sys.stderr)
    return False


def main():
    if _ensure_elevated():
        return

    _set_windows_app_id()
    app = QApplication(sys.argv)
    load_fonts()
    app.setStyleSheet(get_application_stylesheet())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
