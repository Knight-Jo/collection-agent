"""Search query analysis and variant generation."""

from __future__ import annotations

import re

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

_LONG_SEGMENT_LEN = 8
_LONG_SEGMENT_SPLIT_RE = re.compile(
    "|".join(sorted(GENERIC_TERMS | STOP_WORDS, key=len, reverse=True))
)


def tokenize_query(query: str) -> list[str]:
    """Extract significant English, Chinese, and year tokens."""
    tokens: set[str] = set()
    for match in re.findall(r"[a-zA-Z][a-zA-Z0-9-]{1,}", query):
        word = match.lower()
        if word not in STOP_WORDS and len(word) >= 3:
            tokens.add(word)
    for segment in re.split(r"[^\u4e00-\u9fa5]+", query):
        if len(segment) < 2 or segment in STOP_WORDS:
            continue
        if len(segment) > _LONG_SEGMENT_LEN:
            # Long CJK runs are compound phrases; one whole-phrase token
            # never matches result titles/snippets (run 011: intel_plan
            # merged topic+questions into a 22-char token and crawl
            # seeding died). Split on generic/stop terms so short,
            # searchable tokens survive.
            tokens.update(
                chunk
                for chunk in _LONG_SEGMENT_SPLIT_RE.split(segment)
                if len(chunk) >= 2 and chunk not in STOP_WORDS
            )
        elif segment not in GENERIC_TERMS:
            tokens.add(segment)
    for match in re.findall(r"\d{4}", query):
        tokens.add(match)
    return list(tokens)


def relevance_tokens(query: str) -> list[str]:
    """Tokens for relevance scoring: tokenize_query minus bare year tokens.

    A four-digit year matches any URL path or timestamp (e.g. /2026/08/03/),
    so counting it inflates the relevance of otherwise unrelated links and
    search results (run 008: 16 CCDI video pages seeded via year-in-URL).
    """
    return [
        token
        for token in tokenize_query(query)
        if not re.fullmatch(r"\d{4}", token)
    ]


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


QUERY_MATRIX_SLOTS = (
    "discovery",
    "primary",
    "verify",
    "structured",
    "attachment",
    "adversarial",
)

# Budget split by phase (run 014): discovery 40%, verification 40%,
# adversarial + recency 20%.
QUERY_MATRIX_PHASE: dict[str, str] = {
    "discovery": "discovery",
    "primary": "verify",
    "verify": "verify",
    "structured": "verify",
    "attachment": "verify",
    "adversarial": "adversarial",
}
QUERY_MATRIX_PHASE_BUDGET = {
    "discovery": 0.4,
    "verify": 0.4,
    "adversarial": 0.2,
}


def query_matrix(topic: str, question: str) -> dict[str, list[str]]:
    """Deterministic six-slot query matrix for one question (run 014).

    Slots: broad discovery, first-party sources, independent verification,
    structured data, attachments, adversarial/controversy. English entity
    queries are added to discovery when the question carries Latin tokens;
    company questions get an IR/regulatory primary query, policy questions
    get the authoritative original text.
    """
    keywords = extract_keywords(question)
    english_terms = " ".join(
        re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", question)
    ).lower()
    slots: dict[str, list[str]] = {
        "discovery": [f"{topic} {keywords}", f"{keywords} 最新 数据"],
        "primary": authoritative_variants(question),
        "verify": [
            f"{keywords} 官方 公告",
            f"{keywords} 同比 增长 统计",
        ],
        "structured": [f"{keywords} filetype:xlsx OR filetype:pptx"],
        # Attachment queries cover the full media matrix so the crawl can
        # discover PDFs, Office files, images, audio and video (run 017).
        "attachment": [
            f"{keywords} filetype:pdf",
            f"{keywords} filetype:docx",
            f"{keywords} filetype:xlsx OR filetype:pptx",
            f"{keywords} filetype:png OR filetype:jpg OR filetype:webp",
            f"{keywords} filetype:mp3 OR filetype:wav OR filetype:m4a",
            f"{keywords} filetype:mp4 OR filetype:webm OR filetype:mov",
        ],
        "adversarial": [f"{keywords} 争议 质疑 负面"],
    }
    if english_terms:
        slots["discovery"].append(f"{english_terms} {keywords}")
    if re.search(r"投资|融资|商业化|订单|营收|公司|企业", question):
        slots["primary"].append(f"{keywords} 官网 OR 投资者关系 OR 财报")
    if re.search(r"政策|法规|条例|监管|标准", question):
        slots["primary"].append(f"site:gov.cn {keywords}")
    slots = {
        slot: list(dict.fromkeys(queries)) for slot, queries in slots.items()
    }
    return {
        slot: [query for query in queries if len(query.split()) >= 2]
        for slot, queries in slots.items()
    }
