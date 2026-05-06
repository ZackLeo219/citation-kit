"""Tavily Search API adapter.

Tavily returns:
    {
      "query": "...",
      "results": [
        {"title": "...", "url": "...", "content": "...", "score": 0.x, ...}
      ],
      ...
    }

We only consume `results[]`. URL is the only stable identifier (Tavily doesn't
expose DOI/PMID even for academic results), so cite_id is `url:<hash>`.
"""
from __future__ import annotations

from typing import Any

from ..canonicalize import canonical_url_for, pick_cite_id
from ..types import CitationRecord, ParseResult
from .base import build_snippet


def parse(raw_response: dict[str, Any]) -> ParseResult:
    results = raw_response.get("results") or []
    records: list[CitationRecord] = []
    snippets: list[str] = []
    for r in results:
        url = (r.get("url") or "").strip()
        if not url:
            continue
        identifiers = {"url": url}
        try:
            cite_id = pick_cite_id(identifiers)
        except ValueError:
            continue
        rec = CitationRecord(
            cite_id=cite_id,
            title=(r.get("title") or "").strip(),
            url=canonical_url_for(identifiers, fallback_url=url),
            abstract=(r.get("content") or "").strip(),
            source_tool="tavily",
            identifiers=identifiers,
            raw=r,
        )
        records.append(rec)
        snippets.append(build_snippet(rec))
    return ParseResult(records=records, snippets=snippets)
