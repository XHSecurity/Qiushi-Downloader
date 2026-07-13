"""
models.py
---------
Plain data containers shared by the scraper, the PDF builder and the UI.
Kept dependency-free (no Qt, no requests) so they can be reused/tested in
isolation and by future source plugins.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto


class DownloadState(Enum):
    PENDING = auto()
    FETCHING = auto()
    RENDERING = auto()
    DONE = auto()
    SKIPPED = auto()  # already downloaded
    FAILED = auto()


@dataclass
class Article:
    title: str
    url: str
    author: str = ""
    html_body: str = ""          # sanitised inner HTML of the article body
    image_urls: list[str] = field(default_factory=list)


@dataclass
class Issue:
    """One issue (期) of the periodical."""

    source_id: str               # which SourcePlugin produced this
    year: int
    issue_no: int                # 期号, e.g. 13
    title: str                   # e.g. "2026年第13期"
    toc_url: str                 # the issue's 目录 page
    publish_dt: datetime | None  # exact publish date/time if the site provides one
    cover_image_url: str = ""
    articles: list[Article] = field(default_factory=list)

    state: DownloadState = DownloadState.PENDING
    progress: float = 0.0        # 0..1, used by the UI progress bar
    error: str = ""
    output_path: str = ""

    @property
    def display_date(self) -> str:
        if self.publish_dt:
            return self.publish_dt.strftime("%Y-%m-%d")
        return ""

    @property
    def sort_key(self):
        return (self.year, self.issue_no)
