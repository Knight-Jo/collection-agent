"""Search query analysis tests."""

from intel_agent.search import (
    _result,
    authoritative_variants,
    build_query_variants,
    extract_keywords,
    industry_terms,
    is_broad_query,
    is_semantic_duplicate,
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


def test_build_query_variants():
    variants = build_query_variants("低空经济", "2026年低空经济投资规模如何")
    assert len(variants) >= 3
    assert any("官方 公告" in v for v in variants)


def test_industry_terms_injection():
    extra = industry_terms("低空经济的融资轮次如何")
    assert any("融资 轮次 金额" in v for v in extra)
    extra = industry_terms("低空经济的技术进展如何")
    assert any("突破 技术" in v for v in extra)


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


def test_query_plan_includes_document_and_media_discovery():
    variants = build_query_variants("低空经济", "亿航智能订单情况")

    assert any("filetype:pdf" in variant for variant in variants)
    assert any("filetype:docx" in variant for variant in variants)
    assert any("filetype:png" in variant for variant in variants)
    assert any("filetype:mp3" in variant for variant in variants)
    assert any("filetype:mp4" in variant for variant in variants)
