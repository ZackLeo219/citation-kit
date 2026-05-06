"""Brave Search API adapter.

Brave returns (web search):
    {
      "web": {
        "results": [
          {
            "title": "...",
            "url": "...",
            "description": "...",
            "page_age": "2024-...",
            "language": "en"
          }
        ]
      }
    }

URL-only identification. We accept either the full response (with `web` wrapper)
or just the inner `results` array, since some users post-process before calling.
"""
from __future__ import annotations

from typing import Any

from ..canonicalize import canonical_url_for, pick_cite_id
from ..types import CitationRecord, ParseResult
from .base import build_snippet, safe_int


def parse(raw_response: dict[str, Any]) -> ParseResult:
    if "web" in raw_response:
        results = (raw_response["web"] or {}).get("results") or []
    else:
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
        page_age = r.get("page_age") or ""
        year = safe_int(page_age[:4]) if page_age else None
        rec = CitationRecord(
            cite_id=cite_id,
            title=(r.get("title") or "").strip(),
            url=canonical_url_for(identifiers, fallback_url=url),
            abstract=(r.get("description") or "").strip(),
            year=year,
            source_tool="brave",
            identifiers=identifiers,
            raw=r,
        )
        records.append(rec)
        snippets.append(build_snippet(rec))
    return ParseResult(records=records, snippets=snippets)
