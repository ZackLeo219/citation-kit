"""arXiv adapter.

Accepts:
  * Output of `arxiv.Client().results(query)` — list of `arxiv.Result` objects
    or dict-converted equivalents
  * Raw API JSON: list[dict] with keys `entry_id`, `title`, `summary`,
    `published`, `authors`

arxiv.Result objects have attribute access (`.entry_id`, `.title`, etc.) so we
support both styles.
"""
from __future__ import annotations

from typing import Any, Iterable

from ..canonicalize import canonical_url_for, normalize_arxiv_id, normalize_doi, pick_cite_id
from ..types import CitationRecord, ParseResult
from .base import build_snippet, ensure_authors_tuple, safe_int


def parse(raw_response: Any) -> ParseResult:
    if isinstance(raw_response, dict):
        items = raw_response.get("entries") or raw_response.get("results") or []
    elif isinstance(raw_response, Iterable):
        items = list(raw_response)
    else:
        items = []
    records: list[CitationRecord] = []
    snippets: list[str] = []
    for item in items:
        rec = _parse_one(item)
        if rec is None:
            continue
        records.append(rec)
        snippets.append(build_snippet(rec))
    return ParseResult(records=records, snippets=snippets)


def _g(item: Any, key: str, default=None) -> Any:
    """Get attribute or dict key, whichever the item supports."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _parse_one(item: Any) -> CitationRecord | None:
    entry_id = _g(item, "entry_id", "") or _g(item, "id", "")
    arxiv_id = normalize_arxiv_id(str(entry_id))
    if not arxiv_id:
        return None
    doi_raw = _g(item, "doi", "")
    doi = normalize_doi(str(doi_raw)) if doi_raw else None
    identifiers = {"arxiv": arxiv_id}
    if doi:
        identifiers["doi"] = doi
    try:
        cite_id = pick_cite_id(identifiers)
    except ValueError:
        return None
    pub = _g(item, "published", "")
    year = safe_int(str(pub)[:4]) if pub else None
    authors_raw = _g(item, "authors", [])
    # arxiv.Result.authors is list of objects with .name; ensure_authors_tuple
    # handles dicts but not bespoke objects, so we stringify here.
    if authors_raw and not isinstance(authors_raw, str):
        authors_norm = []
        for a in authors_raw:
            if isinstance(a, (str, dict)):
                authors_norm.append(a)
            else:
                authors_norm.append(getattr(a, "name", str(a)))
        authors = ensure_authors_tuple(authors_norm)
    else:
        authors = ensure_authors_tuple(authors_raw)
    return CitationRecord(
        cite_id=cite_id,
        title=(_g(item, "title", "") or "").strip(),
        url=canonical_url_for(identifiers),
        abstract=(_g(item, "summary", "") or _g(item, "abstract", "") or "").strip(),
        authors=authors,
        year=year,
        venue="arXiv",
        source_tool="arxiv",
        identifiers=identifiers,
        raw=item if isinstance(item, dict) else None,
    )
