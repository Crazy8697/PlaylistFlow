"""The DarkRelay look, shared by every window and dialog.

Same construction as Lazarus PDF: Fusion style, a dark QPalette, one app-wide
stylesheet, and Material Design icons through qtawesome (mdi6). The colours are
DarkRelay's: near-black ground, cyan #19C2E6 for the accent and anything active,
teal #0E7490 for buttons.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette

BG = "#0a0e14"          # window ground
PANEL = "#10151c"       # menu bar, toolbars, status bar
SURFACE = "#161c24"     # lists, inputs, boxed sections
RAISED = "#1c232d"      # hover on surfaces
BORDER = "#263040"
BORDER_HI = "#33404f"
TEXT = "#e6edf3"
MUTED = "#8b96a5"
DIM = "#5c6672"
ACCENT = "#19C2E6"      # cyan: active modes, selection, focus, glow
ACCENT_INK = "#04161c"  # text on an accent fill
TEAL = "#0E7490"        # buttons
TEAL_HI = "#138aa8"
TEAL_LO = "#0b5c72"
LINK = "#5fd3f0"

QSS = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: 'Segoe UI';
    font-size: 13px;
}}
QMainWindow, QDialog {{ background: {BG}; }}
QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER_HI}; padding: 4px; }}

/* menus */
QMenuBar {{ background: {PANEL}; color: {MUTED}; border-bottom: 1px solid {BORDER}; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {TEAL}; color: #ffffff; border-radius: 4px; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER_HI}; padding: 4px; }}
QMenu::item {{ padding: 5px 22px 5px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {TEAL}; color: #ffffff; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}

/* buttons: teal, lighter on hover, darker pressed, cyan when active */
QPushButton {{
    background: {TEAL};
    border: 1px solid {TEAL_HI};
    border-radius: 6px;
    color: #ffffff;
    padding: 5px 12px;
    font-size: 12px;
}}
QPushButton:hover {{ background: {TEAL_HI}; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {TEAL_LO}; }}
QPushButton:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: {ACCENT_INK}; font-weight: 600; }}
QPushButton:disabled {{ background: {SURFACE}; border-color: {BORDER}; color: {DIM}; }}
QPushButton:default {{ border-color: {ACCENT}; }}
QPushButton#inline {{ padding: 2px 10px; font-size: 11px; }}
/* flat text buttons on the menu bar line (Undo, Save) */
QPushButton#menubtn {{ background: transparent; border: none; color: {MUTED}; padding: 4px 12px; font-size: 13px; }}
QPushButton#menubtn:hover {{ background: {TEAL}; color: #ffffff; border-radius: 4px; }}
/* transport: quiet until hovered */
QPushButton#transport {{ background: {SURFACE}; border: 1px solid {BORDER_HI}; color: {TEXT}; }}
QPushButton#transport:hover {{ background: {TEAL}; border-color: {ACCENT}; }}

/* toolbars: grouped, with a small-caps label and a dotted grip, icons over labels */
QToolBar {{ background: {PANEL}; border: none; border-bottom: 1px solid {BORDER}; spacing: 2px; padding: 3px 4px; }}
QToolBar[group="tools"] {{ border-right: 1px solid {BORDER}; }}
QToolBar[group="tools"]::handle:horizontal {{
    width: 6px; margin: 8px 2px 8px 3px;
    border-left: 2px dotted {DIM}; border-right: 2px dotted {DIM};
}}
QToolBar[group="tools"]::handle:horizontal:hover {{ border-color: {ACCENT}; }}
QToolBar[group="tools"]::handle:vertical {{
    height: 6px; margin: 3px 8px 2px 8px;
    border-top: 2px dotted {DIM}; border-bottom: 2px dotted {DIM};
}}
QToolBar[group="tools"] QToolButton {{
    background: transparent; border: 1px solid transparent; border-radius: 6px;
    color: {TEXT}; padding: 2px 4px; margin: 0 1px; font-size: 11px; min-width: 52px;
}}
QToolBar[group="tools"] QToolButton:hover {{ background: {RAISED}; border-color: {BORDER_HI}; }}
QToolBar[group="tools"] QToolButton:pressed {{ background: {TEAL_LO}; }}
QToolBar[group="tools"] QToolButton:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: {ACCENT_INK}; font-weight: 600; }}
QLabel#grouplabel {{ background: transparent; color: {MUTED}; font-size: 9px; font-weight: 700; letter-spacing: 1px; padding: 0 3px; }}

/* side panel: boxed sections */
QGroupBox {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px;
    margin-top: 16px; padding: 10px 6px 6px 6px;
}}
QGroupBox#spotify_box {{ margin-top: 0; padding-top: 4px; }}
QGroupBox::title {{
    subcontrol-origin: margin; left: 10px; padding: 0 4px;
    color: {MUTED}; font-size: 10px; font-weight: 700; letter-spacing: 1px;
}}
QToolButton#panelbtn {{
    background: {SURFACE}; border: 1px solid {BORDER_HI}; border-radius: 5px; padding: 3px;
}}
QToolButton#panelbtn:hover {{ background: {TEAL}; border-color: {ACCENT}; }}
QToolButton#panelbtn:pressed {{ background: {TEAL_LO}; }}

/* lists, inputs */
QListWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; outline: none; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 4px; color: {TEXT}; }}
QListWidget::item:hover {{ background: {RAISED}; }}
QListWidget::item:selected {{ background: {TEAL}; color: #ffffff; }}
QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser, QSpinBox, QComboBox {{
    background: {SURFACE}; border: 1px solid {BORDER_HI}; border-radius: 5px;
    color: {TEXT}; padding: 5px 8px; selection-background-color: {TEAL};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QPlainTextEdit {{ font-family: Consolas, 'JetBrains Mono', monospace; font-size: 11px; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER_HI}; selection-background-color: {TEAL}; }}
QCheckBox {{ background: transparent; spacing: 8px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {BORDER_HI}; border-radius: 3px; background: {SURFACE}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

/* tabs */
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; top: -1px; background: {BG}; }}
QTabBar::tab {{ background: {PANEL}; color: {MUTED}; border: 1px solid {BORDER}; padding: 6px 16px; margin-right: 2px;
               border-top-left-radius: 6px; border-top-right-radius: 6px; }}
QTabBar::tab:selected {{ background: {BG}; color: {TEXT}; border-bottom-color: {BG}; border-top: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

/* the track table */
QTableWidget {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px;
    gridline-color: transparent; outline: none;
    selection-background-color: {RAISED}; selection-color: {TEXT};
}}
QTableWidget::item {{ padding-left: 6px; border-bottom: 1px solid {BORDER}; }}
QHeaderView::section {{
    background: {PANEL}; color: {DIM}; border: none; border-bottom: 1px solid {BORDER};
    padding: 6px; font-size: 11px; letter-spacing: 1px;
}}

/* scroll bars, splitters, sliders */
QScrollBar:vertical {{ background: {BG}; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: {BG}; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {BORDER_HI}; border-radius: 5px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {TEAL}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: {BG}; }}
QSplitter::handle:hover {{ background: {TEAL_LO}; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER_HI}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 12px; margin: -4px 0; border-radius: 6px; }}
QProgressBar {{ border: 1px solid {BORDER_HI}; border-radius: 5px; text-align: center; background: {SURFACE}; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}

/* status bar and the update strip */
QStatusBar {{ background: {PANEL}; color: {MUTED}; border-top: 1px solid {BORDER}; padding-right: 8px; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ background: transparent; color: {MUTED}; }}
QWidget#update_bar {{ background: rgba(25, 194, 230, 0.12); border: 1px solid {ACCENT}; border-radius: 6px; }}
QWidget#update_bar QLabel {{ color: {TEXT}; font-weight: 600; }}
QWidget#update_bar QPushButton {{ padding: 2px 10px; font-size: 11px; }}

/* readouts */
QLabel#stat {{ color: {MUTED}; font-family: Consolas, monospace; font-size: 12px; }}
QLabel#busy {{ color: {ACCENT}; font-size: 12px; }}
QLabel#now {{ color: {TEXT}; font-size: 13px; }}
QLabel#clock {{ color: {DIM}; font-family: Consolas, monospace; font-size: 11px; }}
QLabel#plname {{ color: {TEXT}; font-size: 15px; font-weight: 600; }}
QLabel#plcount {{ color: {MUTED}; font-size: 12px; font-family: Consolas, monospace; }}
QLabel#cover, QLabel#art {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 4px; }}
QLabel#spotify_logo {{ background: transparent; }}
QWidget#strip {{ background: transparent; }}

/* message boxes and plain dialogs */
QMessageBox, QInputDialog {{ background: {BG}; }}
QMessageBox QLabel {{ background: transparent; }}
QDialogButtonBox {{ background: transparent; }}
"""


