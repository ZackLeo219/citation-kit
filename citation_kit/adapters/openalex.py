"""OpenAlex adapter — free, comprehensive scholarly graph.

Returns:
    {
      "results": [
        {
          "id": "https://openalex.org/W123",
          "doi": "https://doi.org/10.x/y",
          "title": "...",
          "abstract_inverted_index": {"word": [pos1, pos2], ...},  # need reconstruction
          "publication_year": 2024,
          "authorships": [{"author": {"display_name": "..."}}, ...],
          "host_venue": {"display_name": "Nature"},
          "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/12345", "openalex": "...", ...},
        }
      ]
    }

OpenAlex stores abstracts as an inverted index to dodge copyright; we reverse
it to get a readable string. DOI/PMID extraction needs URL stripping.
"""
from __future__ import annotations

from typing import Any

from ..canonicalize import canonical_url_for, normalize_doi, normalize_pmid, pick_cite_id
from ..types import CitationRecord, ParseResult
from .base import build_snippet, safe_int


def parse(raw_response: dict[str, Any] | list[dict[str, Any]]) -> ParseResult:
    if isinstance(raw_response, list):
        results = raw_response
    else:
        results = raw_response.get("results") or []
    records: list[CitationRecord] = []
    snippets: list[str] = []
    for r in results:
        rec = _parse_one(r)
        if rec is None:
            continue
        records.append(rec)
        snippets.append(build_snippet(rec))
    return ParseResult(records=records, snippets=snippets)


def _reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str:
    """OpenAlex's `abstract_inverted_index` → readable string."""
    if not inverted:
        return ""
    pos_word: list[tuple[int, str]] = []
    for word, positions in inverted.items():
        for p in positions:
            pos_word.append((p, word))
    pos_word.sort()
    return " ".join(w for _, w in pos_word)


def _parse_one(r: dict[str, Any]) -> CitationRecord | None:
    ids = r.get("ids") or {}
    doi = normalize_doi(r.get("doi") or ids.get("doi", ""))
    pmid_url = ids.get("pmid", "")
    pmid = normalize_pmid(pmid_url.rsplit("/", 1)[-1]) if pmid_url else None
    identifiers: dict[str, str] = {}
    if doi:
        identifiers["doi"] = doi
    if pmid:
        identifiers["pmid"] = pmid
    if r.get("id"):
        identifiers["url"] = r["id"]
    if not identifiers:
        return None
    try:
        cite_id = pick_cite_id(identifiers)
    except ValueError:
        return None
    authorships = r.get("authorships") or []
    authors = tuple(
        (a.get("author") or {}).get("display_name", "").strip()
        for a in authorships
        if (a.get("author") or {}).get("display_name")
    )
    venue = (r.get("host_venue") or r.get("primary_location") or {}).get("display_name") or ""
    return CitationRecord(
        cite_id=cite_id,
        title=(r.get("title") or "").strip(),
        url=canonical_url_for(identifiers, fallback_url=r.get("id") or ""),
        abstract=_reconstruct_abstract(r.get("abstract_inverted_index")),
        authors=authors,
        year=safe_int(r.get("publication_year")),
        venue=venue.strip(),
        source_tool="openalex",
        identifiers=identifiers,
        raw=r,
    )
