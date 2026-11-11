"""Windows-style home screen with large section tiles."""
from __future__ import annotations

from PySide6.QtCore import QDate, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ..config import APP_VERSION, resolve_logo
from .icons import make_icon
from .logo import AnimatedLogo
from .palette import accent as section_accent, blend, shade

TILES = [
    ("consumers", "Consumers", "Search, add and edit consumer accounts and meters.", "consumers"),
    ("generate", "Generate bill", "Enter a meter reading and create a new bill.", "bill"),
    ("bills", "Bills & payments", "Find bills, collect payments, print or save PDF.", "payments"),
    ("unitrate", "Unit / rate change", "Correct a reading or change consumer / type rates.", "unitrate"),
    ("reports", "Reports & Excel", "Dues, collections and monthly reports with Excel export.", "reports"),
    ("dashboard", "Dashboard", "Totals, recent bills and a quick consumer search.", "dashboard"),
    ("masters", "Master data", "Areas, types, designations, departments and groups.", "masters"),
    ("settings", "Settings", "Database, company, printer and paper settings.", "settings"),
]

ACTIONS = {"excel", "password", "about"}


class TileButton(QAbstractButton):
    """A large clickable card: colour strip, icon, title and description."""

    def __init__(self, icon: QIcon, title: str, subtitle: str, accent: str,
                 parent=None):
        super().__init__(parent)
        self._icon = icon
        self._title = title
        self._subtitle = subtitle
        self._accent = QColor(accent)
        self._title_color = shade(accent, 0.45)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(190, 176)
        self.setAccessibleName(title)
        self.setToolTip(f"{title} - {subtitle}")

    def sizeHint(self) -> QSize:
        return QSize(270, 230)

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        card = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        active = self.underMouse() or self.hasFocus()

        # card fill + coloured top strip (clipped to the rounded corners)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(blend(self._accent.name(), 0.94) if active else QColor("#ffffff"))
        painter.drawRoundedRect(card, 9.0, 9.0)

        path = QPainterPath()
        path.addRoundedRect(card, 9.0, 9.0)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(QRectF(card.left(), card.top(), card.width(), 6.0), self._accent)
        painter.restore()

        painter.setPen(QPen(self._accent if active else QColor("#d3e0ec"),
                            1.5 if active else 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(card, 9.0, 9.0)

        # keep the icon/text block vertically centred when the tile grows
        top = max(14.0, (card.height() - 126.0) / 2.0)
        plate = QRectF(16.0, top, 54.0, 54.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(blend(self._accent.name(), 0.84))
        painter.drawRoundedRect(plate, 11.0, 11.0)
        self._icon.paint(painter, plate.adjusted(9, 9, -9, -9).toRect(),
                         Qt.AlignmentFlag.AlignCenter)

        width = max(40.0, card.width() - 32.0)
        title_font = QFont(self.font())
        title_font.setPointSizeF(12.0)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(self._title_color)
        painter.drawText(QRectF(16.0, top + 62.0, width, 24.0),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self._title)

        sub_font = QFont(self.font())
        sub_font.setPointSizeF(9.0)
        painter.setFont(sub_font)
        painter.setPen(QColor("#5b6b7a"))
        painter.drawText(QRectF(16.0, top + 86.0, width, 40.0),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop |
                         Qt.TextFlag.TextWordWrap,
                         self._subtitle)


class HomeTab(QWidget):
    """Start screen: hero banner plus a grid of section tiles."""

    navigate = Signal(str)
    action = Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.tiles: dict[str, TileButton] = {}
        self._build()
        self.refresh()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QFrame()
        body.setObjectName("homeBody")
        root = QVBoxLayout(body)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        # -- hero banner -------------------------------------------------
        hero = QFrame()
        hero.setObjectName("homeHero")
        h = QHBoxLayout(hero)
        h.setContentsMargins(18, 14, 18, 14)
        h.setSpacing(14)

        self.logo_badge = AnimatedLogo(height=46, plate=True)
        self.logo_badge.set_fallback(make_icon("unitrate", 44, "#1e4f78").pixmap(44, 44))
        h.addWidget(self.logo_badge)

        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title = QLabel("EPBS Desktop")
        title.setObjectName("homeTitle")
        self.company_label = QLabel("Electricity billing")
        self.company_label.setObjectName("homeSub")
        title_box.addWidget(title)
        title_box.addWidget(self.company_label)
        h.addLayout(title_box)
        h.addStretch(1)

        user_box = QVBoxLayout()
        user_box.setSpacing(1)
        self.user_label = QLabel()
        self.user_label.setObjectName("homeSub")
        self.user_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.date_label = QLabel()
        self.date_label.setObjectName("homeSub")
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        user_box.addWidget(self.user_label)
        user_box.addWidget(self.date_label)
        h.addLayout(user_box)
        root.addWidget(hero)

        # -- section title ----------------------------------------------
        head = QHBoxLayout()
        section = QLabel("Main menu")
        section.setObjectName("homeSection")
        head.addWidget(section)
        head.addStretch(1)
        hint = QLabel("Select a block to open that section")
        hint.setObjectName("homeHint")
        head.addWidget(hint)
        root.addLayout(head)

        # -- tiles -------------------------------------------------------
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        for index, (key, title, subtitle, icon_name) in enumerate(TILES):
            colour = section_accent(icon_name)
            tile = TileButton(make_icon(icon_name, 40, colour), title, subtitle, colour)
            tile.clicked.connect(lambda _checked=False, k=key: self._activate(k))
            self.tiles[key] = tile
            grid.addWidget(tile, index // 4, index % 4)
        root.addLayout(grid)
        root.addStretch(1)

        # -- quick actions and status -----------------------------------
        actions = QFrame()
        actions.setObjectName("homeActions")
        row = QHBoxLayout(actions)
        row.setContentsMargins(14, 9, 14, 9)
        row.setSpacing(8)
        quick = QLabel("Quick actions")
        quick.setObjectName("homeSection")
        row.addWidget(quick)
        for label, key, style_name in [("Backup to Excel", "excel", "excelAction"),
                                       ("Change password", "password", "passwordAction"),
                                       ("About EPBS", "about", "aboutAction")]:
            button = QPushButton(label)
            button.setObjectName(style_name)
            button.clicked.connect(lambda _checked=False, k=key: self.action.emit(k))
            row.addWidget(button)
        row.addStretch(1)
        self.status_label = QLabel()
        self.status_label.setObjectName("homeHint")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight |
                                       Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.status_label)
        root.addWidget(actions)

        footer = QLabel(
            f"EPBS Desktop {APP_VERSION}   ·   Tip: every section is also available from the "
            "tabs above."
        )
        footer.setObjectName("homeHint")
        root.addWidget(footer)

        scroll.setWidget(body)
        outer.addWidget(scroll)

    def _set_logo(self, path) -> None:
        if path and self.logo_badge.set_source(path):
            return
        self.logo_badge.set_fallback(make_icon("unitrate", 44, "#1e4f78").pixmap(44, 44))

    def _activate(self, key: str) -> None:
        if key in ACTIONS:
            self.action.emit(key)
        else:
            self.navigate.emit(key)

    def refresh(self) -> None:
        try:
            company = self.ctx.company()
            name = str(company.get("company_name") or "EPBS")
            logo_path = resolve_logo(company.get("logo_url"))
        except Exception:
            name = "EPBS"
            logo_path = resolve_logo(None)
        self._set_logo(logo_path)
        self.company_label.setText(f"{name}   ·   Electricity billing")
        full_name = self.ctx.user.get("full_name") or self.ctx.user_name or "-"
        role = self.ctx.user.get("access_type") or "User"
        self.user_label.setText(f"Signed in as {full_name} ({role})")
        self.date_label.setText(QDate.currentDate().toString("dddd, d MMMM yyyy"))
        cfg = self.ctx.cfg
        self.status_label.setText(
            f"Database: {cfg.db.label()}   ·   Printer: {cfg.printer or 'system default'}"
            f"   ·   Paper: {cfg.paper}   ·   Ink saver on"
        )
