"""
ui/theme.py
-----------
Light/dark palette that (a) follows the OS by default, and (b) can be
forced to light or dark from Settings. Qt6's `QStyleHints.colorScheme()`
already tracks macOS/Windows/GNOME dark-mode switches live, so we just
listen to its `colorSchemeChanged` signal and re-apply.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QGuiApplication, QPalette, QColor, QFont
from PySide6.QtWidgets import QApplication

ACCENT = "#c62828"       # 求是's editorial red, used sparingly as an accent
ACCENT_HOVER = "#a81f1f"

_LIGHT = {
    "window": "#f5f5f7", "base": "#ffffff", "text": "#1c1c1e",
    "subtext": "#6b6b70", "border": "#d9d9de", "hover": "#ececef",
    "selected": "#e7ecff",
}
_DARK = {
    "window": "#1e1e20", "base": "#2a2a2d", "text": "#f2f2f3",
    "subtext": "#9d9da3", "border": "#3a3a3d", "hover": "#333336",
    "selected": "#33415e",
}


FONT_STACK = (
    '"PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei", '
    '"Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei", '
    '-apple-system, "Segoe UI", sans-serif'
)


def _qss(c: dict) -> str:
    return f"""
QWidget {{ background: {c['window']}; color: {c['text']}; font-size: 13px; font-family: {FONT_STACK}; }}
QMainWindow {{ background: {c['window']}; }}
#Sidebar {{ background: {c['base']}; border-right: 1px solid {c['border']}; }}
#TopBar {{ background: {c['window']}; border-bottom: 1px solid {c['border']}; }}
QListWidget {{
  background: transparent; border: none; outline: none; padding: 4px;
}}
QListWidget::item {{ padding: 8px 10px; border-radius: 8px; margin: 1px 4px; }}
QListWidget::item:hover {{ background: {c['hover']}; }}
QListWidget::item:selected {{ background: {c['selected']}; color: {c['text']}; }}
QPushButton {{
  background: {c['base']}; border: 1px solid {c['border']}; border-radius: 8px;
  padding: 6px 14px;
}}
QPushButton:hover {{ background: {c['hover']}; }}
QPushButton#Primary {{ background: {ACCENT}; color: white; border: none; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton:disabled {{ color: {c['subtext']}; }}
QLineEdit, QComboBox, QSpinBox {{
  background: {c['base']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 5px 8px;
}}
QProgressBar {{
  background: {c['hover']}; border: none; border-radius: 6px; height: 10px; text-align: center;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 6px; }}
QLabel#Subtext {{ color: {c['subtext']}; }}
QLabel#SectionTitle {{ color: {c['subtext']}; font-weight: 600; padding: 10px 12px 2px; }}
QTextEdit#LogPane {{
  background: {c['base']}; border: 1px solid {c['border']}; border-radius: 8px;
  color: {c['subtext']}; font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 11.5px;
}}
QScrollBar:vertical {{ width: 10px; background: transparent; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {c['subtext']}; }}
QFrame#Card {{ background: {c['base']}; border: 1px solid {c['border']}; border-radius: 10px; }}
"""


class ThemeManager(QObject):
    changed = Signal(bool)  # emits is_dark

    def __init__(self, app: QApplication):
        super().__init__(app)
        self._app = app
        self._mode = "system"
        hints = QGuiApplication.styleHints()
        hints.colorSchemeChanged.connect(self._on_system_change)

    def set_mode(self, mode: str):
        """'system' | 'light' | 'dark'"""
        self._mode = mode
        self.apply()

    def is_dark(self) -> bool:
        if self._mode == "dark":
            return True
        if self._mode == "light":
            return False
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark

    def apply(self):
        dark = self.is_dark()
        c = _DARK if dark else _LIGHT
        self._app.setStyleSheet(_qss(c))

        font = QFont()
        font.setFamilies([
            "PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei",
            "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei",
            "-apple-system", "Segoe UI", "sans-serif",
        ])
        font.setPointSize(13)
        self._app.setFont(font)

        pal = self._app.palette()
        pal.setColor(QPalette.Window, QColor(c["window"]))
        pal.setColor(QPalette.Base, QColor(c["base"]))
        pal.setColor(QPalette.Text, QColor(c["text"]))
        pal.setColor(QPalette.WindowText, QColor(c["text"]))
        self._app.setPalette(pal)
        self.changed.emit(dark)

    def _on_system_change(self, *_):
        if self._mode == "system":
            self.apply()
