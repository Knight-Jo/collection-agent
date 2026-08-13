"""Search query analysis and variant generation."""

from __future__ import annotations

import re
from datetime import date

PUNCT_RE = re.compile(r"[？?。.!！,，;；:：\"'“”‘’()（）]")
STOP_TERMS = {
    "如何",
    "怎样",
    "怎么",
    "什么",
    "为什么",
    "哪些",
    "多少",
    "进展",
    "情况",
    "现状",
    "未来",
    "最新",
    "官方",
    "公告",
    "争议",
    "质疑",
    "同比",
    "增长",
    "统计",
    "里程碑",
    "突破",
    "技术",
}
GENERIC_TERMS = {
    "投资",
    "融资",
    "商业化",
    "产业",
    "发展",
    "市场",
    "政策",
    "法规",
    "经济",
    "进展",
    "影响",
    "情况",
    "现状",
    "相关",
    "最新",
    "数据",
    "公告",
    "官方",
    "标准",
    "技术",
    "规模",
    "企业",
}
STOP_WORDS = STOP_TERMS | {
    "是否",
    "有没有",
    "是否已",
    "目前",
    "中国",
    "2026",
    "2025",
    "年",
    "和",
    "与",
    "及",
    "的",
    "了",
    "在",
    "对",
    "其",
    "the",
    "a",
    "an",
    "of",
    "for",
    "to",
    "in",
    "on",
}


def tokenize_query(query: str) -> list[str]:
    """Extract significant English, Chinese, and year tokens."""
    tokens: set[str] = set()
    for match in re.findall(r"[a-zA-Z][a-zA-Z0-9-]{1,}", query):
        word = match.lower()
        if word not in STOP_WORDS and len(word) >= 3:
            tokens.add(word)
    for segment in re.split(r"[^\u4e00-\u9fa5]+", query):
        if (
            len(segment) >= 2
            and segment not in STOP_WORDS
            and segment not in GENERIC_TERMS
        ):
            tokens.add(segment)
    for match in re.findall(r"\d{4}", query):
        tokens.add(match)
    return list(tokens)


def is_broad_query(query: str) -> tuple[bool, str | None]:
    """Return whether a query lacks enough identifying terms."""
    text = query.strip()
    if len(text) < 4:
        return True, "查询过短"
    tokens = [
        token
        for token in tokenize_query(text)
        if not re.fullmatch(r"\d{4}", token)
    ]
    if len(tokens) < 2:
        return (
            True,
            f"仅 {len(tokens)} 个实体词（如“{text}”），建议加限定词：年份/公司/机构/具体指标",
        )
    return False, None


def query_similarity(first: str, second: str) -> float:
    """Measure overlap relative to the shorter token list."""
    first_tokens = tokenize_query(first)
    second_tokens = tokenize_query(second)
    if not first_tokens or not second_tokens:
        return 0.0
    overlap = sum(1 for token in first_tokens if token in second_tokens)
    return overlap / min(len(first_tokens), len(second_tokens))


def is_semantic_duplicate(first: str, second: str) -> bool:
    """Detect materially duplicate queries after generic terms are removed."""
    first_tokens = [
        token for token in tokenize_query(first) if token not in GENERIC_TERMS
    ]
    second_tokens = [
        token for token in tokenize_query(second) if token not in GENERIC_TERMS
    ]
    if len(first_tokens) < 3 or len(second_tokens) < 3:
        return False
    overlap = sum(1 for token in first_tokens if token in second_tokens)
    return overlap / min(len(first_tokens), len(second_tokens)) >= 0.6


def authoritative_variants(query: str) -> list[str]:
    """Build queries restricted to established authoritative domains."""
    keywords = extract_keywords(query, 12)
    return [
        variant
        for variant in [
            f"site:gov.cn {keywords}",
            f"site:ndrc.gov.cn {keywords}",
            f"site:news.cn {keywords}",
            f"site:people.com.cn {keywords}",
        ]
        if len(variant.split()) >= 2
    ]


def industry_terms(question: str) -> list[str]:
    """Add domain-specific search phrases inferred from a question."""
    keywords = extract_keywords(question, 12)
    variants: list[str] = []
    if re.search(r"投资|融资|商业化|市场|估值|商业", question):
        variants += [
            f"{keywords} 融资 轮次 金额",
            f"{keywords} 基金 投资 规模",
            f"{keywords} IPO 上市 订单",
        ]
    if re.search(r"政策|法规|条例|监管|标准", question):
        variants += [f"{keywords} 条例 意见稿", f"{keywords} 标准 体系"]
    if re.search(r"进展|发展|突破|技术", question):
        variants += [f"{keywords} 里程碑 进展", f"{keywords} 突破 技术"]
    return variants


def extract_keywords(question: str, max_len: int = 14) -> str:
    """Remove question prefixes and generic punctuation from a query."""
    keywords = re.sub(
        r"^(q\d*[:：\s]*|问题\d*[:：\s]*)", "", question, flags=re.I
    )
    terms = [
        term
        for term in re.sub(
            r"[？?。.!！,，;；:：\"'“”‘’()（）【】]", " ", keywords
        ).split()
        if len(term) >= 2 and term not in STOP_TERMS
    ]
    result = " ".join(terms)
    return result[:max_len] or question[:max_len]


def build_query_variants(topic: str, question: str) -> list[str]:
    """Build general, current, authoritative, and industry query variants."""
    keywords = extract_keywords(question)
    year = date.today().year
    variants = [
        f"{topic} {keywords}",
        f"{keywords} {year}",
        f"{keywords} 最新 数据",
        f"{keywords} 官方 公告",
        f"{keywords} 争议 质疑",
        f"{keywords} 同比 增长 统计",
        f"EN:{keywords} {year} official update（将关键词译为英文后搜索）",
        f"{keywords} filetype:pdf",
        f"{keywords} filetype:docx",
        f"{keywords} filetype:xlsx OR filetype:pptx",
        f"{keywords} filetype:png OR filetype:jpg OR filetype:webp",
        f"{keywords} filetype:mp3 OR filetype:wav OR filetype:m4a",
        f"{keywords} filetype:mp4 OR filetype:webm OR filetype:mov",
    ]
    variants.extend(industry_terms(question))
    return [
        variant
        for variant in variants
        if len(variant.split()) >= 2 or variant.startswith("EN:")
    ]
