"""Domain source-role classification tests (run 013)."""

from intel_agent.source import classify_domain, source_type_for_domain


def test_ir_subdomains_are_first_party_official():
    assert classify_domain("ir.ehang.com") == "official"
    assert source_type_for_domain("ir.ehang.com") == "official"
    assert source_type_for_domain("investor.example.com") == "other"


def test_forum_and_community_domains_are_social():
    for hostname in (
        "etbbs.com",
        "xueqiu.com",
        "guba.eastmoney.com",
        "tieba.baidu.com",
        "www.zhihu.com",
    ):
        assert source_type_for_domain(hostname) == "social", hostname


def test_government_and_news_roles_are_preserved():
    assert source_type_for_domain("www.gov.cn") == "government"
    assert source_type_for_domain("ndrc.gov.cn") == "government"
    assert source_type_for_domain("news.cn") == "news"
    assert source_type_for_domain("caixin.com") == "news"
    assert source_type_for_domain("university.edu") == "academic"
