"""Serper.dev — Google Search via SERP API.

Serper returns:
    {
      "searchParameters": {...},
      "organic": [
        {"title": "...", "link": "...", "snippet": "...", "position": 1, ...}
      ],
      "knowledgeGraph": {...},
      "answerBox": {...},
      ...
    }

We currently only consume `organic` (most reliable URL/snippet pairs).
"""
from __future__ import annotations

from typing import Any

from ..canonicalize import canonical_url_for, pick_cite_id
from ..types import CitationRecord, ParseResult
from .base import build_snippet, safe_int


def parse(raw_response: dict[str, Any]) -> ParseResult:
    results = raw_response.get("organic") or []
    records: list[CitationRecord] = []
    snippets: list[str] = []
    for r in results:
        url = (r.get("link") or r.get("url") or "").strip()
        if not url:
            continue
        identifiers = {"url": url}
        try:
            cite_id = pick_cite_id(identifiers)
        except ValueError:
            continue
        date = r.get("date") or ""
        year = safe_int(date[:4]) if date else None
        rec = CitationRecord(
            cite_id=cite_id,
            title=(r.get("title") or "").strip(),
            url=canonical_url_for(identifiers, fallback_url=url),
            abstract=(r.get("snippet") or "").strip(),
            year=year,
            source_tool="serper",
            identifiers=identifiers,
            raw=r,
        )
        records.append(rec)
        snippets.append(build_snippet(rec))
    return ParseResult(records=records, snippets=snippets)
