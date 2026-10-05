from pathlib import Path
from PySide6.QtGui import QFontDatabase, QIcon, QPixmap, QPainter
from PySide6.QtCore import Qt, QByteArray
from PySide6.QtSvg import QSvgRenderer

from pymobile3_gui.core.backend.paths import resource_path

# Resolve through resource_path() so this works both from source and in the
# frozen build. A naive Path(__file__) walk points at _MEIPASS/pymobile3_gui/
# assets in a PyInstaller bundle, but the spec installs fonts/icons at
# _MEIPASS/assets — the two paths never meet and every icon silently vanishes.
ASSET_DIR = Path(resource_path("assets"))
FONT_DIR = ASSET_DIR / "fonts"
ICON_DIR = ASSET_DIR / "icons"


def load_fonts() -> None:
    """Register bundled fonts. Call once after QApplication is constructed."""
    for ttf in sorted(FONT_DIR.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(ttf))


def icon(name: str, color: str = "#f6f7fb", size: int = 18) -> QIcon:
    """Load a bundled Lucide SVG, recoloured to `color`."""
    path = ICON_DIR / f"{name}.svg"
    if not path.exists():
        return QIcon()
    svg = path.read_text(encoding="utf-8").replace('stroke="currentColor"', f'stroke="{color}"')
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    renderer.render(p)
    p.end()
    return QIcon(pm)
