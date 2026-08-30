"""Vertical search providers: parsing, degradation, cascades, admission."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

import httpx
import pytest

from intel_agent.config import CrawlConfig
from intel_agent.crawl import crawl_collect
from intel_agent.evidence import load_document
from intel_agent.fetch import FetchedResponse
from intel_agent.search.academic import academic_search
from intel_agent.search.news import news_search
from intel_agent.search.provider import (
    ALLOWED_ACCESS_MODES,
    REGISTRY,
    ProviderMetadata,
    SearchRequest,
    credentialed_providers,
    search_cache_key,
)
from intel_agent.search.providers.arxiv import ArxivProvider
from intel_agent.search.providers.brave import BraveProvider
from intel_agent.search.providers.crossref import CrossrefProvider
from intel_agent.search.providers.exa import ExaProvider
from intel_agent.search.providers.gdelt import GDELTProvider
from intel_agent.search.providers.gitee import GiteeProvider
from intel_agent.search.providers.github import GitHubProvider
from intel_agent.search.providers.semantic_scholar import (
    SemanticScholarProvider,
)
from intel_agent.search.providers.so360 import So360NewsProvider
from intel_agent.search.providers.tavily import TavilyProvider
from tests.conftest import new_task

ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>https://arxiv.org/abs/2501.00001</id>
    <published>2025-01-02T00:00:00Z</published>
    <title>Low Altitude Economy Survey</title>
    <summary>A survey of eVTOL regulation.</summary>
    <author><name>Alice Zhang</name></author>
  </entry>
</feed>"""


def _searxng_response(results):
    return httpx.Response(
        200,
        json={
            "results": results,
            "unresponsive_engines": [],
        },
    )


@pytest.mark.asyncio
async def test_search_stack_without_credentials():
    # Import every production provider so the registry is fully populated.
    import intel_agent.search.providers.arxiv  # noqa: F401
    import intel_agent.search.providers.crossref  # noqa: F401
    import intel_agent.search.providers.gdelt  # noqa: F401
    import intel_agent.search.providers.gitee  # noqa: F401
    import intel_agent.search.providers.github  # noqa: F401
    import intel_agent.search.providers.searxng  # noqa: F401
    import intel_agent.search.providers.semantic_scholar  # noqa: F401  # noqa: F401
    import intel_agent.search.providers.so360  # noqa: F401

    providers = REGISTRY.providers()
    assert providers, "no providers registered"
    for provider in providers:
        metadata = provider.metadata
        assert metadata.requires_credentials is False, metadata.name
        assert metadata.requires_payment is False, metadata.name
        assert metadata.supports_anonymous is True, metadata.name
        assert metadata.access_mode in ALLOWED_ACCESS_MODES, metadata.name


