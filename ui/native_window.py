"""Pymobile3-GUI - Native window shell: native frame kept, frame extended into client area for a custom titlebar + DWM backdrop."""
import sys
import ctypes
from ctypes import c_int, byref, sizeof, Structure
from PySide6.QtWidgets import QMainWindow, QWidget
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QColor, QPainter

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_MAINWINDOW = 2
WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_NCLBUTTONDOWN = 0x00A1
HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17

RESIZE_MARGIN = 8


class MARGINS(Structure):
    _fields_ = [("cxLeftWidth", c_int), ("cxRightWidth", c_int),
                ("cyTopHeight", c_int), ("cyBottomHeight", c_int)]


def _win_build() -> int:
    try:
        return sys.getwindowsversion().build
    except Exception:
        return 0


def apply_windows_glass(hwnd: int) -> bool:
    """True when a real Mica backdrop was applied (Win11 build 22000+)."""
    if sys.platform != "win32":
        return False
    try:
        dwm = ctypes.windll.dwmapi
        dark = c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, byref(dark), sizeof(dark))
        dwm.DwmExtendFrameIntoClientArea(hwnd, byref(MARGINS(-1, -1, -1, -1)))
        if _win_build() >= 22000:
            bd = c_int(DWMSBT_MAINWINDOW)
            hr = dwm.DwmSetWindowAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, byref(bd), sizeof(bd))
            return hr == 0
        return False
    except Exception:
        return False


class NativeFramelessWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.title_bar_widget = None
        self._is_glass_active = False
        self._drag_pos = QPoint()
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumSize(960, 620)
        self.setMouseTracking(True)

    def set_title_bar(self, widget: QWidget):
        self.title_bar_widget = widget

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == "win32" and not self._is_glass_active:
            self._is_glass_active = apply_windows_glass(int(self.winId()))
            self.update()

    def nativeEvent(self, eventType, message):
        if eventType == b"windows_generic_MSG" and sys.platform == "win32":
            import ctypes.wintypes
            msg = ctypes.wintypes.MSG.from_address(int(message))

            if msg.message == WM_NCCALCSIZE and msg.wParam:
                return True, 0

            if msg.message == WM_NCHITTEST:
                return self._hit_test(msg)

        return super().nativeEvent(eventType, message)

    def _hit_test(self, msg):
        """Handle WM_NCHITTEST for resize borders and title bar drag."""
        x = ctypes.c_short(msg.lParam & 0xFFFF).value
        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value

        # Convert screen coords to window coords
        rect = self.frameGeometry()
        rx = x - rect.left()
        ry = y - rect.top()

        # Check resize margins
        left = rx < RESIZE_MARGIN
        right = rx > rect.width() - RESIZE_MARGIN
        top = ry < RESIZE_MARGIN
        bottom = ry > rect.height() - RESIZE_MARGIN

        if top and left:
            return True, HTTOPLEFT
        if top and right:
            return True, HTTOPRIGHT
        if bottom and left:
            return True, HTBOTTOMLEFT
        if bottom and right:
            return True, HTBOTTOMRIGHT
        if left:
            return True, HTLEFT
        if right:
            return True, HTRIGHT
        if top:
            return True, HTTOP
        if bottom:
            return True, HTBOTTOM

        # Title bar area (top 40px, excluding traffic lights area)
        if ry < 40 and self.title_bar_widget:
            title_rect = self.title_bar_widget.geometry()
            # Allow drag only on empty space in title bar
            if title_rect.contains(rx, ry):
                # Check if clicking on traffic light buttons area (left 60px)
                if rx < 60:
                    return True, HTCLIENT
                return True, HTCAPTION

        return True, HTCLIENT

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._is_glass_active:
            p.fillRect(self.rect(), QColor(10, 11, 16, 40))
        else:
            p.fillRect(self.rect(), QColor(10, 11, 16, 255))