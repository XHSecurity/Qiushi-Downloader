"""
config.py
---------
Centralised, persisted application configuration.

Uses QSettings so it stores itself in the right native location on every
platform automatically:
    macOS   -> ~/Library/Preferences/com.qiushi-tools.QiushiDownloader.plist
    Windows -> Registry (HKEY_CURRENT_USER)
    Linux   -> ~/.config/qiushi-tools/QiushiDownloader.conf
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths

ORG_NAME = "qiushi-tools"
APP_NAME = "QiushiDownloader"
APP_DISPLAY_NAME = "求是刊读下载器"
APP_VERSION = "1.1.0"
APP_AUTHOR = "本工具作者"
APP_COPYRIGHT_YEAR = "2026"
APP_HOMEPAGE = "https://www.qstheory.cn"
APP_DESCRIPTION = "自动抓取《求是》在线期刊，整理排版为按发布日期时间命名的 PDF。"
APP_CONTENT_DISCLAIMER = (
    "本工具仅做个人本地归档 / 离线阅读整理，不用于商业用途或大规模再分发。"
    "《求是》文章内容版权归求是网 / 《求是》杂志社所有。"
)


def assets_dir() -> Path:
    return Path(__file__).parent / "assets"


def icon_path() -> str:
    """Best available icon for the current platform, falling back sensibly."""
    import sys
    d = assets_dir()
    if sys.platform == "darwin" and (d / "icon.icns").exists():
        return str(d / "icon.icns")
    if sys.platform.startswith("win") and (d / "icon.ico").exists():
        return str(d / "icon.ico")
    return str(d / "icon.png")


def default_output_dir() -> Path:
    docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
    base = Path(docs) if docs else Path.home() / "Documents"
    return base / "QiuShi_PDF"


@dataclass
class AppConfig:
    """A thin, typed wrapper around QSettings."""

    _settings: QSettings

    def __init__(self):
        self._settings = QSettings(ORG_NAME, APP_NAME)

    # -- output ---------------------------------------------------------
    @property
    def output_dir(self) -> Path:
        val = self._settings.value("output_dir", str(default_output_dir()))
        path = Path(val)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @output_dir.setter
    def output_dir(self, value: Path | str):
        self._settings.setValue("output_dir", str(value))

    # -- theme ------------------------------------------------------------
    @property
    def theme_mode(self) -> str:
        """'system' | 'light' | 'dark'"""
        return self._settings.value("theme_mode", "system")

    @theme_mode.setter
    def theme_mode(self, value: str):
        self._settings.setValue("theme_mode", value)

    # -- scraping behaviour ----------------------------------------------
    @property
    def request_delay_seconds(self) -> float:
        return float(self._settings.value("request_delay_seconds", 0.6))

    @request_delay_seconds.setter
    def request_delay_seconds(self, value: float):
        self._settings.setValue("request_delay_seconds", value)

    @property
    def include_images(self) -> bool:
        return self._settings.value("include_images", True, type=bool)

    @include_images.setter
    def include_images(self, value: bool):
        self._settings.setValue("include_images", value)

    @property
    def auto_check_enabled(self) -> bool:
        return self._settings.value("auto_check_enabled", False, type=bool)

    @auto_check_enabled.setter
    def auto_check_enabled(self, value: bool):
        self._settings.setValue("auto_check_enabled", value)

    @property
    def auto_check_interval_hours(self) -> int:
        return int(self._settings.value("auto_check_interval_hours", 12))

    @auto_check_interval_hours.setter
    def auto_check_interval_hours(self, value: int):
        self._settings.setValue("auto_check_interval_hours", value)

    @property
    def active_source_id(self) -> str:
        """Which registered SourcePlugin to use — extensibility hook."""
        return self._settings.value("active_source_id", "qstheory")

    @active_source_id.setter
    def active_source_id(self, value: str):
        self._settings.setValue("active_source_id", value)


config = AppConfig()
