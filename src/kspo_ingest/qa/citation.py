"""Citation parsing — extract [N] references from LLM answer and map to sources.

Ported from bari-chatbot/src/generation/citation.py, adapted for web page sources.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Citation:
    index: int
    source_url: str
    title: str | None
    domain_host: str | None


def parse_citations(
    text: str, sources: list[dict]
) -> tuple[str, list[Citation]]:
    """Extract [1][2]... references from text and map to source list."""
    refs = re.findall(r"\[(\d+)\]", text)
    seen: set[int] = set()
    citations: list[Citation] = []
    for ref in refs:
        idx = int(ref) - 1
        if idx < 0 or idx >= len(sources) or idx in seen:
            continue
        seen.add(idx)
        src = sources[idx]
        citations.append(Citation(
            index=int(ref),
            source_url=src.get("source", ""),
            title=src.get("title"),
            domain_host=src.get("domain_host"),
        ))
    return text, citations
