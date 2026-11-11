"""On-screen colours.

Each section has its own accent colour, used by the Home tiles, the tab icons
and the dashboard cards.  Printing deliberately stays monochrome (see
``printing.py``) so the ink-saver rules are not affected.
"""
from __future__ import annotations

from PySide6.QtGui import QColor

# accent colour per section (keys are the icon names)
ACCENTS = {
    "home": "#1d4ed8",        # blue
    "dashboard": "#4f46e5",   # indigo
    "consumers": "#0e7490",   # teal-blue
    "bill": "#15803d",        # green
    "payments": "#c2410c",    # orange
    "unitrate": "#7c3aed",    # violet
    "reports": "#0d9488",     # teal
    "masters": "#be185d",     # rose
    "settings": "#475569",    # slate
    "excel": "#15803d",
}

DEFAULT_ACCENT = "#1f5f8b"


def accent(name: str) -> str:
    """Accent colour for a section/icon name."""
    return ACCENTS.get(name, DEFAULT_ACCENT)


def blend(color: str, white: float = 0.86) -> QColor:
    """Mix ``color`` with white (0 = colour, 1 = white)."""
    base = QColor(color)
    if not base.isValid():
        base = QColor(DEFAULT_ACCENT)
    white = max(0.0, min(1.0, float(white)))
    return QColor(
        round(base.red() + (255 - base.red()) * white),
        round(base.green() + (255 - base.green()) * white),
        round(base.blue() + (255 - base.blue()) * white),
    )


def shade(color: str, black: float = 0.2) -> QColor:
    """Darken ``color`` towards black (0 = colour, 1 = black)."""
    base = QColor(color)
    black = max(0.0, min(1.0, float(black)))
    return QColor(
        round(base.red() * (1 - black)),
        round(base.green() * (1 - black)),
        round(base.blue() * (1 - black)),
    )
