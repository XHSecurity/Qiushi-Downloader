#!/usr/bin/env python3
"""
main.py
-------
Entry point. Wires together: QApplication -> ThemeManager -> PdfRenderer
(GUI thread) -> PdfBridge -> DownloadWorker (background QThread) -> MainWindow.

Run with:
    python main.py
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from config import config, ORG_NAME, APP_NAME, APP_DISPLAY_NAME, icon_path
from pdf_builder import PdfRenderer, PdfBridge
from downloader import DownloadWorker
from ui.theme import ThemeManager
from ui.main_window import MainWindow


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    QApplication.setOrganizationName(ORG_NAME)
    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationDisplayName(APP_DISPLAY_NAME)
    if hasattr(Qt, "AA_DontCreateNativeWidgetSiblings"):
        QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(icon_path()))

    theme = ThemeManager(app)
    theme.set_mode(config.theme_mode)

    # PdfRenderer wraps QtWebEngine and MUST live on the GUI thread.
    renderer = PdfRenderer()
    bridge = PdfBridge(renderer)

    worker = DownloadWorker(bridge)
    window = MainWindow(worker, theme)
    window.show()

    exit_code = app.exec()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
