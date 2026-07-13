"""
ui/main_window.py
------------------
The whole UI in one window, kept deliberately simple / native-feeling:

  ┌───────────────┬──────────────────────────────────────────┐
  │  年份           │  期号列表（标题 / 日期 / 进度 / 操作按钮）        │
  │  2026          │  ...                                     │
  │  2025          │  ...                                     │
  │  ...           │                                          │
  ├───────────────┴──────────────────────────────────────────┤
  │  运行日志（可折叠）                                            │
  └──────────────────────────────────────────────────────────┘

Extensibility hooks used here:
  * `config.active_source_id` — which SourcePlugin drives the year/issue
    list, so a future second periodical only needs a new entry in the
    "来源" combo box, nothing else in this file changes.
  * Per-row actions are driven purely off `DownloadState`, so adding a new
    state (e.g. QUEUED_FOR_RETRY) only needs one more branch in
    `IssueRow.set_state`.
"""
from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal, QTimer
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QListWidget, QListWidgetItem, QLabel, QPushButton,
    QHBoxLayout, QVBoxLayout, QSplitter, QProgressBar, QTextEdit, QDialog,
    QFormLayout, QLineEdit, QFileDialog, QComboBox, QSpinBox, QCheckBox,
    QDialogButtonBox, QToolButton, QSizePolicy, QFrame, QMenuBar, QMenu,
)

from models import Issue, DownloadState
from downloader import DownloadWorker
from scraper import registry
from config import (
    config, APP_DISPLAY_NAME, APP_VERSION, APP_AUTHOR, APP_COPYRIGHT_YEAR,
    APP_HOMEPAGE, APP_DESCRIPTION, APP_CONTENT_DISCLAIMER, icon_path,
)
from ui.theme import ThemeManager

_STATE_LABEL = {
    DownloadState.PENDING: ("尚未下载", False),
    DownloadState.FETCHING: ("抓取中…", True),
    DownloadState.RENDERING: ("生成 PDF 中…", True),
    DownloadState.DONE: ("已下载", False),
    DownloadState.SKIPPED: ("已存在", False),
    DownloadState.FAILED: ("失败", False),
}


def _reveal_in_file_manager(path: str):
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", "-R", path], check=False)
        elif system == "Windows":
            subprocess.run(["explorer", "/select,", path], check=False)
        else:
            subprocess.run(["xdg-open", str(Path(path).parent)], check=False)
    except Exception:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))


class IssueRow(QFrame):
    download_clicked = Signal(object)
    layout_changed = Signal()

    def __init__(self, issue: Issue, parent=None):
        super().__init__(parent)
        self.issue = issue
        self.setObjectName("Card")
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        title = QLabel(f"《求是》{issue.title}")
        title.setStyleSheet("font-weight: 600; font-size: 14px;")

        self.subtitle = QLabel(self._subtitle_text())
        self.subtitle.setObjectName("Subtext")

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)

        self.action_btn = QPushButton()
        self.action_btn.setFixedWidth(96)
        self.action_btn.clicked.connect(self._on_action_clicked)

        self._left = QVBoxLayout()
        self._left.setSpacing(2)
        self._left.addWidget(title)
        self._left.addWidget(self.subtitle)
        self._progress_in_layout = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.addLayout(self._left, 1)
        layout.addWidget(self.action_btn, 0, Qt.AlignVCenter)

        self.set_state(issue.state)

    def _set_progress_visible(self, visible: bool):
        if visible and not self._progress_in_layout:
            self._left.addWidget(self.progress)
            self.progress.show()
            self._progress_in_layout = True
            self.layout_changed.emit()
        elif not visible and self._progress_in_layout:
            self._left.removeWidget(self.progress)
            self.progress.hide()
            self._progress_in_layout = False
            self.layout_changed.emit()

    def _subtitle_text(self) -> str:
        date = self.issue.display_date or "发布日期未知"
        state_text, _ = _STATE_LABEL[self.issue.state]
        return f"{date}   ·   {state_text}"

    def set_state(self, state: DownloadState, phase_text: str | None = None):
        self.issue.state = state
        text, busy = _STATE_LABEL[state]
        date = self.issue.display_date or "发布日期未知"
        self.subtitle.setText(f"{date}   ·   {phase_text or text}")
        self._set_progress_visible(busy)

        if state in (DownloadState.DONE, DownloadState.SKIPPED):
            self.action_btn.setText("显示文件")
            self.action_btn.setObjectName("")
        elif state == DownloadState.FAILED:
            self.action_btn.setText("重试")
            self.action_btn.setObjectName("Primary")
        elif busy:
            self.action_btn.setText("下载中…")
            self.action_btn.setEnabled(False)
            self.action_btn.setObjectName("")
        else:
            self.action_btn.setText("下载")
            self.action_btn.setEnabled(True)
            self.action_btn.setObjectName("Primary")
        self.action_btn.setEnabled(not busy)
        self.action_btn.style().unpolish(self.action_btn)
        self.action_btn.style().polish(self.action_btn)

    def set_progress(self, fraction: float, phase_text: str):
        self._set_progress_visible(True)
        self.progress.setValue(int(fraction * 100))
        date = self.issue.display_date or "发布日期未知"
        self.subtitle.setText(f"{date}   ·   {phase_text}")

    def _on_action_clicked(self):
        if self.issue.state in (DownloadState.DONE, DownloadState.SKIPPED):
            if self.issue.output_path:
                _reveal_in_file_manager(self.issue.output_path)
        else:
            self.download_clicked.emit(self.issue)


