"""Europe PMC adapter — biomedical literature (PubMed superset + preprints + full-text).

Returns:
    {
      "resultList": {
        "result": [
          {
            "id": "12345",          # may be PMID, PMCID, or DOI
            "source": "MED" | "PMC" | "PPR" | ...,
            "pmid": "12345",
            "pmcid": "PMC123",
            "doi": "10.x/y",
            "title": "...",
            "abstractText": "...",
            "authorString": "Last F, Last F.",
            "journalTitle": "...",
            "pubYear": "2024",
            "fullTextUrlList": {"fullTextUrl": [{"url": "..."}, ...]}
          }
        ]
      }
    }

Source codes: MED = PubMed, PMC = PubMed Central full text, PPR = preprint
(bioRxiv/medRxiv/etc.). All produce the same record shape after normalization.
"""
from __future__ import annotations

from typing import Any

from ..canonicalize import canonical_url_for, normalize_doi, normalize_pmid, pick_cite_id
from ..types import CitationRecord, ParseResult
from .base import build_snippet, safe_int


def parse(raw_response: dict[str, Any] | list[dict[str, Any]]) -> ParseResult:
    items = _extract(raw_response)
    records: list[CitationRecord] = []
    snippets: list[str] = []
    for it in items:
        rec = _parse_one(it)
        if rec is None:
            continue
        records.append(rec)
        snippets.append(build_snippet(rec))
    return ParseResult(records=records, snippets=snippets)


def _extract(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        rl = raw.get("resultList")
        if isinstance(rl, dict):
            return list(rl.get("result") or [])
        if "result" in raw:
            return list(raw["result"])
    return []


def _parse_one(it: dict[str, Any]) -> CitationRecord | None:
    doi = normalize_doi(it.get("doi", ""))
    pmid = normalize_pmid(it.get("pmid", ""))
    identifiers: dict[str, str] = {}
    if doi:
        identifiers["doi"] = doi
    if pmid:
        identifiers["pmid"] = pmid
    # Try fullTextUrlList for fallback URL
    full_url = ""
    fulltext = (it.get("fullTextUrlList") or {}).get("fullTextUrl") or []
    if fulltext:
        full_url = fulltext[0].get("url", "")
    if full_url and "url" not in identifiers:
        identifiers["url"] = full_url
    if not identifiers:
        return None
    try:
        cite_id = pick_cite_id(identifiers)
    except ValueError:
        return None
    # Authors as comma-separated string in `authorString`
    author_str = (it.get("authorString") or "").rstrip(".").strip()
    authors = tuple(a.strip() for a in author_str.split(",") if a.strip()) if author_str else ()
    return CitationRecord(
        cite_id=cite_id,
        title=(it.get("title") or "").strip(),
        url=canonical_url_for(identifiers, fallback_url=full_url),
        abstract=(it.get("abstractText") or "").strip(),
        authors=authors,
        year=safe_int(it.get("pubYear")),
        venue=(it.get("journalTitle") or "").strip(),
        source_tool="europepmc",
        identifiers=identifiers,
        raw=it,
    )
