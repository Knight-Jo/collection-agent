"""Search query analysis tests."""

import httpx
import pytest

from intel_agent.models import IntelError
from intel_agent.search import (
    MAX_SEARCH_RESPONSE_BYTES,
    _result,
    bing_search,
    strip_tags,
    web_search,
)
from intel_agent.search_queries import (
    authoritative_variants,
    extract_keywords,
    is_broad_query,
    is_semantic_duplicate,
    query_matrix,
    relevance_tokens,
    tokenize_query,
)


def test_tokenize_query():
    tokens = tokenize_query("华为 2026年 昇腾AI芯片 进展")
    assert "昇腾" in tokens
    assert "芯片" in tokens
    assert "2026" in tokens


def test_relevance_tokens_drop_bare_years():
    tokens = tokenize_query("华为 2026年 昇腾AI芯片 进展")
    assert relevance_tokens("华为 2026年 昇腾AI芯片 进展") == [
        token for token in tokens if token != "2026"
    ]
    assert "2026" not in relevance_tokens("华为 2026年 昇腾AI芯片 进展")
    assert "昇腾" in relevance_tokens("华为 2026年 昇腾AI芯片 进展")


def test_tokenize_query_splits_long_compound_segments():
    tokens = tokenize_query("低空经济投资与融资趋势及亿航智能商业化进展")
    assert "低空" in tokens
    assert "趋势" in tokens
    assert "亿航智能" in tokens
    assert "低空经济投资与融资趋势及亿航智能商业化进展" not in tokens


def test_broad_query_detection():
    broad, reason = is_broad_query("低空经济")
    assert broad
    assert reason is not None
    broad, _ = is_broad_query("低空经济 亿航智能 2026 订单")
    assert not broad
    broad, _ = is_broad_query("hi")
    assert broad


def test_semantic_duplicate():
    assert is_semantic_duplicate(
        "亿航智能 2026 年 订单 金额", "亿航智能 2026 订单 规模 金额"
    )
    assert not is_semantic_duplicate("亿航智能 订单", "低空经济 政策")


def test_extract_keywords():
    kw = extract_keywords("问题1：低空经济2026年投资规模如何")
    assert "低空经济2026年投资规模" in kw or "低空经济" in kw


def test_authoritative_variants():
    variants = authoritative_variants("低空经济 亿航智能")
    assert any("site:gov.cn" in v for v in variants)


def test_search_result_decodes_url_entities():
    result = _result(
        "test",
        "report",
        "https://example.com/report.pdf?a=1&amp;b=2",
        "",
        "company report",
    )

    assert result is not None
    assert result.url == "https://example.com/report.pdf?a=1&b=2"


def test_strip_tags_decodes_standard_html_entities():
    assert strip_tags("<p>A&nbsp;&amp;&#x20AC;&#39;</p>") == "A &€'"


async def test_bing_search_uses_direct_endpoint_and_cjk_language():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.bing.com"
        assert request.url.params["setlang"] == "zh-CN"
        assert request.headers["accept-language"].startswith("zh-CN")
        return httpx.Response(
            200,
            text=(
                '<li class="b_algo"><h2><a href="https://www.gov.cn/policy">'
                "低空经济政策</a></h2><p>国家层面政策原文</p></li>"
            ),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        results = await bing_search(client, "低空经济 政策", 5)

    assert len(results) == 1
    assert results[0].url == "https://www.gov.cn/policy"


@pytest.mark.asyncio
async def test_search_response_is_rejected_before_html_parsing():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"x" * (MAX_SEARCH_RESPONSE_BYTES + 1)
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(IntelError) as error:
            await bing_search(client, "test", 5)

    assert error.value.code == "RESPONSE_TOO_LARGE"


@pytest.mark.asyncio
async def test_web_search_merges_ai_native_results_and_reports_degraded(
    monkeypatch,
):
    async def ok(_client, _query, _count):
        return [
            _result(
                "bing",
                "Topic result",
                "https://example.com/topic",
                "topic",
                "topic",
            )
        ]

    async def failed(_client, _query, _count):
        raise RuntimeError("upstream unavailable")

    monkeypatch.setattr("intel_agent.search.bing_search", ok)
    monkeypatch.setattr("intel_agent.search.baidu_search", failed)
    monkeypatch.setattr("intel_agent.search.baidu_news_search", ok)

    class Provider:
        metadata = type("Metadata", (), {"name": "exa"})

        async def search(self, _client, request):
            return [
                _result(
                    "exa",
                    "Topic result",
                    "https://www.example.com/topic#section",
                    request.query,
                    request.query,
                )
            ]

    result = await web_search(
        "topic",
        max_results=5,
        searxng_url=None,
        ai_native_providers=[Provider()],
    )

    assert len(result["results"]) == 1
    assert result["degraded"] == ["baidu"]


def test_query_plan_includes_document_and_media_discovery():
    variants = [
        query
        for queries in query_matrix("低空经济", "亿航智能订单情况").values()
        for query in queries
    ]

    assert any("filetype:pdf" in variant for variant in variants)
    assert any("filetype:docx" in variant for variant in variants)
    assert any("filetype:png" in variant for variant in variants)
    assert any("filetype:mp3" in variant for variant in variants)
    assert any("filetype:mp4" in variant for variant in variants)


def test_query_matrix_has_six_slots_with_expected_content():
    matrix = query_matrix("低空经济", "2026年低空经济投资与融资趋势")

    assert set(matrix) == {
        "discovery",
        "primary",
        "verify",
        "structured",
        "attachment",
        "adversarial",
    }
    assert any("site:" in query for query in matrix["primary"])
    assert any(
        "filetype:" in query
        for query in matrix["attachment"] + matrix["structured"]
    )
    assert any("争议" in query for query in matrix["adversarial"])


def test_query_matrix_adds_english_company_and_policy_queries():
    company = query_matrix("低空经济", "EHang 亿航智能商业化进展与订单情况")
    assert any("ehang" in query.lower() for query in company["discovery"])
    assert any("官网" in query for query in company["primary"])

    policy = query_matrix("低空经济", "低空经济政策与监管环境现状")
    assert any("site:gov.cn" in query for query in policy["primary"])