def test_registry_rejects_paid_provider():
    from intel_agent.search.provider import ProviderRegistry

    registry = ProviderRegistry()

    class Paid:
        metadata = ProviderMetadata(
            name="exa",
            access_mode="OPEN_ANONYMOUS",
            requires_payment=True,
            supports_anonymous=True,
        )

        async def search(self, client, request):
            return []

    with pytest.raises(ValueError, match="requires_payment"):
        registry.register(Paid())  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_cls", "host", "path", "payload", "expected"),
    [
        (
            ExaProvider,
            "exa.test",
            "/search",
            {
                "results": [
                    {
                        "title": "Exa",
                        "url": "https://example.com/exa",
                        "summary": "summary",
                    }
                ]
            },
            "exa",
        ),
        (
            BraveProvider,
            "brave.test",
            "/web/search",
            {
                "web": {
                    "results": [
                        {
                            "title": "Brave",
                            "url": "https://example.com/brave",
                            "description": "summary",
                        }
                    ]
                }
            },
            "brave",
        ),
        (
            TavilyProvider,
            "tavily.test",
            "/search",
            {
                "results": [
                    {
                        "title": "Tavily",
                        "url": "https://example.com/tavily",
                        "content": "summary",
                    }
                ]
            },
            "tavily",
        ),
    ],
)
async def test_credentialed_adapters_map_results_without_leaking_key(
    provider_cls, host, path, payload, expected
):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == host
        assert (
            "secret-key" in request.headers.get("x-api-key", "")
            or "secret-key" in request.headers.get("X-Subscription-Token", "")
            or b"secret-key" in request.content
        )
        return httpx.Response(200, json=payload)

    provider = provider_cls(
        api_key="secret-key", base_url=f"https://{host}", min_interval=0
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        results = await provider.search(client, SearchRequest(query="topic"))
    assert len(results) == 1
    assert results[0].provider == expected
    assert results[0].url.startswith("https://example.com/")


def test_credentialed_providers_require_explicit_enablement(monkeypatch):
    from intel_agent.config import AiNativeSearchConfig

    monkeypatch.setenv("EXA_API_KEY", "secret-key")
    cfg = AiNativeSearchConfig()
    assert credentialed_providers(cfg) == []
    cfg.exa.enabled = True
    providers = credentialed_providers(cfg)
    assert [provider.metadata.name for provider in providers] == ["exa"]


def test_credentialed_provider_without_key_degrades(monkeypatch):
    from intel_agent.config import AiNativeSearchConfig

    monkeypatch.delenv("EXA_API_KEY", raising=False)
    cfg = AiNativeSearchConfig(
        exa={"enabled": True, "api_key_env": "EXA_API_KEY"}
    )

    assert credentialed_providers(cfg) == []


@pytest.mark.asyncio
async def test_github_parses_repos_and_issues_with_roles():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.github.com"
        if "/search/repositories" in request.url.path:
            payload = {
                "items": [
                    {
                        "full_name": "acme/drone-os",
                        "html_url": "https://github.com/acme/drone-os",
                        "description": "Open source flight stack",
                        "stargazers_count": 3200,
                        "forks_count": 100,
                        "language": "Rust",
                        "pushed_at": "2025-06-01T00:00:00Z",
                        "fork": False,
                        "owner": {"login": "acme"},
                    },
                    {
                        "full_name": "user/forked",
                        "html_url": "https://github.com/user/forked",
                        "description": "",
                        "stargazers_count": 0,
                        "forks_count": 0,
                        "fork": True,
                        "owner": {"login": "user"},
                    },
                ]
            }
            return httpx.Response(200, json=payload)
        payload = {
            "items": [
                {
                    "title": "Range limited to 10km",
                    "html_url": "https://github.com/acme/drone-os/issues/7",
                    "body": "Flight range is limited in v1.2",
                    "state": "open",
                    "number": 7,
                    "created_at": "2025-05-01T00:00:00Z",
                    "user": {"login": "tester"},
                    "repository_url": "https://api.github.com/repos/acme/drone-os",
                }
            ]
        }
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        provider = GitHubProvider(min_interval=0)
        results = await provider.search(
            client, SearchRequest(query="drone flight stack")
        )

    assert [r.extra.get("kind") for r in results] == [
        "repository",
        "repository",
        "issue",
    ]
    repo, fork, issue = results
    assert repo.provider_source_type == "software"
    assert repo.evidence_role == "primary"
    assert repo.published_at == "2025-06-01T00:00:00Z"
    assert fork.evidence_role == "secondary"
    assert issue.evidence_role == "supporting"
    assert issue.extra["issue_number"] == 7
    assert provider.last_calls == 2


@pytest.mark.asyncio
async def test_github_rate_limited_degrades_to_searxng_site_search():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(403)
        assert request.url.host == "searxng.test"
        assert "site:github.com" in request.url.params["q"]
        return _searxng_response(
            [
                {
                    "title": "drone-os repo",
                    "url": "https://github.com/acme/drone-os",
                    "content": "",
                    "engines": ["google"],
                }
            ]
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        provider = GitHubProvider(
            searxng_url="http://searxng.test", min_interval=0
        )
        results = await provider.search(
            client, SearchRequest(query="drone flight stack")
        )

    assert len(results) == 1
    assert results[0].url == "https://github.com/acme/drone-os"
    assert provider.last_calls == 3


@pytest.mark.asyncio
async def test_arxiv_parses_atom():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "export.arxiv.org"
        return httpx.Response(200, text=ARXIV_ATOM)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        provider = ArxivProvider(min_interval=0)
        results = await provider.search(
            client, SearchRequest(query="low altitude economy")
        )

    assert len(results) == 1
    result = results[0]
    assert result.url == "https://arxiv.org/abs/2501.00001"
    assert result.provider_source_type == "academic"
    assert result.evidence_role == "primary"
    assert result.author == "Alice Zhang"
    assert result.published_at == "2025-01-02"


@pytest.mark.asyncio
async def test_crossref_parses_works():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.crossref.org"
        return httpx.Response(
            200,
            json={
                "message": {
                    "items": [
                        {
                            "DOI": "10.1000/xyz",
                            "title": ["eVTOL regulation review"],
                            "URL": "https://publisher.example/article",
                            "published": {"date-parts": [[2025, 3]]},
                            "author": [{"given": "Bob", "family": "Li"}],
                            "container-title": ["J. Air Law"],
                            "is-referenced-by-count": 42,
                        }
                    ]
                }
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        provider = CrossrefProvider(min_interval=0)
        results = await provider.search(
            client, SearchRequest(query="eVTOL regulation")
        )

    assert len(results) == 1
    result = results[0]
    assert result.url == "https://publisher.example/article"
    assert result.published_at == "2025-03"
    assert result.extra["citation_count"] == 42
    assert result.provider_source_type == "academic"


@pytest.mark.asyncio
async def test_semantic_scholar_429_degrades_to_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.semanticscholar.org"
        return httpx.Response(429)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        provider = SemanticScholarProvider(min_interval=0)
        results = await provider.search(client, SearchRequest(query="eVTOL"))

    assert results == []
    assert provider.last_calls == 0


@pytest.mark.asyncio
async def test_gdelt_parses_articles():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.gdeltproject.org"
        assert request.url.params["mode"] == "artlist"
        return httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "url": "https://news.example/story",
                        "title": "Drone maker raises funding",
                        "seendate": "20250601T000000Z",
                        "domain": "news.example",
                        "language": "English",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        provider = GDELTProvider(min_interval=0)
        results = await provider.search(
            client, SearchRequest(query="drone funding")
        )

    assert len(results) == 1
    assert results[0].provider_source_type == "news"
    assert results[0].published_at == "20250601T000000Z"
    assert results[0].extra["domain"] == "news.example"


def _routed_handler(
    routes: Mapping[str, Callable | httpx.Response],
):
    def handler(request: httpx.Request) -> httpx.Response:
        route = routes.get(request.url.host)
        if route is None:
            raise AssertionError(f"unexpected host: {request.url.host}")
        return route(request) if callable(route) else route  # type: ignore[return-value]

    return handler


@pytest.mark.asyncio
async def test_academic_cascade_supplements_s2_when_below_threshold():
    routes = {
        "export.arxiv.org": httpx.Response(200, text=ARXIV_ATOM),
        "api.crossref.org": httpx.Response(
            200,
            json={
                "message": {
                    "items": [
                        {
                            "DOI": "10.1000/a",
                            "title": ["Second paper"],
                            "URL": "https://pub.example/2",
                            "published": {"date-parts": [[2025]]},
                            "author": [{"given": "C", "family": "D"}],
                        }
                    ]
                }
            },
        ),
        "api.semanticscholar.org": httpx.Response(
            200,
            json={
                "data": [
                    {
                        "title": "Third paper",
                        "url": "https://www.semanticscholar.org/paper/3",
                        "abstract": "",
                        "authors": [{"name": "E"}],
                        "year": 2025,
                    }
                ]
            },
        ),
    }

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_routed_handler(routes))
    ) as client:
        outcome = await academic_search(
            client,
            "low altitude economy",
            arxiv=ArxivProvider(min_interval=0),
            crossref=CrossrefProvider(min_interval=0),
            semantic_scholar=SemanticScholarProvider(min_interval=0),
            supplement_threshold=3,
        )

    assert outcome["provider_calls"] == 3
    assert len(outcome["results"]) == 3
    assert "arxiv" in outcome["engines_used"]
    assert outcome["degraded"] == []


@pytest.mark.asyncio
async def test_academic_cascade_skips_s2_and_dedupes_when_enough():
    def arxiv_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=ARXIV_ATOM)

    def crossref_handler(request: httpx.Request) -> httpx.Response:
        items = [
            {
                "DOI": f"10.1000/{i}",
                "title": [f"Paper {i}"],
                "URL": f"https://pub.example/{i}",
                "published": {"date-parts": [[2025]]},
                "author": [{"given": "A", "family": "B"}],
            }
            for i in range(3)
        ]
        # one duplicate of the arXiv abs page to prove URL dedupe
        items[0]["URL"] = "https://arxiv.org/abs/2501.00001"
        return httpx.Response(200, json={"message": {"items": items}})

    routes = {
        "export.arxiv.org": arxiv_handler,
        "api.crossref.org": crossref_handler,
        "api.semanticscholar.org": (
            lambda request: (_ for _ in ()).throw(
                AssertionError("S2 must not be called")
            )
        ),
    }

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_routed_handler(routes))
    ) as client:
        outcome = await academic_search(
            client,
            "low altitude economy",
            arxiv=ArxivProvider(min_interval=0),
            crossref=CrossrefProvider(min_interval=0),
            semantic_scholar=SemanticScholarProvider(min_interval=0),
            supplement_threshold=3,
        )

    assert outcome["provider_calls"] == 2
    # 1 arxiv + 3 crossref - 1 duplicate = 3 unique results
    assert len(outcome["results"]) == 3


