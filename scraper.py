"""
scraper.py
----------
All network / HTML-parsing logic lives here, behind a small plugin
interface (`SourcePlugin`). Today only `QstheorySource` (求是网 /
www.qstheory.cn) is implemented, but the registry makes it straightforward
to add e.g. a second periodical or an alternate mirror later without
touching the UI or the PDF builder — that is the "扩展空间" the program
was asked to leave room for.

Design notes
~~~~~~~~~~~~
qstheory.cn's public article/TOC pages (as opposed to the ebook.qstheory.cn
flip-book *reader*, which is a JS single-page app) are plain server-rendered
HTML, so this module talks to them with plain `requests` + BeautifulSoup —
no headless browser needed, which keeps the app light and fast.

Because the exact CSS class names used by the site's CMS were not directly
inspectable from this build environment, extraction below is deliberately
*defensive*: it tries a list of known/likely selectors first and falls back
to a generic "biggest link cluster on the page" / trafilatura heuristic.
If qstheory.cn changes its markup, only `QstheorySource` needs to be
touched — try `python -m scraper --selftest` (see bottom of this file)
to quickly verify extraction still works before relying on a full run.
"""
from __future__ import annotations

import re
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from models import Article, Issue

log = logging.getLogger("qiushi.scraper")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15 QiushiDownloader/1.0"
)

CONTENT_SELECTORS = [
    "#content", ".content", "#detailContent", ".detail-content",
    ".article-content", ".texttxt", ".TRS_Editor", ".article_content",
    ".qs_content", "article", ".Custom_UnionStyle",
]

# Filenames like zxcode_xxx.jpg are the site's share/QR-code stamp, not
# real article imagery — skip them.
_SKIP_IMAGE_HINTS = ("zxcode", "weixin_share", "n7/images", "n6/images")


class ScrapeError(RuntimeError):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    return s


class SourcePlugin(ABC):
    """Extension point: implement this to support another periodical/site."""

    id: str = "base"
    display_name: str = "Base source"

    def __init__(self, delay_seconds: float = 0.6):
        self.delay_seconds = delay_seconds
        self.session = _session()

    def _get(self, url: str) -> BeautifulSoup:
        resp = self.session.get(url, timeout=20)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        time.sleep(self.delay_seconds)
        return BeautifulSoup(resp.text, "lxml")

    @abstractmethod
    def list_year_pages(self) -> list[tuple[int, str]]:
        """Return [(year, year_index_url), ...]."""

    @abstractmethod
    def list_issues(self, year: int, year_url: str) -> list[Issue]:
        """Return Issue stubs (no articles yet) for one year."""

    @abstractmethod
    def fetch_issue_detail(self, issue: Issue, progress_cb: Optional[Callable[[float], None]] = None) -> Issue:
        """Populate issue.articles / cover / publish_dt in place, return it."""


class _Registry:
    def __init__(self):
        self._sources: dict[str, type[SourcePlugin]] = {}

    def register(self, cls: type[SourcePlugin]):
        self._sources[cls.id] = cls
        return cls

    def get(self, source_id: str, **kwargs) -> SourcePlugin:
        try:
            cls = self._sources[source_id]
        except KeyError:
            raise ScrapeError(f"未知的内容来源插件: {source_id}")
        return cls(**kwargs)

    def all_ids(self) -> list[str]:
        return list(self._sources.keys())


registry = _Registry()


# ---------------------------------------------------------------------------
# qstheory.cn implementation
# ---------------------------------------------------------------------------

_YEAR_RE = re.compile(r"^(\d{4})年$")
_ISSUE_RE = re.compile(r"《求是》(\d{4})年第(\d+)期")
_PUBLISH_DT_RE = re.compile(
    r"来源[:：]\s*《求是》[^\s]+\s+(?:作者[:：]\s*\S+\s+)?(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})"
)
_PUBLISH_DT_RE_NOAUTHOR = re.compile(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})")
_AUTHOR_RE = re.compile(r"作者[:：]\s*([^\s]+)")