def apply(app) -> None:
    """Fusion, the dark palette, the stylesheet and the font, app-wide."""
    app.setStyle("Fusion")
    p = QPalette()
    for role, c in ((QPalette.Window, BG), (QPalette.WindowText, TEXT),
                    (QPalette.Base, SURFACE), (QPalette.AlternateBase, RAISED),
                    (QPalette.Text, TEXT), (QPalette.Button, TEAL),
                    (QPalette.ButtonText, "#ffffff"), (QPalette.Highlight, TEAL),
                    (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, RAISED),
                    (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, DIM),
                    (QPalette.Link, LINK)):
        p.setColor(role, QColor(c))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(DIM))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(DIM))
    app.setPalette(p)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(QSS)


MDI_TTF = "materialdesignicons6-webfont-6.9.96.ttf"
MDI_CHARMAP = "materialdesignicons6-webfont-charmap-6.9.96.json"
_ICONIC = None


def _iconic():
    """Our own qtawesome font set: only Material Design Icons 6, loaded from an explicit
    folder. qtawesome's shared instance, given no folder, copies every bundled font into
    the Windows user fonts folder and registers them in the registry; passing the folder
    skips that, so the program never installs fonts on anyone's PC."""
    global _ICONIC
    if _ICONIC is None:
        import os
        import qtawesome
        from qtawesome.iconic_font import IconicFont
        fonts = os.path.join(os.path.dirname(qtawesome.__file__), "fonts")
        _ICONIC = IconicFont(("mdi6", MDI_TTF, MDI_CHARMAP, fonts))
    return _ICONIC


