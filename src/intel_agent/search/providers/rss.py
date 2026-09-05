"""RSS feed provider (channel=rss, local condition matching)."""

from __future__ import annotations

import email.utils
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from html import unescape

import httpx

from ...contracts.ports import (
    FilterCapability,
    ProviderCapabilities,
)
from ...contracts.research import SearchHit, SearchQuery, SourceType
from .._util import make_hit


def _parse_pubdate(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_tz(value)
        if parsed is not None:
            return datetime(*parsed[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        pass
    return None


class RssProvider:
    name = "rss"

    def __init__(
        self,
        client: httpx.AsyncClient,
        feeds: list[str],
        source_types: list[SourceType] | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.client = client
        self.feeds = feeds
        self.source_types = source_types or ["news"]
        self.timeout_seconds = timeout_seconds

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            source_types=list(self.source_types),
            dates=FilterCapability(supported=True),
            language=FilterCapability(supported=False),
            domains=FilterCapability(supported=False),
            exclude_domains=FilterCapability(supported=False),
        )

    async def search(self, query: SearchQuery, limit: int) -> list[SearchHit]:
        out: list[SearchHit] = []
        terms = [t for t in re.split(r"\s+", query.text.strip()) if t]
        for feed in self.feeds:
            try:
                response = await self.client.get(
                    feed, timeout=self.timeout_seconds
                )
                response.raise_for_status()
            except httpx.HTTPError:
                continue
            entries = _parse_feed(response.text)
            for rank, entry in enumerate(entries, start=1):
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                text = f"{title} {summary}"
                if terms and not any(t in text for t in terms):
                    continue
                hit = make_hit(
                    "rss",
                    query,
                    entry["link"],
                    title=title or None,
                    snippet=summary[:400] or None,
                    published_at=entry.get("published_at"),
                    source_types=self.source_types,
                    rank=rank,
                    score=None,
                    channel="rss",
                )
                out.append(hit)
                if len(out) >= limit:
                    return out
        return out


def _parse_feed(text: str) -> list[dict]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    entries: list[dict] = []
    for item in root.iter():
        tag = item.tag.rsplit("}", 1)[-1].lower()
        if tag not in ("item", "entry"):
            continue
        link = _find_text(item, ("link", "guid", "id")) or ""
        if tag == "entry":
            link = _atom_link(item) or link
        entries.append(
            {
                "title": unescape(_find_text(item, ("title",)) or ""),
                "summary": unescape(
                    _find_text(item, ("description", "summary", "content"))
                    or ""
                ),
                "link": link,
                "published_at": _parse_pubdate(
                    _find_text(item, ("pubdate", "published", "updated"))
                ),
            }
        )
    return entries


def _find_text(node: ET.Element, names: tuple[str, ...]) -> str | None:
    for child in node:
        tag = child.tag.rsplit("}", 1)[-1].lower()
        if tag in names and child.text:
            return child.text.strip()
    return None


def _atom_link(item: ET.Element) -> str | None:
    for child in item:
        tag = child.tag.rsplit("}", 1)[-1].lower()
        if tag == "link":
            href = child.get("href")
            if href:
                return href
    return None