class SettingsDialog(QDialog):
    def __init__(self, theme: ThemeManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(420)
        self._theme = theme

        self.output_edit = QLineEdit(str(config.output_dir))
        browse_btn = QToolButton()
        browse_btn.setText("选择…")
        browse_btn.clicked.connect(self._choose_dir)
        out_row = QHBoxLayout()
        out_row.addWidget(self.output_edit, 1)
        out_row.addWidget(browse_btn)
        out_row_w = QWidget()
        out_row_w.setLayout(out_row)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("跟随系统", "system")
        self.theme_combo.addItem("浅色", "light")
        self.theme_combo.addItem("深色", "dark")
        idx = self.theme_combo.findData(config.theme_mode)
        self.theme_combo.setCurrentIndex(max(idx, 0))

        self.source_combo = QComboBox()
        for sid in registry.all_ids():
            self.source_combo.addItem(registry.get(sid).display_name, sid)
        idx = self.source_combo.findData(config.active_source_id)
        self.source_combo.setCurrentIndex(max(idx, 0))

        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 5000)
        self.delay_spin.setSuffix(" ms")
        self.delay_spin.setSingleStep(100)
        self.delay_spin.setValue(int(config.request_delay_seconds * 1000))

        self.autocheck_box = QCheckBox("自动检查新一期并下载")
        self.autocheck_box.setChecked(config.auto_check_enabled)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 168)
        self.interval_spin.setSuffix(" 小时")
        self.interval_spin.setValue(config.auto_check_interval_hours)

        form = QFormLayout()
        form.addRow("PDF 保存位置", out_row_w)
        form.addRow("外观", self.theme_combo)
        form.addRow("内容来源", self.source_combo)
        form.addRow("请求间隔（礼貌抓取，避免过快请求）", self.delay_spin)
        form.addRow("", self.autocheck_box)
        form.addRow("检查频率", self.interval_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择保存位置", self.output_edit.text())
        if d:
            self.output_edit.setText(d)

    def save(self):
        config.output_dir = self.output_edit.text()
        config.theme_mode = self.theme_combo.currentData()
        config.active_source_id = self.source_combo.currentData()
        config.request_delay_seconds = self.delay_spin.value() / 1000.0
        config.auto_check_enabled = self.autocheck_box.isChecked()
        config.auto_check_interval_hours = self.interval_spin.value()
        self._theme.set_mode(config.theme_mode)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"关于 {APP_DISPLAY_NAME}")
        self.setFixedWidth(380)

        icon_label = QLabel()
        pix = QIcon(icon_path()).pixmap(96, 96)
        icon_label.setPixmap(pix)
        icon_label.setAlignment(Qt.AlignCenter)

        name_label = QLabel(APP_DISPLAY_NAME)
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setStyleSheet("font-size: 18px; font-weight: 700;")

        version_label = QLabel(f"版本 {APP_VERSION}")
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setObjectName("Subtext")

        desc_label = QLabel(APP_DESCRIPTION)
        desc_label.setAlignment(Qt.AlignCenter)
        desc_label.setWordWrap(True)

        link_label = QLabel(f'<a href="{APP_HOMEPAGE}" style="color:#c62828;">{APP_HOMEPAGE}</a>')
        link_label.setAlignment(Qt.AlignCenter)
        link_label.setOpenExternalLinks(True)

        copyright_label = QLabel(f"© {APP_COPYRIGHT_YEAR} {APP_AUTHOR}   ·   MIT 许可证")
        copyright_label.setAlignment(Qt.AlignCenter)
        copyright_label.setObjectName("Subtext")

        disclaimer = QLabel(APP_CONTENT_DISCLAIMER)
        disclaimer.setAlignment(Qt.AlignCenter)
        disclaimer.setWordWrap(True)
        disclaimer.setObjectName("Subtext")
        disclaimer.setStyleSheet("font-size: 11px;")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(icon_label)
        layout.addWidget(name_label)
        layout.addWidget(version_label)
        layout.addSpacing(6)
        layout.addWidget(desc_label)
        layout.addWidget(link_label)
        layout.addSpacing(6)
        layout.addWidget(copyright_label)
        layout.addWidget(disclaimer)
        layout.addSpacing(4)
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self, worker: DownloadWorker, theme: ThemeManager):
        super().__init__()
        self.worker = worker
        self.theme = theme
        self._rows: dict[str, IssueRow] = {}  # toc_url -> row
        self._pending_auto_download = False

        self.setWindowTitle(APP_DISPLAY_NAME)
        self.setWindowIcon(QIcon(icon_path()))
        self.resize(920, 620)
        self._build_menu_bar()
        self._build_ui()
        self._wire_worker()

        self.worker.start()
        self.worker.request_years()

        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._run_auto_check)
        self._apply_auto_check_settings()

    # -- menu bar -----------------------------------------------------------
    def _build_menu_bar(self):
        menubar = self.menuBar()

        app_menu = menubar.addMenu(APP_DISPLAY_NAME)
        about_action = QAction(f"关于 {APP_DISPLAY_NAME}", self)
        about_action.triggered.connect(self._show_about)
        app_menu.addAction(about_action)

        app_menu.addSeparator()
        prefs_action = QAction("偏好设置…", self)
        prefs_action.setShortcut(QKeySequence.Preferences)
        prefs_action.triggered.connect(self._open_settings)
        app_menu.addAction(prefs_action)

        app_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        app_menu.addAction(quit_action)

        file_menu = menubar.addMenu("文件")
        reveal_action = QAction("打开保存文件夹", self)
        reveal_action.triggered.connect(self._open_output_dir)
        file_menu.addAction(reveal_action)
        refresh_action = QAction("刷新年份列表", self)
        refresh_action.setShortcut(QKeySequence.Refresh)
        refresh_action.triggered.connect(self.worker.request_years)
        file_menu.addAction(refresh_action)

        help_menu = menubar.addMenu("帮助")
        homepage_action = QAction("访问求是网", self)
        homepage_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(APP_HOMEPAGE)))
        help_menu.addAction(homepage_action)
        help_menu.addAction(about_action)

    def _show_about(self):
        AboutDialog(self).exec()

    def _open_output_dir(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.output_dir)))

    # -- auto-check -----------------------------------------------------------
    def _apply_auto_check_settings(self):
        if config.auto_check_enabled:
            self._auto_timer.start(config.auto_check_interval_hours * 3600 * 1000)
        else:
            self._auto_timer.stop()

    def _run_auto_check(self):
        self._pending_auto_download = True
        self._log("自动检查：正在查找是否有新一期…")
        self.worker.request_years()

    # -- UI construction ----------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_issue_pane())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([160, 760])
        root.addWidget(splitter, 1)

        self.log_pane = QTextEdit()
        self.log_pane.setObjectName("LogPane")
        self.log_pane.setReadOnly(True)
        self.log_pane.setFixedHeight(110)
        root.addWidget(self.log_pane)

        footer = QLabel(f"© {APP_COPYRIGHT_YEAR} {APP_AUTHOR}   ·   {APP_CONTENT_DISCLAIMER}")
        footer.setObjectName("Subtext")
        footer.setStyleSheet("font-size: 10.5px; padding: 4px 12px;")
        footer.setWordWrap(True)
        root.addWidget(footer)

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 10, 16, 10)

        title = QLabel(f"{APP_DISPLAY_NAME}")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        subtitle = QLabel(f"v{APP_VERSION}")
        subtitle.setObjectName("Subtext")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)

        self.download_all_btn = QPushButton("下载本年全部")
        self.download_all_btn.setObjectName("Primary")
        self.download_all_btn.clicked.connect(self._download_all_current_year)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.worker.request_years)

        settings_btn = QPushButton("设置")
        settings_btn.clicked.connect(self._open_settings)

        layout.addWidget(self.download_all_btn)
        layout.addWidget(refresh_btn)
        layout.addWidget(settings_btn)
        return bar

    def _build_sidebar(self) -> QWidget:
        wrap = QWidget()
        wrap.setObjectName("Sidebar")
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(0)

        label = QLabel("年份")
        label.setObjectName("SectionTitle")
        layout.addWidget(label)

        self.year_list = QListWidget()
        self.year_list.currentItemChanged.connect(self._on_year_selected)
        layout.addWidget(self.year_list, 1)
        return wrap

    def _build_issue_pane(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(10, 10, 10, 0)

        self.issue_list = QListWidget()
        self.issue_list.setSpacing(6)
        self.issue_list.setSelectionMode(QListWidget.NoSelection)
        self.issue_list.setFrameShape(QListWidget.NoFrame)
        layout.addWidget(self.issue_list)
        return wrap

    # -- worker signal wiring -------------------------------------------------
    def _wire_worker(self):
        self.worker.years_ready.connect(self._on_years_ready)
        self.worker.issues_ready.connect(self._on_issues_ready)
        self.worker.issue_progress.connect(self._on_issue_progress)
        self.worker.issue_done.connect(self._on_issue_done)
        self.worker.issue_failed.connect(self._on_issue_failed)
        self.worker.log_message.connect(self._log)

    # -- slots ------------------------------------------------------------
    def _on_years_ready(self, years: list[tuple[int, str]]):
        self.year_list.clear()
        for year, url in years:
            item = QListWidgetItem(f"{year} 年")
            item.setData(Qt.UserRole, (year, url))
            self.year_list.addItem(item)
        if years:
            self.year_list.setCurrentRow(0)

    def _on_year_selected(self, current: QListWidgetItem, _prev):
        if not current:
            return
        year, url = current.data(Qt.UserRole)
        self.issue_list.clear()
        self._rows.clear()
        self.worker.request_issues(year, url)

    def _on_issues_ready(self, year: int, issues: list[Issue]):
        self.issue_list.clear()
        self._rows.clear()
        sorted_issues = sorted(issues, key=lambda i: -i.issue_no)
        for issue in sorted_issues:
            item = QListWidgetItem()
            row = IssueRow(issue)
            row.download_clicked.connect(self.worker.request_download)
            row.layout_changed.connect(lambda r=row, it=item: it.setSizeHint(r.minimumSizeHint()))
            self.issue_list.addItem(item)
            self.issue_list.setItemWidget(item, row)
            item.setSizeHint(row.minimumSizeHint())
            self._rows[issue.toc_url] = row

        if self._pending_auto_download:
            self._pending_auto_download = False
            pending = [i for i in sorted_issues if i.state == DownloadState.PENDING]
            if pending:
                latest = pending[0]
                self._log(f"自动检查：发现新一期 {latest.title}，开始下载…")
                self.worker.request_download(latest)
            else:
                self._log("自动检查：当前最新一期已下载，无需处理。")

    def _on_issue_progress(self, issue: Issue, fraction: float, phase: str):
        row = self._rows.get(issue.toc_url)
        if row:
            row.set_progress(fraction, phase)

    def _on_issue_done(self, issue: Issue):
        row = self._rows.get(issue.toc_url)
        if row:
            row.set_state(issue.state)

    def _on_issue_failed(self, issue: Issue, error: str):
        row = self._rows.get(issue.toc_url)
        if row:
            row.set_state(DownloadState.FAILED, phase_text=f"失败：{error}")
        self._log(f"[错误] {issue.title}: {error}")

    def _download_all_current_year(self):
        for row in self._rows.values():
            if row.issue.state in (DownloadState.PENDING, DownloadState.FAILED):
                self.worker.request_download(row.issue)

    def _open_settings(self):
        dlg = SettingsDialog(self.theme, self)
        if dlg.exec() == QDialog.Accepted:
            dlg.save()
            self._apply_auto_check_settings()

    def _log(self, message: str):
        self.log_pane.append(message)

    def closeEvent(self, event):
        self.worker.stop()
        self.worker.wait(2000)
        super().closeEvent(event)
