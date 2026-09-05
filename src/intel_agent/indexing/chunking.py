"""Structure-first chunking with exact block spans (spec §10.1)."""

from __future__ import annotations

import hashlib
import re

from ..contracts.documents import (
    BlockSpan,
    Chunk,
    EvidenceBlock,
    NormalizedDocument,
)
from ..runtime import profile_id

SEPARATOR = "\n\n"
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？.!?])\s*")


def chunk_profile_id(config: dict) -> str:
    return profile_id(config)


def chunk_document(
    document: NormalizedDocument,
    chunk_config: dict,
    counter,
) -> list[Chunk]:
    """Chunk a document, preserving exact per-block spans in chunk text."""
    target = chunk_config.get("target_tokens", 600)
    hard = chunk_config.get("hard_limit_tokens", 900)
    pid = chunk_profile_id(chunk_config)
    chunks: list[Chunk] = []
    ordinal = 1
    buffer: list[tuple[EvidenceBlock, int, int]] = []
    buffer_tokens = 0

    def flush() -> None:
        nonlocal ordinal
        if buffer:
            chunks.append(_build(document, pid, ordinal, buffer))
            ordinal += 1

    for block in document.blocks:
        block_tokens = counter.count(block.text)
        if block_tokens > hard:
            if buffer:
                flush()
                buffer = []
                buffer_tokens = 0
            for piece_start, piece_end in _split_spans(
                block.text, counter, hard
            ):
                chunks.append(
                    _build(document, pid, ordinal, [(block, piece_start,
                                                     piece_end)])
                )
                ordinal += 1
            continue
        if buffer and buffer_tokens + block_tokens > hard:
            flush()
            buffer = []
            buffer_tokens = 0
        buffer.append((block, 0, len(block.text)))
        buffer_tokens += block_tokens
        if buffer_tokens >= target:
            flush()
            buffer = []
            buffer_tokens = 0
    flush()
    return chunks


def _build(document, pid, ordinal, spans) -> Chunk:
    parts = [block.text[start:end] for block, start, end in spans]
    text = SEPARATOR.join(parts)
    locators = [block.locator for block, _, _ in spans]
    chunk_id = f"chk-{hashlib.sha256(f'{document.artifact_id}\n{pid}\n{ordinal}'.encode()).hexdigest()[:24]}"
    return Chunk(
        chunk_id=chunk_id,
        artifact_id=document.artifact_id,
        document_id=document.document_id,
        revision_id=document.revision_id,
        text=text,
        block_spans=[
            BlockSpan(block_id=block.block_id, char_start=start,
                      char_end=end)
            for block, start, end in spans
        ],
        locators=locators,
        chunk_profile_id=pid,
        ordinal=ordinal,
    )


def _split_spans(text: str, counter, hard: int) -> list[tuple[int, int]]:
    """Split an oversized block into token-bounded char spans."""
    sentences = [
        s for s in _SENTENCE_SPLIT.split(text) if s
    ] or [text]
    spans: list[tuple[int, int]] = []
    offset = 0
    current_start = 0
    current_tokens = 0
    for sentence in sentences:
        tokens = counter.count(sentence)
        if current_tokens + tokens > hard and current_tokens > 0:
            spans.append((current_start, offset))
            current_start = offset
            current_tokens = 0
        current_tokens += tokens
        offset += len(sentence)
    if offset > current_start:
        spans.append((current_start, offset))
    return spans
