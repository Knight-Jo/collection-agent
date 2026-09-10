"""Typed, secret-masked search configuration (spec 002 §2.1, §6)."""

from __future__ import annotations

from ..contracts.errors import DomainError
from ..runtime.config import AI_SEARCH_TOOL_NAMES, ResearchSettings
from ..storage.settings import SettingsStore


class SearchSettings:
    """Validated search config over the writable settings store.

    Provider display grouping and executable registration are kept separate:
    AI tools (Exa/Brave/Tavily) are API-key providers, everything else is a
    generic search source. Secrets are write-only; reads return booleans.
    """

    def __init__(
        self, settings: ResearchSettings, store: SettingsStore
    ) -> None:
        self.settings = settings
        self.store = store

    # --- helpers ------------------------------------------------------------

    def _override(self, key: str) -> dict:
        value = self.store.get(key)
        return value if isinstance(value, dict) else {}

    def _provider(self, name: str):
        return self.settings.search.providers.get(name)

    def _has_api_key(self, name: str) -> bool:
        o = self._override(f"ai_tool:{name}")
        if o.get("api_key"):
            return True
        provider = self._provider(name)
        if provider is not None and provider.api_key_env:
            import os

            return bool(os.environ.get(provider.api_key_env))
        return False

    # --- read projections ---------------------------------------------------

    def search_sources(self) -> list[dict]:
        sources = []
        for name, provider in self.settings.search.providers.items():
            if name in AI_SEARCH_TOOL_NAMES:
                continue
            o = self._override(f"search_source:{name}")
            sources.append(
                {
                    "id": name,
                    "name": name,
                    "url": provider.base_url or "",
                    "enabled": o.get("enabled", provider.enabled),
                    "cookie_configured": bool(o.get("cookies")),
                }
            )
        for cid in self.store.get("custom_sources") or []:
            o = self._override(f"search_source:{cid}")
            if not o:
                continue
            sources.append(
                {
                    "id": cid,
                    "name": o.get("name", ""),
                    "url": o.get("url", ""),
                    "enabled": o.get("enabled", True),
                    "cookie_configured": bool(o.get("cookies")),
                    "executable": False,
                }
            )
        return sources

    def ai_search_tools(self) -> list[dict]:
        tools = []
        for name in sorted(AI_SEARCH_TOOL_NAMES):
            provider = self._provider(name)
            o = self._override(f"ai_tool:{name}")
            tools.append(
                {
                    "id": name,
                    "name": name,
                    "description": f"{name} AI search provider",
                    "enabled": o.get(
                        "enabled", provider.enabled if provider else False
                    ),
                    "api_key_configured": self._has_api_key(name),
                    "api_key_env": (provider.api_key_env if provider else None)
                    or f"{name.upper()}_API_KEY",
                }
            )
        return tools

    def revision(self) -> int:
        return self.store.current_revision()

    # --- mutations ----------------------------------------------------------

    def add_search_source(self, name: str, url: str) -> dict:
        from ..storage._ids import new_id

        cid = new_id("src")
        self.store.set(
            f"search_source:{cid}",
            {
                "name": name,
                "url": url,
                "enabled": True,
                "cookies": "",
                "custom": True,
                "executable": False,
            },
        )
        ids = list(self.store.get("custom_sources") or [])
        ids.append(cid)
        self.store.set("custom_sources", ids)
        self.store.bump_revision()
        return {
            "id": cid,
            "name": name,
            "url": url,
            "enabled": True,
            "cookie_configured": False,
            "executable": False,
        }

    def toggle_search_source(self, source_id: str) -> dict:
        o = self._override(f"search_source:{source_id}")
        provider = self._provider(source_id)
        o["enabled"] = not o.get(
            "enabled", provider.enabled if provider else True
        )
        self.store.set(f"search_source:{source_id}", o)
        self.store.bump_revision()
        return self._source_view(source_id)

    def update_search_source(self, source_id: str, patch: dict) -> dict:
        o = self._override(f"search_source:{source_id}")
        if "enabled" in patch:
            o["enabled"] = patch["enabled"]
        if "cookies" in patch:
            o["cookies"] = patch["cookies"]
        self.store.set(f"search_source:{source_id}", o)
        self.store.bump_revision()
        return self._source_view(source_id)

    def toggle_ai_tool(self, tool_id: str) -> dict:
        o = self._override(f"ai_tool:{tool_id}")
        provider = self._provider(tool_id)
        o["enabled"] = not o.get(
            "enabled", provider.enabled if provider else False
        )
        self.store.set(f"ai_tool:{tool_id}", o)
        self.store.bump_revision()
        return self._tool_view(tool_id)

    def update_ai_tool_key(self, tool_id: str, api_key: str) -> dict:
        o = self._override(f"ai_tool:{tool_id}")
        o["api_key"] = api_key
        self.store.set(f"ai_tool:{tool_id}", o)
        self.store.bump_revision()
        return self._tool_view(tool_id)

    def _source_view(self, source_id: str) -> dict:
        provider = self._provider(source_id)
        o = self._override(f"search_source:{source_id}")
        if provider is not None:
            return {
                "id": source_id,
                "name": source_id,
                "url": provider.base_url or "",
                "enabled": o.get("enabled", provider.enabled),
                "cookie_configured": bool(o.get("cookies")),
            }
        if o.get("custom"):
            return {
                "id": source_id,
                "name": o.get("name", ""),
                "url": o.get("url", ""),
                "enabled": o.get("enabled", True),
                "cookie_configured": bool(o.get("cookies")),
                "executable": False,
            }
        raise DomainError("NOT_FOUND", f"search source not found: {source_id}")

    def _tool_view(self, tool_id: str) -> dict:
        provider = self._provider(tool_id)
        o = self._override(f"ai_tool:{tool_id}")
        return {
            "id": tool_id,
            "name": tool_id,
            "description": f"{tool_id} AI search provider",
            "enabled": o.get(
                "enabled", provider.enabled if provider else False
            ),
            "api_key_configured": self._has_api_key(tool_id),
            "api_key_env": (provider.api_key_env if provider else None)
            or f"{tool_id.upper()}_API_KEY",
        }
