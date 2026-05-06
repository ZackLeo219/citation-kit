"""Semantic Scholar Graph API adapter.

S2 returns:
    {
      "data": [
        {
          "paperId": "abc123...",
          "title": "...",
          "abstract": "...",
          "year": 2024,
          "authors": [{"authorId": "...", "name": "Last F"}],
          "venue": "...",
          "externalIds": {"DOI": "10.x/y", "PubMed": "12345", "ArXiv": "2401.123"},
          "url": "..."
        }
      ]
    }

S2 covers cross-disciplinary literature with rich `externalIds` — usually we
can resolve to DOI or PMID for canonical cite_id, falling back to S2 paperId.
"""
from __future__ import annotations

from typing import Any

from ..canonicalize import (
    canonical_url_for,
    normalize_arxiv_id,
    normalize_doi,
    normalize_pmid,
    pick_cite_id,
)
from ..types import CitationRecord, ParseResult
from .base import build_snippet, ensure_authors_tuple, safe_int


def parse(raw_response: dict[str, Any] | list[dict[str, Any]]) -> ParseResult:
    if isinstance(raw_response, list):
        papers = raw_response
    else:
        papers = raw_response.get("data") or raw_response.get("papers") or []
    records: list[CitationRecord] = []
    snippets: list[str] = []
    for p in papers:
        rec = _parse_one(p)
        if rec is None:
            continue
        records.append(rec)
        snippets.append(build_snippet(rec))
    return ParseResult(records=records, snippets=snippets)


def _parse_one(p: dict[str, Any]) -> CitationRecord | None:
    ext = p.get("externalIds") or {}
    identifiers: dict[str, str] = {}
    doi = normalize_doi(ext.get("DOI", ""))
    if doi:
        identifiers["doi"] = doi
    pmid = normalize_pmid(ext.get("PubMed", ""))
    if pmid:
        identifiers["pmid"] = pmid
    arxiv = normalize_arxiv_id(ext.get("ArXiv", ""))
    if arxiv:
        identifiers["arxiv"] = arxiv
    if p.get("paperId"):
        identifiers["s2"] = str(p["paperId"])
    if p.get("url"):
        identifiers["url"] = p["url"]
    if not identifiers:
        return None
    try:
        cite_id = pick_cite_id(identifiers)
    except ValueError:
        return None
    return CitationRecord(
        cite_id=cite_id,
        title=(p.get("title") or "").strip(),
        url=canonical_url_for(identifiers, fallback_url=p.get("url") or ""),
        abstract=(p.get("abstract") or "").strip(),
        authors=ensure_authors_tuple(p.get("authors")),
        year=safe_int(p.get("year")),
        venue=(p.get("venue") or "").strip(),
        source_tool="semantic_scholar",
        identifiers=identifiers,
        raw=p,
    )
