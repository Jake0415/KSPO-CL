from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=4)
def get_encoder(name: str = "cl100k_base"):
    """tiktoken encoder cache. text-embedding-3-large는 cl100k_base 사용."""
    import tiktoken

    return tiktoken.get_encoding(name)


def count_tokens(text: str, encoder_name: str = "cl100k_base") -> int:
    if not text:
        return 0
    return len(get_encoder(encoder_name).encode(text))
