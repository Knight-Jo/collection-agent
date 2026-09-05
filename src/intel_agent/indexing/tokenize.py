"""Token counting backed by a real tokenizer (spec §5, §11)."""

from __future__ import annotations


class TiktokenCounter:
    """Counts tokens with a pinned tiktoken encoding.

    Binds a concrete model/tokenizer identity so budget guarantees are not
    based on character-count guesses.
    """

    def __init__(
        self,
        encoding_name: str = "cl100k_base",
        model_id: str = "gpt-4",
    ) -> None:
        import tiktoken

        self._encoding = tiktoken.get_encoding(encoding_name)
        self.model_id = model_id
        self.tokenizer_version = encoding_name

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text))
