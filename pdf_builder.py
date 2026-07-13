"""
pdf_builder.py
--------------
Two responsibilities, kept in one small module since they're tightly
related and both PDF-output concerns:

1. `build_issue_html(issue)` — pure function, turns a populated `Issue`
   into one self-contained, nicely typeset HTML document (cover, table of
   contents, then every article with its images, in a serif magazine
   layout with a running Chinese title).

2. `PdfRenderer` — a QObject that must live on the GUI thread (QtWebEngine
   requirement) and turns that HTML into an actual PDF file using
   Chromium's print pipeline, which reliably handles CJK text shaping and
   remote images with zero extra native dependencies (no wkhtmltopdf /
   Cairo / Pango install step needed on any platform).

   Worker threads call `PdfRenderer.render()` through a blocking queued
   Qt connection (see downloader.py) so the async `printToPdf` call still
   behaves like a normal synchronous function from the caller's point of
   view, while actually executing safely on the GUI thread.
"""
from __future__ import annotations

import html as html_escape
import logging

import threading

from PySide6.QtCore import QObject, QUrl, QMarginsF, QEventLoop, Qt, Signal
from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile

from models import Issue

log = logging.getLogger("qiushi.pdf")

_CSS = """
@page { margin: 18mm 16mm; }
* { box-sizing: border-box; }
body {
  font-family: "PingFang SC", "Microsoft YaHei", "Noto Serif CJK SC",
               "Songti SC", serif;
  color: #1c1c1e;
  line-height: 1.9;
  font-size: 14px;
}
.cover {
  height: 253mm;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  page-break-after: always;
}
.cover img { max-width: 78%; max-height: 60%; object-fit: contain; margin-bottom: 14mm; border-radius: 4px; }
.cover h1 { font-size: 30px; letter-spacing: 4px; margin: 0 0 6px; }
.cover .subtitle { font-size: 14px; color: #6b6b70; letter-spacing: 2px; }
.toc { page-break-after: always; }
.toc h2 { font-size: 20px; border-bottom: 2px solid #c62828; padding-bottom: 8px; }
.toc ol { padding-left: 20px; }
.toc li { margin: 10px 0; font-size: 14.5px; }
.toc .author { color: #8a8a8e; font-size: 12.5px; margin-left: 6px; }
article { page-break-before: always; }
article h1 { font-size: 21px; text-align: center; margin-bottom: 4px; }
article .byline { text-align: center; color: #8a8a8e; font-size: 12px; margin-bottom: 20px; }
article p { margin: 0 0 14px; text-indent: 2em; text-align: justify; }
article blockquote { margin: 0 0 14px 0; padding-left: 14px; border-left: 3px solid #c62828; color: #444; }
article h3 { font-size: 16px; margin: 20px 0 10px; }
article img { display: block; max-width: 100%; margin: 10px auto; border-radius: 3px; }
footer.gen-note { color: #b0b0b5; font-size: 10px; text-align: center; margin-top: 40px; }
"""


def build_issue_html(issue: Issue) -> str:
    esc = html_escape.escape

    def _toc_line(i: int, a) -> str:
        author_span = f'<span class="author">/ {esc(a.author)}</span>' if a.author else ""
        return f'<li><a href="#article-{i}">{esc(a.title)}</a>{author_span}</li>'

    toc_items = "\n".join(_toc_line(i, a) for i, a in enumerate(issue.articles))

    articles_html = "\n".join(
        f'''<article id="article-{i}">
  <h1>{esc(a.title)}</h1>
  <div class="byline">{esc(issue.title)}{f" · {esc(a.author)}" if a.author else ""}</div>
  {a.html_body}
</article>'''
        for i, a in enumerate(issue.articles)
    )

    cover_img = f'<img src="{esc(issue.cover_image_url)}" />' if issue.cover_image_url else ""
    date_line = issue.display_date or ""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<style>{_CSS}</style>
</head>
<body>
  <section class="cover">
    {cover_img}
    <h1>《求是》{esc(issue.title)}</h1>
    <div class="subtitle">{esc(date_line)}</div>
  </section>

  <section class="toc">
    <h2>目 录</h2>
    <ol>{toc_items}</ol>
  </section>

  {articles_html}

  <footer class="gen-note">由「求是刊读下载器」自动生成 &middot; 来源 www.qstheory.cn</footer>
</body>
</html>"""


class PdfRenderer(QObject):
    """Must be instantiated on the GUI thread. See module docstring."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._profile = QWebEngineProfile(f"qiushi-pdf-{id(self)}", self)
        self._page = QWebEnginePage(self._profile, self)

    def render(self, html_doc: str, output_path: str) -> tuple[bool, str]:
        """Render HTML -> PDF. Must be called from the GUI thread (this
        object lives there) — see `PdfBridge` below for the thread-safe
        way a worker thread should call this.
        """
        result = {"ok": False, "error": ""}
        load_loop = QEventLoop()
        print_loop = QEventLoop()

        def on_load(ok: bool):
            if not ok:
                result["error"] = "页面加载失败（可能是图片/网络问题）"
            load_loop.quit()

        def on_printed(path: str, ok: bool):
            result["ok"] = ok
            if not ok:
                result["error"] = result["error"] or "PDF 生成失败"
            print_loop.quit()

        self._page.loadFinished.connect(on_load)
        self._page.pdfPrintingFinished.connect(on_printed)
        try:
            self._page.setHtml(html_doc, QUrl("https://www.qstheory.cn/"))
            load_loop.exec()
            if not result["error"]:
                layout = QPageLayout(
                    QPageSize(QPageSize.A4),
                    QPageLayout.Portrait,
                    QMarginsF(0, 0, 0, 0),
                )
                self._page.printToPdf(output_path, layout)
                print_loop.exec()
        finally:
            self._page.loadFinished.disconnect(on_load)
            self._page.pdfPrintingFinished.disconnect(on_printed)

        return result["ok"], result["error"]


class PdfBridge(QObject):
    """Lives on the GUI thread and lets a background worker thread request
    a render and *block until it's done*, without touching QtWebEngine
    directly from off the GUI thread (which Qt does not allow).

    Pattern: the worker thread calls `render_blocking()`, which emits a
    queued signal into this object (safe — Qt marshals it across threads
    automatically) and then waits on a plain `threading.Event`. The GUI
    thread's event loop delivers the signal, `_on_render` executes the
    actual (GUI-thread-only) PdfRenderer.render(), stashes the result, and
    wakes the waiting worker thread back up.
    """

    _do_render = Signal(str, str, object)

    def __init__(self, renderer: PdfRenderer, parent=None):
        super().__init__(parent)
        self._renderer = renderer
        self._do_render.connect(self._on_render, Qt.QueuedConnection)

    def render_blocking(self, html_doc: str, output_path: str) -> tuple[bool, str]:
        box = {"event": threading.Event(), "ok": False, "error": ""}
        self._do_render.emit(html_doc, output_path, box)
        box["event"].wait()
        return box["ok"], box["error"]

    def _on_render(self, html_doc: str, output_path: str, box: dict):
        try:
            ok, err = self._renderer.render(html_doc, output_path)
        except Exception as exc:  # pragma: no cover - defensive
            ok, err = False, str(exc)
        box["ok"], box["error"] = ok, err
        box["event"].set()
