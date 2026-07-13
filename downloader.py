"""
downloader.py
-------------
Threading glue: runs the (network-bound) scraping on a background
QThread so the UI never blocks, and calls back into the GUI-thread
`PdfRenderer` for the actual PDF write via a blocking queued connection.

Public API used by the UI:
    worker = DownloadWorker(source_id, output_dir, renderer)
    worker.years_ready.connect(...)
    worker.issues_ready.connect(...)
    worker.issue_progress.connect(...)
    worker.issue_done.connect(...)
    worker.issue_failed.connect(...)
    worker.log.connect(...)
    worker.start()
    worker.request_years()
    worker.request_issues(year, year_url)
    worker.request_download(issue)
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from queue import Queue, Empty

from PySide6.QtCore import QThread, Signal, QObject

from models import Issue, DownloadState
from scraper import registry, ScrapeError
from pdf_builder import build_issue_html, PdfBridge
from config import config

log = logging.getLogger("qiushi.downloader")

_INVALID_FS_CHARS = re.compile(r'[\\/:*?"<>|]')


def safe_filename(issue: Issue) -> str:
    """'以相应日期和时间命名' -> filename is built from the issue's own
    publish date/time as reported by the site, with the issue label kept
    for human readability."""
    if issue.publish_dt:
        stamp = issue.publish_dt.strftime("%Y-%m-%d_%H-%M-%S")
    else:
        stamp = "date-unknown"
    label = f"求是_{issue.year}年第{issue.issue_no}期"
    name = f"{stamp}_{label}.pdf"
    return _INVALID_FS_CHARS.sub("_", name)


class _Job:
    __slots__ = ("kind", "payload")

    def __init__(self, kind: str, payload=None):
        self.kind = kind
        self.payload = payload


class DownloadWorker(QThread):
    years_ready = Signal(list)                 # [(year, url), ...]
    issues_ready = Signal(int, list)            # year, [Issue, ...]
    issue_progress = Signal(object, float, str) # issue, 0..1, phase text
    issue_done = Signal(object)                 # issue (state=DONE)
    issue_failed = Signal(object, str)          # issue, error text
    log_message = Signal(str)

    def __init__(self, pdf_bridge: PdfBridge, parent: QObject | None = None):
        super().__init__(parent)
        self._pdf_bridge = pdf_bridge
        self._queue: Queue[_Job] = Queue()
        self._running = True
        self._source_id = config.active_source_id

    # -- public, thread-safe entry points ---------------------------------
    def request_years(self):
        self._queue.put(_Job("years"))

    def request_issues(self, year: int, year_url: str):
        self._queue.put(_Job("issues", (year, year_url)))

    def request_download(self, issue: Issue):
        self._queue.put(_Job("download", issue))

    def stop(self):
        self._running = False
        self._queue.put(_Job("__stop__"))

    # -- QThread main loop --------------------------------------------------
    def run(self):
        source = registry.get(self._source_id, delay_seconds=config.request_delay_seconds)
        while self._running:
            try:
                job = self._queue.get(timeout=0.25)
            except Empty:
                continue

            try:
                if job.kind == "__stop__":
                    break
                elif job.kind == "years":
                    self._handle_years(source)
                elif job.kind == "issues":
                    year, url = job.payload
                    self._handle_issues(source, year, url)
                elif job.kind == "download":
                    self._handle_download(source, job.payload)
            except Exception as exc:  # never let the worker die silently
                log.exception("worker job failed")
                self.log_message.emit(f"发生错误：{exc}")

    # -- job handlers ---------------------------------------------------------
    def _handle_years(self, source):
        self.log_message.emit("正在获取往期年份列表…")
        years = source.list_year_pages()
        self.years_ready.emit(years)

    def _handle_issues(self, source, year: int, year_url: str):
        self.log_message.emit(f"正在获取 {year} 年各期列表…")
        issues = source.list_issues(year, year_url)
        self.issues_ready.emit(year, issues)

    def _handle_download(self, source, issue: Issue):
        out_dir = Path(config.output_dir)
        target = out_dir / safe_filename(issue)

        if target.exists():
            issue.state = DownloadState.SKIPPED
            issue.output_path = str(target)
            self.log_message.emit(f"已存在，跳过：{target.name}")
            self.issue_done.emit(issue)
            return

        issue.state = DownloadState.FETCHING
        self.issue_progress.emit(issue, 0.0, "正在抓取文章内容…")

        def on_progress(p: float):
            self.issue_progress.emit(issue, p * 0.8, "正在抓取文章内容…")

        try:
            source.fetch_issue_detail(issue, progress_cb=on_progress)
        except ScrapeError as exc:
            issue.state = DownloadState.FAILED
            issue.error = str(exc)
            self.issue_failed.emit(issue, str(exc))
            return

        if not issue.articles:
            issue.state = DownloadState.FAILED
            issue.error = "未解析到任何文章"
            self.issue_failed.emit(issue, issue.error)
            return

        issue.state = DownloadState.RENDERING
        self.issue_progress.emit(issue, 0.85, "正在排版生成 PDF…")

        html_doc = build_issue_html(issue)
        ok, err = self._pdf_bridge.render_blocking(html_doc, str(target))

        if not ok:
            issue.state = DownloadState.FAILED
            issue.error = err or "PDF 渲染失败"
            self.issue_failed.emit(issue, issue.error)
            return

        issue.state = DownloadState.DONE
        issue.output_path = str(target)
        issue.progress = 1.0
        self.issue_progress.emit(issue, 1.0, "完成")
        self.log_message.emit(f"已生成：{target.name}")
        self.issue_done.emit(issue)
