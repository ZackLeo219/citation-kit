"""PubMed (NCBI E-utilities) adapter.

We accept the parsed-dict shape produced by `Bio.Entrez.read(efetch(...))` for
PubMed articles. Common per-article path:
    PubmedArticle/MedlineCitation/Article/...

For convenience, we ALSO accept a simpler dict shape that callers can hand-roll:
    {
      "pmid": "12345",
      "title": "...",
      "abstract": "...",
      "authors": ["Last F", "Last F"],
      "year": 2024,
      "journal": "...",
      "doi": "10.1038/...",  # optional
    }

The latter is useful if you're not using biopython but hitting E-utilities
directly via httpx.
"""
from __future__ import annotations

from typing import Any

from ..canonicalize import canonical_url_for, normalize_doi, normalize_pmid, pick_cite_id
from ..types import CitationRecord, ParseResult
from .base import build_snippet, ensure_authors_tuple, safe_int


def parse(raw_response: list[dict[str, Any]] | dict[str, Any]) -> ParseResult:
    """Accept either:
      * Top-level Entrez result: dict with `PubmedArticle` key (list of articles)
      * Bare list of articles in the simple-dict form
      * Bare list of articles in the Entrez nested form
    """
    articles = _extract_article_list(raw_response)
    records: list[CitationRecord] = []
    snippets: list[str] = []
    for art in articles:
        rec = _parse_one(art)
        if rec is None:
            continue
        records.append(rec)
        snippets.append(build_snippet(rec))
    return ParseResult(records=records, snippets=snippets)


def _extract_article_list(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        if "PubmedArticle" in raw:
            return list(raw["PubmedArticle"])
        if "articles" in raw:
            return list(raw["articles"])
    return []


def _parse_one(art: dict[str, Any]) -> CitationRecord | None:
    # Simple-dict path first (caller pre-flattened):
    if "pmid" in art or "title" in art and "PubmedArticle" not in art and "MedlineCitation" not in art:
        return _parse_simple(art)
    # Entrez nested path
    return _parse_entrez(art)


def _parse_simple(art: dict[str, Any]) -> CitationRecord | None:
    pmid = normalize_pmid(art.get("pmid"))
    doi = normalize_doi(art.get("doi", ""))
    identifiers = {}
    if doi:
        identifiers["doi"] = doi
    if pmid:
        identifiers["pmid"] = pmid
    if not identifiers:
        return None
    try:
        cite_id = pick_cite_id(identifiers)
    except ValueError:
        return None
    return CitationRecord(
        cite_id=cite_id,
        title=(art.get("title") or "").strip(),
        url=canonical_url_for(identifiers),
        abstract=(art.get("abstract") or "").strip(),
        authors=ensure_authors_tuple(art.get("authors")),
        year=safe_int(art.get("year")),
        venue=(art.get("journal") or "").strip(),
        source_tool="pubmed",
        identifiers=identifiers,
        raw=art,
    )


def _parse_entrez(art: dict[str, Any]) -> CitationRecord | None:
    try:
        mc = art["MedlineCitation"]
        article = mc["Article"]
    except (KeyError, TypeError):
        return None
    pmid = normalize_pmid(str(mc.get("PMID", "")))
    title = (article.get("ArticleTitle") or "").strip()
    abstract_parts = (article.get("Abstract") or {}).get("AbstractText") or []
    if isinstance(abstract_parts, str):
        abstract = abstract_parts
    else:
        abstract = " ".join(str(p) for p in abstract_parts if p)
    journal = ((article.get("Journal") or {}).get("Title") or "").strip()
    year = None
    pubdate = ((article.get("Journal") or {}).get("JournalIssue") or {}).get("PubDate") or {}
    if "Year" in pubdate:
        year = safe_int(pubdate["Year"])
    elif "MedlineDate" in pubdate:
        year = safe_int(str(pubdate["MedlineDate"])[:4])
    authors_raw = (article.get("AuthorList") or [])
    authors = []
    for a in authors_raw:
        if isinstance(a, dict):
            last = a.get("LastName", "")
            init = a.get("Initials", "")
            full = f"{last} {init}".strip()
            if full:
                authors.append(full)
    # Find DOI in ArticleIdList → ELocationID
    doi = None
    for el in article.get("ELocationID", []) or []:
        if isinstance(el, dict) and (el.get("EIdType") or el.get("attributes", {}).get("EIdType")) == "doi":
            doi = normalize_doi(str(el.get("value") or el))
            break
        elif isinstance(el, str) and el.startswith("10."):
            doi = normalize_doi(el)
            break

    identifiers = {}
    if doi:
        identifiers["doi"] = doi
    if pmid:
        identifiers["pmid"] = pmid
    if not identifiers:
        return None
    try:
        cite_id = pick_cite_id(identifiers)
    except ValueError:
        return None
    return CitationRecord(
        cite_id=cite_id,
        title=title,
        url=canonical_url_for(identifiers),
        abstract=abstract,
        authors=tuple(authors),
        year=year,
        venue=journal,
        source_tool="pubmed",
        identifiers=identifiers,
        raw=art,
    )
