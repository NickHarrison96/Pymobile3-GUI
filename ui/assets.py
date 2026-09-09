from pathlib import Path
from PySide6.QtGui import QFontDatabase, QIcon, QPixmap, QPainter
from PySide6.QtCore import Qt, QByteArray
from PySide6.QtSvg import QSvgRenderer

ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
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