@registry.register
class QstheorySource(SourcePlugin):
    id = "qstheory"
    display_name = "求是网 (qstheory.cn)"

    MULU_URL = "https://www.qstheory.cn/qs/mulu.htm"

    # -- year / issue discovery -------------------------------------------

    def list_year_pages(self) -> list[tuple[int, str]]:
        soup = self._get(self.MULU_URL)
        seen: dict[int, str] = {}
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            m = _YEAR_RE.match(text)
            if not m:
                continue
            year = int(m.group(1))
            url = urljoin(self.MULU_URL, a["href"])
            seen.setdefault(year, url)
        if not seen:
            raise ScrapeError("未能在目录页解析出年份列表，页面结构可能已变化。")
        return sorted(seen.items(), key=lambda kv: -kv[0])

    def list_issues(self, year: int, year_url: str) -> list[Issue]:
        soup = self._get(year_url)
        seen: dict[str, Issue] = {}
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            m = _ISSUE_RE.search(text)
            if not m:
                continue
            y, no = int(m.group(1)), int(m.group(2))
            url = urljoin(year_url, a["href"])
            if url in seen:
                continue
            seen[url] = Issue(
                source_id=self.id,
                year=y,
                issue_no=no,
                title=f"{y}年第{no}期",
                toc_url=url,
                publish_dt=None,
            )
        issues = list(seen.values())
        issues.sort(key=lambda i: i.issue_no)
        return issues

    # -- per-issue detail ---------------------------------------------------

    def fetch_issue_detail(self, issue: Issue, progress_cb: Optional[Callable[[float], None]] = None) -> Issue:
        soup = self._get(issue.toc_url)
        full_text = soup.get_text(" ", strip=True)

        dt_match = _PUBLISH_DT_RE.search(full_text) or _PUBLISH_DT_RE_NOAUTHOR.search(full_text)
        if dt_match:
            try:
                issue.publish_dt = datetime.strptime(dt_match.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                issue.publish_dt = None

        cover = soup.find("img", src=True)
        if cover:
            issue.cover_image_url = urljoin(issue.toc_url, cover["src"])

        article_links = self._extract_article_links(soup, issue.toc_url)
        if not article_links:
            raise ScrapeError(f"未能在期号目录页解析出文章列表: {issue.toc_url}")

        total = len(article_links)
        for idx, (title, url) in enumerate(article_links, start=1):
            try:
                article = self._parse_article(title, url)
                issue.articles.append(article)
            except Exception as exc:  # keep going — one bad article shouldn't kill the issue
                log.warning("跳过无法解析的文章 %s (%s): %s", title, url, exc)
            if progress_cb:
                progress_cb(idx / total)

        return issue

    def _extract_article_links(self, soup: BeautifulSoup, toc_url: str) -> list[tuple[str, str]]:
        root = None
        for sel in CONTENT_SELECTORS:
            found = soup.select_one(sel)
            if found and len(found.get_text(strip=True)) > 20:
                root = found
                break
        root = root or soup.body or soup

        host = urlparse(toc_url).netloc
        ordered: list[tuple[str, str]] = []
        seen_href: dict[str, int] = {}

        for a in root.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = urljoin(toc_url, a["href"])
            if not text or len(text) < 2:
                continue
            parsed = urlparse(href)
            if parsed.netloc and host not in parsed.netloc:
                continue
            if href == toc_url:
                continue
            if _ISSUE_RE.search(text) or _YEAR_RE.match(text):
                continue
            if not (href.endswith(("c.html", ".htm")) or "/c_" in href):
                continue

            if href in seen_href:
                # subtitle continuation line -> merge into existing entry
                i = seen_href[href]
                prev_title, prev_href = ordered[i]
                if text not in prev_title:
                    ordered[i] = (f"{prev_title} {text}".strip(), prev_href)
                continue

            seen_href[href] = len(ordered)
            ordered.append((text, href))

        return ordered

    def _parse_article(self, fallback_title: str, url: str) -> Article:
        soup = self._get(url)

        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else fallback_title

        full_text = soup.get_text(" ", strip=True)
        author_match = _AUTHOR_RE.search(full_text)
        author = author_match.group(1) if author_match else ""

        content_node = None
        for sel in CONTENT_SELECTORS:
            found = soup.select_one(sel)
            if found and len(found.get_text(strip=True)) > 60:
                content_node = found
                break

        if content_node is None:
            # Fallback: use trafilatura's generic readability-style extractor.
            content_node = self._trafilatura_fallback(soup, url)

        html_body, image_urls = self._sanitize_content(content_node, url)

        return Article(
            title=title,
            url=url,
            author=author,
            html_body=html_body,
            image_urls=image_urls,
        )

    @staticmethod
    def _trafilatura_fallback(soup: BeautifulSoup, url: str):
        try:
            import trafilatura
            extracted = trafilatura.extract(
                str(soup), url=url, include_images=True, output_format="html",
                favor_precision=True,
            )
            if extracted:
                return BeautifulSoup(extracted, "lxml")
        except Exception as exc:  # pragma: no cover - best effort fallback
            log.warning("trafilatura 兜底解析失败 %s: %s", url, exc)
        # last resort: whole body
        return soup.body or soup

    @staticmethod
    def _sanitize_content(node, base_url: str) -> tuple[str, list[str]]:
        """Rebuild a minimal, consistently-styled HTML snippet from a messy node."""
        parts: list[str] = []
        images: list[str] = []

        for el in node.find_all(["p", "h2", "h3", "h4", "img", "blockquote", "li"], recursive=True):
            if el.name == "img":
                src = el.get("src") or el.get("data-src") or ""
                if not src or any(h in src for h in _SKIP_IMAGE_HINTS):
                    continue
                abs_src = urljoin(base_url, src)
                images.append(abs_src)
                parts.append(f'<img src="{abs_src}" />')
                continue

            text = el.get_text(" ", strip=True)
            if not text:
                continue
            if el.name in ("h2", "h3", "h4"):
                parts.append(f"<h3>{text}</h3>")
            elif el.name == "blockquote":
                parts.append(f"<blockquote>{text}</blockquote>")
            elif el.name == "li":
                parts.append(f"<li>{text}</li>")
            else:
                parts.append(f"<p>{text}</p>")

        if not parts:
            # Degenerate case: no tagged children found — dump raw text.
            text = node.get_text("\n\n", strip=True)
            parts = [f"<p>{p}</p>" for p in text.split("\n\n") if p.strip()]

        return "\n".join(parts), images


# ---------------------------------------------------------------------------
# Quick manual self-test (no GUI / no PDF rendering), run with:
#     python scraper.py --selftest
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    if "--selftest" in sys.argv:
        src = registry.get("qstheory")
        years = src.list_year_pages()
        print(f"发现 {len(years)} 个年份, 最新: {years[0]}")
        latest_year, latest_url = years[0]
        issues = src.list_issues(latest_year, latest_url)
        print(f"{latest_year} 年共有 {len(issues)} 期, 最新一期: {issues[-1].title}")
        detailed = src.fetch_issue_detail(issues[-1], progress_cb=lambda p: print(f"  {p:.0%}", end="\r"))
        print()
        print(f"共解析出 {len(detailed.articles)} 篇文章, 发布时间: {detailed.publish_dt}")
        for a in detailed.articles[:5]:
            print(" -", a.title, f"({len(a.image_urls)} 张图)")