def icon(name: str, active_ink: bool = True):
    """A Material Design icon (mdi6) in the theme's colours. Checkable buttons get a
    dark glyph when on, to sit on the cyan fill."""
    kw = {"color": TEXT, "color_disabled": DIM}
    if active_ink:
        kw["color_on"] = ACCENT_INK
    return _iconic().icon("mdi6." + name, **kw)


def elided_label(text: str = "", name: str = ""):
    """A QLabel that shortens its text with an ellipsis instead of clipping it, and
    keeps the whole text in its tooltip (Spotify's guidelines: truncated metadata must
    stay viewable in full)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel, QSizePolicy

    class _Elided(QLabel):
        def __init__(self):
            super().__init__()
            self._full = ""
            self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            self.setMinimumWidth(40)

        def setText(self, t):                       # noqa: N802 (Qt name)
            self._full = t or ""
            self.setToolTip(self._full)
            self._fit()

        def text(self):
            return self._full

        def _fit(self):
            fm = self.fontMetrics()
            super().setText(fm.elidedText(self._full, Qt.ElideRight, max(0, self.width())))

        def resizeEvent(self, e):
            super().resizeEvent(e)
            self._fit()

        def sizeHint(self):
            sh = super().sizeHint()
            sh.setWidth(self.fontMetrics().horizontalAdvance(self._full) + 4)
            return sh

    lab = _Elided()
    if name:
        lab.setObjectName(name)
    lab.setText(text)
    return lab
