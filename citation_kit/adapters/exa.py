"""Exa (formerly Metaphor) Search API adapter.

Exa returns:
    {
      "results": [
        {
          "title": "...",
          "url": "...",
          "publishedDate": "2024-...",
          "author": "...",
          "id": "...",            # Exa's internal id
          "text": "..."           # full content if `contents=true` was passed
        }
      ]
    }

URL is the canonical identifier; published date gives us year.
"""
from __future__ import annotations

from typing import Any

from ..canonicalize import canonical_url_for, pick_cite_id
from ..types import CitationRecord, ParseResult
from .base import build_snippet, ensure_authors_tuple, safe_int


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
        published = r.get("publishedDate") or ""
        year = safe_int(published[:4]) if published else None
        rec = CitationRecord(
            cite_id=cite_id,
            title=(r.get("title") or "").strip(),
            url=canonical_url_for(identifiers, fallback_url=url),
            abstract=(r.get("text") or r.get("snippet") or "").strip(),
            authors=ensure_authors_tuple(r.get("author")),
            year=year,
            source_tool="exa",
            identifiers=identifiers,
            raw=r,
        )
        records.append(rec)
        snippets.append(build_snippet(rec))
    return ParseResult(records=records, snippets=snippets)