@pytest.mark.asyncio
async def test_news_cascade_stops_at_baidu_when_sufficient():
    def baidu_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="".join(
                f'<h3><a href="https://news.example/{i}">'
                f"无人机融资 新闻{i}</a></h3>"
                for i in range(4)
            ),
        )

    routes = {
        "www.baidu.com": baidu_handler,
        "news.so.com": lambda request: (_ for _ in ()).throw(
            AssertionError("so360 must not be called")
        ),
        "searxng.test": lambda request: (_ for _ in ()).throw(
            AssertionError("searxng must not be called")
        ),
        "api.gdeltproject.org": lambda request: (_ for _ in ()).throw(
            AssertionError("gdelt must not be called")
        ),
    }

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_routed_handler(routes))
    ) as client:
        outcome = await news_search(
            client,
            "无人机 融资",
            gdelt=None,
            so360=So360NewsProvider(min_interval=0),
            searxng_url="http://searxng.test",
            supplement_threshold=3,
        )

    assert outcome["provider_calls"] == 1
    assert len(outcome["results"]) == 4
    assert outcome["engines_used"] == ["baidu-news"]


@pytest.mark.asyncio
async def test_news_cascade_domestic_first_then_optional_gdelt():
    def baidu_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="")

    def searxng_handler(request: httpx.Request) -> httpx.Response:
        return _searxng_response(
            [
                {
                    "title": "无人机融资 新闻",
                    "url": "https://news.cn/drone",
                    "content": "融资",
                    "engines": ["google"],
                }
            ]
        )

    routes = {
        "www.baidu.com": baidu_handler,
        "news.so.com": httpx.Response(200, text=""),
        "searxng.test": searxng_handler,
        "api.gdeltproject.org": httpx.Response(200, json={"articles": []}),
    }

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_routed_handler(routes))
    ) as client:
        outcome = await news_search(
            client,
            "无人机 融资",
            gdelt=GDELTProvider(min_interval=0),
            so360=So360NewsProvider(min_interval=0),
            searxng_url="http://searxng.test",
            supplement_threshold=3,
        )

    assert outcome["provider_calls"] == 4
    assert outcome["engines_used"] == [
        "baidu-news",
        "so360-news",
        "searxng-news",
        "gdelt",
    ]
    # degrade tiers are still tagged as news for archive attribution
    assert outcome["results"][0]["provider_source_type"] == "news"


