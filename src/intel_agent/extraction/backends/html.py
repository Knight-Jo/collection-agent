"""Dual real HTML backends: Trafilatura and BeautifulSoup (spec §8.3)."""

from __future__ import annotations

from ...contracts.documents import CoverageUnit, Locator
from ..models import Availability, BackendRequest, BackendOutput
from ._base import BaseBackend
from ._util import make_block


class TrafilaturaBackend(BaseBackend):
    backend_id = "trafilatura"
    version = "2.2.0"
    capabilities = ("html_structure",)
    media_types = ("text/html",)

    def availability(self) -> Availability:
        try:
            import trafilatura  # noqa: F401
        except ImportError:
            return "missing_dependency"
        return "available"

    async def run(self, request: BackendRequest) -> BackendOutput:
        import trafilatura

        html = self.read_bytes(request.resource_id)
        text = trafilatura.extract(
            html,
            output_format="txt",
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )
        title = None
        try:
            metadata = trafilatura.extract_metadata(html)
            title = metadata.title if metadata else None
        except Exception:  # noqa: BLE001
            title = None
        blocks = []
        ordinal = 1
        if title:
            blocks.append(
                make_block(
                    self.backend_id, self.version, ordinal, title.strip(),
                    "title", locator=Locator(section_path=["title"]),
                )
            )
            ordinal += 1
        for line in (text or "").split("\n"):
            line = line.strip()
            if not line or (title and line == title.strip()):
                continue
            if line.startswith("- "):
                blocks.append(
                    make_block(
                        self.backend_id, self.version, ordinal, line[2:],
                        "list_item",
                        locator=Locator(section_path=["body"]),
                    )
                )
            else:
                blocks.append(
                    make_block(
                        self.backend_id, self.version, ordinal, line,
                        "paragraph",
                        locator=Locator(section_path=["body"]),
                    )
                )
            ordinal += 1
        status = "success" if blocks else "empty"
        return BackendOutput(
            blocks=blocks,
            coverage=[
                CoverageUnit(
                    unit_type="document",
                    locator=Locator(),
                    status=status,
                )
            ],
            metrics={"backend": self.backend_id},
        )


class BeautifulSoupBackend(BaseBackend):
    backend_id = "beautifulsoup"
    version = "4.15"
    capabilities = ("html_structure",)
    media_types = ("text/html",)

    def availability(self) -> Availability:
        try:
            import bs4  # noqa: F401
        except ImportError:
            return "missing_dependency"
        return "available"

    async def run(self, request: BackendRequest) -> BackendOutput:
        from bs4 import BeautifulSoup

        html = self.read_bytes(request.resource_id).decode(
            "utf-8", errors="replace"
        )
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        title = None
        title_node = soup.find("h1") or soup.find("title")
        if title_node is not None and title_node.get_text(strip=True):
            title = title_node.get_text(strip=True)
        blocks = []
        ordinal = 1
        if title:
            blocks.append(
                make_block(
                    self.backend_id, self.version, ordinal, title, "title",
                    locator=Locator(section_path=["title"]),
                )
            )
            ordinal += 1
        for heading in soup.find_all(["h2", "h3", "h4"]):
            text = heading.get_text(" ", strip=True)
            if text:
                blocks.append(
                    make_block(
                        self.backend_id, self.version, ordinal, text,
                        "heading",
                        locator=Locator(dom_path=_path(heading)),
                    )
                )
                ordinal += 1
        for para in soup.find_all("p"):
            text = para.get_text(" ", strip=True)
            if text:
                blocks.append(
                    make_block(
                        self.backend_id, self.version, ordinal, text,
                        "paragraph",
                        locator=Locator(dom_path=_path(para)),
                    )
                )
                ordinal += 1
        for item in soup.find_all("li"):
            text = item.get_text(" ", strip=True)
            if text:
                blocks.append(
                    make_block(
                        self.backend_id, self.version, ordinal, text,
                        "list_item",
                        locator=Locator(dom_path=_path(item)),
                    )
                )
                ordinal += 1
        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(
                    ["th", "td"]
                )]
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                blocks.append(
                    make_block(
                        self.backend_id, self.version, ordinal,
                        "\n".join(rows), "table",
                        locator=Locator(dom_path=_path(table)),
                    )
                )
                ordinal += 1
        status = "success" if blocks else "empty"
        return BackendOutput(
            blocks=blocks,
            coverage=[
                CoverageUnit(
                    unit_type="document", locator=Locator(), status=status
                )
            ],
            metrics={"backend": self.backend_id},
        )


def _path(node) -> str:
    parts = []
    current = node
    while current is not None and current.name:
        parts.append(str(current.name))
        current = current.parent
    return "/".join(reversed(parts))
