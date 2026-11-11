"""Light, compact Qt stylesheet (the ink-saving rules are in printing.py).

The screen uses the section accent colours from ``ui/palette.py``; printed
documents stay black on white.
"""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

QSS = """
QWidget { font-family: 'Segoe UI', 'DejaVu Sans', sans-serif; font-size: 9.5pt; color: #1b2733; }
QMainWindow, QDialog { background: #edf3f9; }
QTabWidget::pane { border: 1px solid #c3d2e2; background: #ffffff; border-radius: 0 0 4px 4px; }
QTabBar::tab { background: #e4ecf5; border: 1px solid #c3d2e2; border-bottom: none;
               border-top: 3px solid transparent; padding: 6px 14px; margin-right: 1px;
               color: #33475b; }
QTabBar::tab:selected { background: #ffffff; border-top-color: #2563eb; font-weight: 600;
                        color: #123a5c; }
QTabBar::tab:hover { background: #f1f7fd; }
QPushButton { background: #fbfdff; border: 1px solid #aebfd0; border-radius: 4px;
              padding: 5px 12px; min-height: 16px; }
QPushButton:hover { background: #eef5fc; border-color: #7fa3c4; }
QPushButton:pressed { background: #e0ecf8; }
QPushButton:disabled { color: #98a1aa; background: #f0f2f4; border-color: #d6dde3; }
QPushButton#primary { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #2563eb, stop:1 #1d4ed8);
                      color: #ffffff; border-color: #1d4ed8; font-weight: 600; }
QPushButton#primary:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #3b82f6, stop:1 #2563eb); border-color: #2563eb; }
QPushButton#primary:pressed { background: #1e40af; }
QPushButton#danger { color: #b91c1c; border-color: #e0b4b4; background: #fff8f8; }
QPushButton#danger:hover { background: #fdecec; border-color: #d98b8b; }
QPushButton#excelAction { color: #166534; border-color: #9ed3b1; background: #f2fbf5; }
QPushButton#excelAction:hover { background: #e4f7ea; border-color: #5fb37e; }
QPushButton#passwordAction { color: #9a5b05; border-color: #e6c48a; background: #fffaf0; }
QPushButton#passwordAction:hover { background: #fdf1d8; border-color: #cf9b45; }
QPushButton#aboutAction { color: #1d4ed8; border-color: #a8c2f5; background: #f4f8ff; }
QPushButton#aboutAction:hover { background: #e7f0ff; border-color: #6f95e8; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {
    background: #ffffff; border: 1px solid #aebfd0; border-radius: 4px; padding: 3px 5px;
    selection-background-color: #dbeafe; selection-color: #10243a; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {
    border-color: #2563eb; }
QComboBox QAbstractItemView { selection-background-color: #dbeafe; selection-color: #10243a; }
QTableWidget, QTableView { background: #ffffff; alternate-background-color: #f6faff;
    gridline-color: #dde7f1; border: 1px solid #c3d2e2;
    selection-background-color: #dbeafe; selection-color: #10243a; }
QTableWidget::item { padding: 3px; }
QHeaderView::section { background: #e7effa; color: #1e3a5f; border: none;
    border-right: 1px solid #c3d2e2; border-bottom: 1px solid #c3d2e2;
    padding: 4px; font-weight: 600; }
QGroupBox { border: 1px solid #c3d2e2; border-radius: 5px; margin-top: 13px;
            background: #ffffff; padding-top: 4px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; background: #ffffff;
                   font-weight: 600; color: #1e3a5f; }
QFrame#card { background: #ffffff; border: 1px solid #d8e3ef; border-radius: 6px; }
QFrame#kpi { background: #ffffff; border: 1px solid #d8e3ef; border-left: 4px solid #2563eb;
             border-radius: 6px; }
QFrame#kpi[tone="blue"]   { border-left-color: #2563eb; }
QFrame#kpi[tone="green"]  { border-left-color: #16a34a; }
QFrame#kpi[tone="amber"]  { border-left-color: #d97706; }
QFrame#kpi[tone="rose"]   { border-left-color: #e11d48; }
QFrame#kpi[tone="teal"]   { border-left-color: #0d9488; }
QFrame#kpi[tone="indigo"] { border-left-color: #4f46e5; }
QFrame#kpi[tone="blue"]   QLabel#kpiValue { color: #1d4ed8; }
QFrame#kpi[tone="green"]  QLabel#kpiValue { color: #15803d; }
QFrame#kpi[tone="amber"]  QLabel#kpiValue { color: #b45309; }
QFrame#kpi[tone="rose"]   QLabel#kpiValue { color: #be123c; }
QFrame#kpi[tone="teal"]   QLabel#kpiValue { color: #0f766e; }
QFrame#kpi[tone="indigo"] QLabel#kpiValue { color: #4338ca; }
QLabel#h1 { font-size: 15pt; font-weight: 600; color: #123a5c; }
QLabel#h2 { font-size: 11pt; font-weight: 600; color: #17364d; }
QLabel#muted { color: #5b6b7a; }
QLabel#kpiValue { font-size: 15pt; font-weight: 700; }
QLabel#kpiLabel { color: #5b6b7a; }
QLabel#total { font-size: 14pt; font-weight: 700; color: #0b6b3a; }
QLabel#units { font-size: 14pt; font-weight: 700; color: #1d4ed8; }
QLabel#warning { color: #b45309; }
QListWidget { background: #ffffff; border: 1px solid #aebfd0;
              selection-background-color: #dbeafe; selection-color: #10243a; }
QStatusBar { background: #e4ecf5; color: #33475b; }
QMenuBar { background: #e4ecf5; }
QMenuBar::item:selected { background: #d3e1ef; }
QMenu { background: #ffffff; border: 1px solid #c3d2e2; }
QMenu::item:selected { background: #dbeafe; }
QToolTip { background: #ffffe1; color: #000000; border: 1px solid #000000; padding: 2px; }
QSplitter::handle { background: #d8e3ef; }
QFrame#homeBody { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #eaf4fd, stop:1 #fbfdff); }
QFrame#homeHero { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0e7490, stop:0.5 #1d4ed8, stop:1 #4f46e5);
                  border: 1px solid #1d4ed8; border-radius: 8px; }
QLabel#homeTitle { color: #ffffff; font-size: 20pt; font-weight: 600; }
QLabel#homeSub { color: #dbeafe; font-size: 9.5pt; }
QLabel#homeSection { color: #123a5c; font-size: 12pt; font-weight: 600; }
QLabel#homeHint { color: #5b6b7a; }
QFrame#homeActions { background: #ffffff; border: 1px solid #c9d8e8;
                     border-top: 3px solid #2563eb; border-radius: 8px; }
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = QFont("Segoe UI", 9)
    app.setFont(font)
    app.setStyleSheet(QSS)