@pytest.mark.asyncio
async def test_so360_parses_res_list_blocks():
    html = """
    <li class="full-txt res-list pure-txt" data-from="news"
        data-url="https://www.donews.com/news/detail/8/6670509.html">
      <a hidefocus="true"
         href="https://www.donews.com/news/detail/8/6670509.html">
        <h3 class="g-title js-title">
          <div class="g-txt-inner g-ellipsis">
            固芯能源获亿元级<em>融资</em>,升级为<em>低空经济</em>核心能源服务商
          </div>
        </h3>
        <p class="summary g-ellipsis3">
          8月12日,半固态锂电池量产企业固芯能源完成亿元级融资
        </p>
        <p class="g-linkinfo info b-info">
          <cite class="sitename">DoNews</cite>
          <span class="g-linkinfo-txt g-c-gray time">2026-08-13 22:49</span>
        </p>
      </a>
    </li>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "news.so.com"
        return httpx.Response(200, text=html)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        provider = So360NewsProvider(min_interval=0)
        results = await provider.search(
            client, SearchRequest(query="低空经济 融资")
        )

    assert len(results) == 1
    result = results[0]
    assert "固芯能源" in result.title
    assert result.url == "https://www.donews.com/news/detail/8/6670509.html"
    assert result.fetchable is True
    assert result.provider_source_type == "news"
    assert result.published_at == "2026-08-13 22:49"
    assert result.extra["source"] == "DoNews"


@pytest.mark.asyncio
async def test_gitee_parses_repos_and_issues():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "gitee.com"
        if "/search/repositories" in request.url.path:
            return httpx.Response(
                200,
                json=[
                    {
                        "full_name": "acme/drone-os",
                        "html_url": "https://gitee.com/acme/drone-os",
                        "description": "flight stack",
                        "stargazers_count": 5,
                        "forks_count": 1,
                        "language": "Rust",
                        "updated_at": "2025-06-01T00:00:00+08:00",
                        "fork": False,
                        "owner": {"login": "acme"},
                    }
                ],
            )
        return httpx.Response(
            200,
            json=[
                {
                    "title": "range bug",
                    "html_url": "https://gitee.com/acme/drone-os/issues/1",
                    "body": "range limited",
                    "state": "open",
                    "number": 1,
                    "created_at": "2025-05-01T00:00:00+08:00",
                    "user": {"login": "tester"},
                    "repository": {"full_name": "acme/drone-os"},
                }
            ],
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        provider = GiteeProvider(min_interval=0)
        results = await provider.search(client, SearchRequest(query="drone"))

    assert len(results) == 2
    repo, issue = results
    assert repo.provider_source_type == "software"
    assert repo.evidence_role == "primary"
    assert issue.evidence_role == "supporting"
    assert issue.extra["repo"] == "acme/drone-os"


@pytest.mark.asyncio
async def test_github_degrades_to_gitee_before_searxng():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(403)
        if request.url.host == "gitee.com":
            return httpx.Response(
                200,
                json=[
                    {
                        "full_name": "acme/drone-os",
                        "html_url": "https://gitee.com/acme/drone-os",
                        "description": "",
                        "stargazers_count": 1,
                        "forks_count": 0,
                        "updated_at": "2025-06-01T00:00:00+08:00",
                        "fork": False,
                        "owner": {"login": "acme"},
                    }
                ],
            )
        raise AssertionError("searxng must not be called after gitee hit")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        provider = GitHubProvider(
            searxng_url="http://searxng.test",
            gitee=GiteeProvider(min_interval=0),
            min_interval=0,
        )
        results = await provider.search(client, SearchRequest(query="drone"))

    assert len(results) == 1
    assert results[0].provider == "gitee"
    assert provider.last_calls == 4  # github 2 + gitee 2


def test_search_cache_key_varies_with_params():
    base = {
        "provider": "academic",
        "query": "qwen inference",
        "time_range": None,
        "filters": {},
        "max_results": 10,
    }
    key = search_cache_key(base)
    assert search_cache_key({**base, "max_results": 50}) != key
    assert search_cache_key({**base, "time_range": "week"}) != key
    assert search_cache_key({**base, "query": "other"}) != key
    # deterministic: same params, same key
    assert search_cache_key(base) == key


@pytest.mark.asyncio
async def test_wayback_resolves_dead_url_into_archive_document(cwd):
    task = new_task(cwd)

    async def fetcher(url, init, address):
        if "archive.org/wayback/available" in url:
            return FetchedResponse(
                status=200,
                body=json.dumps(
                    {
                        "archived_snapshots": {
                            "closest": {
                                "url": (
                                    "https://web.archive.org/web/2025/"
                                    "https://example.com/dead"
                                )
                            }
                        }
                    }
                ).encode(),
            )
        if "web.archive.org" in url:
            return FetchedResponse(
                status=200,
                headers={"content-type": "text/html"},
                body=(
                    b"<html><title>Archived</title>"
                    b"<p>historical page content</p></html>"
                ),
            )
        if url == "https://example.com/dead":
            return FetchedResponse(status=404, body=b"gone")
        raise AssertionError(f"unexpected url: {url}")

    async def resolver(hostname: str) -> list[str]:
        return ["93.184.216.34"]

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/dead"],
        config=CrawlConfig(
            retries=0, obey_robots=False, per_host_delay_seconds=0
        ),
        fetcher=fetcher,
        resolver=resolver,
        wayback=True,
    )

    entry = snapshot.entries[0]
    assert entry.status == "complete"
    assert entry.document_id is not None
    document = load_document(cwd, entry.document_id)
    assert document.collection_method == "archive"
    import pathlib

    assert "historical page content" in pathlib.Path(
        cwd / document.text_path
    ).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_wayback_disabled_keeps_skipped_http(cwd):
    task = new_task(cwd)

    async def fetcher(url, init, address):
        assert "archive.org" not in url
        return FetchedResponse(status=404, body=b"gone")

    async def resolver(hostname: str) -> list[str]:
        return ["93.184.216.34"]

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/dead"],
        config=CrawlConfig(
            retries=0, obey_robots=False, per_host_delay_seconds=0
        ),
        fetcher=fetcher,
        resolver=resolver,
        wayback=False,
    )

    assert snapshot.entries[0].status == "skipped_http"


@pytest.mark.asyncio
async def test_gap_driven_vertical_routing_seeds_candidates(cwd):
    """Coverage gap with missing source types triggers deterministic vertical retrieval."""
    from intel_agent.agent import AgentDeps, _coverage_eval_with_backlog
    from intel_agent.audit import audit_task_evidence
    from intel_agent.config import (
        AcademicSearchConfig,
        GitHubSearchConfig,
        NewsSearchConfig,
        SearchConfig,
        Settings,
    )
    from intel_agent.evidence import save_evidence
    from intel_agent.fact import save_fact
    from tests.conftest import fake_judge, make_document

    def github_handler(request: httpx.Request) -> httpx.Response:
        if "/search/repositories" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "full_name": "acme/drone-os",
                            "html_url": "https://github.com/acme/drone-os",
                            "description": "flight stack",
                            "stargazers_count": 1,
                            "forks_count": 0,
                            "updated_at": "2025-06-01T00:00:00Z",
                            "fork": False,
                            "owner": {"login": "acme"},
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"items": []})

    def crossref_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "items": [
                        {
                            "DOI": f"10.1000/{i}",
                            "title": [f"Paper {i}"],
                            "URL": f"https://pub.example/{i}",
                            "published": {"date-parts": [[2025]]},
                            "author": [{"given": "A", "family": "B"}],
                        }
                        for i in range(3)
                    ]
                }
            },
        )

    def so360_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                '<li class="full-txt res-list pure-txt" '
                'data-url="https://news.example/drone">'
                "<h3>无人机新闻</h3></li>"
            ),
        )

    routes = {
        "export.arxiv.org": httpx.Response(200, text=ARXIV_ATOM),
        "api.crossref.org": crossref_handler,
        "api.github.com": github_handler,
        "www.baidu.com": httpx.Response(200, text=""),
        "news.so.com": so360_handler,
    }

    task = new_task(cwd)
    fact = save_fact(cwd, task.id, task.questions[0].id, "无人机飞控系统现状")
    # "other"-typed seed keeps all three vertical types missing from the
    # corpus, so every capability must trigger.
    document = make_document(
        cwd, "无人机飞控系统现状", "https://example.com/a"
    )
    save_evidence(cwd, fact.id, document.id, "supports", fact.statement)
    await audit_task_evidence(cwd, task.id, fake_judge, "test", "fake")

    settings = Settings(
        search=SearchConfig(
            searxng_url=None,
            github=GitHubSearchConfig(rate_limit=0, max_results=5),
            academic=AcademicSearchConfig(
                max_results=5, supplement_threshold=3
            ),
            news=NewsSearchConfig(
                baidu=True, so360=True, gdelt=False, max_results=5
            ),
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_routed_handler(routes))
    ) as client:
        deps = AgentDeps(cwd=cwd, settings=settings, http=client)
        data = await _coverage_eval_with_backlog(deps, task.id)

    assert data.get("vertical_supplement"), data
    added = data["vertical_supplement"]
    assert set(added) <= {"academic", "software", "news"}
    candidates = deps.pending_fetch_candidates
    assert candidates, "vertical candidates must be seeded"
    source_types = {c["source_type"] for c in candidates}
    assert "academic" in source_types
    assert "software" in source_types
    assert "news" in source_types
    assert "vertical_hint" in data

    # Each capability fires at most once per run.
    before = list(candidates)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_routed_handler(routes))
    ) as client:
        deps.http = client
        second = await _coverage_eval_with_backlog(deps, task.id)
    assert second.get("vertical_supplement") is None
    assert deps.pending_fetch_candidates == before


def test_vertical_domains_classify_without_provider_hint():
    from intel_agent.source import source_type_for_domain

    assert source_type_for_domain("github.com") == "software"
    assert source_type_for_domain("gitee.com") == "software"
    assert source_type_for_domain("arxiv.org") == "academic"
    assert source_type_for_domain("semanticscholar.org") == "academic"
    assert source_type_for_domain("doi.org") == "academic"
    assert source_type_for_domain("example.com") == "other"
