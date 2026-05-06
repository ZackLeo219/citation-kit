"""Crossref REST API adapter (works with raw JSON or `habanero` output).

Crossref returns:
    {
      "message": {
        "items": [
          {
            "DOI": "10.x/y",
            "title": ["..."],
            "abstract": "<jats:p>...</jats:p>",
            "author": [{"given": "...", "family": "..."}],
            "container-title": ["Nature"],
            "issued": {"date-parts": [[2024]]},
            "URL": "..."
          }
        ]
      }
    }

We accept the full response (with `message` wrapper) or the unwrapped `items`.
DOI is always present in Crossref → cite_id is always `doi:...`.
"""
from __future__ import annotations

import re
from typing import Any

from ..canonicalize import canonical_url_for, normalize_doi, pick_cite_id
from ..types import CitationRecord, ParseResult
from .base import build_snippet, ensure_authors_tuple, safe_int


_TAG_RE = re.compile(r"<[^>]+>")  # strip JATS XML tags from abstract


def parse(raw_response: dict[str, Any] | list[dict[str, Any]]) -> ParseResult:
    items = _extract_items(raw_response)
    records: list[CitationRecord] = []
    snippets: list[str] = []
    for it in items:
        rec = _parse_one(it)
        if rec is None:
            continue
        records.append(rec)
        snippets.append(build_snippet(rec))
    return ParseResult(records=records, snippets=snippets)


def _extract_items(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        msg = raw.get("message")
        if isinstance(msg, dict):
            items = msg.get("items")
            if items is not None:
                return list(items)
            # single-item GET (DOI lookup) → message IS the item
            if "DOI" in msg:
                return [msg]
        if "items" in raw:
            return list(raw["items"])
        if "DOI" in raw:
            return [raw]
    return []


def _parse_one(it: dict[str, Any]) -> CitationRecord | None:
    doi = normalize_doi(it.get("DOI", ""))
    if not doi:
        return None
    identifiers = {"doi": doi}
    if it.get("URL"):
        identifiers["url"] = it["URL"]
    try:
        cite_id = pick_cite_id(identifiers)
    except ValueError:
        return None
    titles = it.get("title") or []
    title = (titles[0] if titles else "").strip()
    container = it.get("container-title") or []
    venue = (container[0] if container else "").strip()
    issued = it.get("issued") or it.get("published-print") or it.get("published-online") or {}
    date_parts = (issued.get("date-parts") or [[None]])[0]
    year = safe_int(date_parts[0]) if date_parts else None
    abstract_raw = it.get("abstract") or ""
    abstract = _TAG_RE.sub("", abstract_raw).strip() if abstract_raw else ""
    return CitationRecord(
        cite_id=cite_id,
        title=title,
        url=canonical_url_for(identifiers),
        abstract=abstract,
        authors=ensure_authors_tuple(it.get("author")),
        year=year,
        venue=venue,
        source_tool="crossref",
        identifiers=identifiers,
        raw=it,
    )
