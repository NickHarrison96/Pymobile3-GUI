"""
Pymobile3-GUI - Theme and Styling Configuration
Quiet Precision: Apple-inspired restraint, deep contrast, refined typography, and subtle micro-borders.
"""

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtCore import Qt

class Colors:
    # Canvas & Surface - increased contrast for readability
    BG_WINDOW = "#0d1117"
    BG_SIDEBAR = "#161b22"
    BG_SURFACE = "#1c2128"
    BG_CARD = "#21262d"
    BG_CARD_HOVER = "#2a2f3a"
    BG_CARD_ACTIVE = "#30363d"
    BG_DOCK = "rgba(22, 27, 34, 0.95)"
    BG_DRAWER = "#161b22"
    BG_TERMINAL = "#0d1117"

    # Borders - more visible
    BORDER_SUBTLE = "#30363d"
    BORDER_DEFAULT = "#3d4451"
    BORDER_MUTED = "#484f5c"
    BORDER_HOVER = "#58a6ff"
    BORDER_FOCUS = "#58a6ff"

    # Accents & States
    ACCENT_PRIMARY = "#388bfd"
    ACCENT_PRIMARY_HOVER = "#58a6ff"
    ACCENT_GLOW = "rgba(56, 139, 253, 0.35)"
    
    SUCCESS = "#3fb950"
    SUCCESS_BG = "#11371d"
    SUCCESS_BORDER = "#2d6b3a"

    WARNING = "#d29922"
    WARNING_BG = "#3d330e"
    WARNING_BORDER = "#664d0e"

    DANGER = "#f85149"
    DANGER_BG = "#491115"
    DANGER_BORDER = "#7f2226"

    # Text Colors - higher contrast
    TEXT_PRIMARY = "#e6edf3"
    TEXT_SECONDARY = "#8b949e"
    TEXT_MUTED = "#6e7681"
    TEXT_INVERTED = "#0d1117"

    # Traffic light buttons
    TRAFFIC_CLOSE = "#ff5f57"
    TRAFFIC_MIN = "#febc2e"
    TRAFFIC_MAX = "#28c840"


def get_application_stylesheet() -> str:
    """Returns the primary QSS stylesheet for the application."""
    return f"""
    QWidget {{
        color: {Colors.TEXT_PRIMARY};
        font-family: 'Inter', 'Segoe UI Variable Text', 'Segoe UI', -apple-system, sans-serif;
        font-size: 13px;
        outline: none;
    }}

    QMainWindow {{
        background-color: transparent;
    }}

    /* Scrollbars */
    QScrollBar:vertical {{
        border: none;
        background: transparent;
        width: 8px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: #2a3140;
        min-height: 24px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #3e485e;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        border: none;
        background: none;
        height: 0px;
    }}

    QScrollBar:horizontal {{
        border: none;
        background: transparent;
        height: 8px;
        margin: 0px;
    }}
    QScrollBar::handle:horizontal {{
        background: #3a4150;
        min-width: 24px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: #505868;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        border: none;
        background: none;
        width: 0px;
    }}

    /* Buttons - consistent styling with clear feedback */
    QPushButton {{
        background-color: {Colors.BG_CARD};
        color: {Colors.TEXT_PRIMARY};
        border: 1px solid {Colors.BORDER_DEFAULT};
        border-radius: 8px;
        padding: 8px 16px;
        font-weight: 600;
        font-size: 12px;
    }}
    QPushButton:hover {{
        background-color: {Colors.BG_CARD_HOVER};
        border-color: {Colors.BORDER_HOVER};
        color: {Colors.TEXT_PRIMARY};
    }}
    QPushButton:pressed {{
        background-color: {Colors.BG_CARD_ACTIVE};
        border-color: {Colors.ACCENT_PRIMARY};
        padding: 9px 15px 7px 17px;
    }}
    QPushButton:disabled {{
        background-color: {Colors.BG_SURFACE};
        color: {Colors.TEXT_MUTED};
        border-color: {Colors.BORDER_SUBTLE};
    }}

    QPushButton.primary {{
        background-color: {Colors.ACCENT_PRIMARY};
        color: #ffffff;
        border: 1px solid {Colors.ACCENT_PRIMARY_HOVER};
    }}
    QPushButton.primary:hover {{
        background-color: {Colors.ACCENT_PRIMARY_HOVER};
        border-color: #79c0ff;
    }}
    QPushButton.primary:pressed {{
        background-color: #1d4ed8;
        padding: 9px 15px 7px 17px;
    }}

    QPushButton.danger {{
        background-color: {Colors.DANGER_BG};
        color: {Colors.DANGER};
        border: 1px solid {Colors.DANGER_BORDER};
    }}
    QPushButton.danger:hover {{
        background-color: #5c1515;
        border-color: #f85149;
    }}
    QPushButton.danger:pressed {{
        background-color: #3d0f0f;
        padding: 9px 15px 7px 17px;
    }}

    /* Line Edits */
    QLineEdit {{
        background-color: {Colors.BG_CARD};
        color: {Colors.TEXT_PRIMARY};
        border: 1px solid {Colors.BORDER_DEFAULT};
        border-radius: 8px;
        padding: 7px 12px;
        selection-background-color: {Colors.ACCENT_PRIMARY};
    }}
    QLineEdit:focus {{
        border-color: {Colors.BORDER_FOCUS};
    }}

    /* Tables & Tree Views */
    QTableWidget, QTreeView, QListWidget {{
        background-color: {Colors.BG_SURFACE};
        color: {Colors.TEXT_PRIMARY};
        border: 1px solid {Colors.BORDER_DEFAULT};
        border-radius: 10px;
        gridline-color: {Colors.BORDER_SUBTLE};
        selection-background-color: #203354;
        selection-color: {Colors.TEXT_PRIMARY};
        outline: none;
    }}
    QHeaderView::section {{
        background-color: #121620;
        color: {Colors.TEXT_SECONDARY};
        padding: 6px 10px;
        border: none;
        border-bottom: 1px solid {Colors.BORDER_DEFAULT};
        border-right: 1px solid {Colors.BORDER_SUBTLE};
        font-weight: 600;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}

    /* Progress Bar */
    QProgressBar {{
        border: 1px solid {Colors.BORDER_SUBTLE};
        border-radius: 5px;
        background-color: #131722;
        text-align: center;
        color: {Colors.TEXT_MUTED};
        font-size: 11px;
        font-weight: 600;
        height: 10px;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                    stop:0 #38bdf8, stop:1 #3b82f6);
        border-radius: 4px;
    }}

    /* Card Frames */
    QFrame.card {{
        background-color: {Colors.BG_CARD};
        border: 1px solid {Colors.BORDER_DEFAULT};
        border-radius: 14px;
    }}

    /* ComboBox */
    QComboBox {{
        background-color: {Colors.BG_CARD};
        color: {Colors.TEXT_PRIMARY};
        border: 1px solid {Colors.BORDER_DEFAULT};
        border-radius: 8px;
        padding: 6px 12px;
        font-weight: 500;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {Colors.BG_CARD};
        color: {Colors.TEXT_PRIMARY};
        border: 1px solid {Colors.BORDER_MUTED};
        selection-background-color: #243552;
        border-radius: 6px;
        padding: 4px;
    }}

    QPlainTextEdit, QTextEdit {{
        font-family: 'JetBrains Mono', 'Consolas', monospace;
    }}
    """
