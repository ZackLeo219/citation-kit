"""Adapters parse vendor-specific search-API responses into `CitationRecord`
plus LLM-facing snippets carrying the `{{cite:<id>}}` placeholder.

All adapters are thin (~80-150 LOC each) — they only normalize fields. They
do NOT perform deduplication or registration; the caller does that via
`registry.register_many()`.

Listed adapters:
    web search:    tavily, exa, brave, serper
    academic:      pubmed, semantic_scholar, arxiv, crossref, openalex, europepmc

To add a new source, model it on `tavily.py`:
    1. Define a `parse(raw_response: dict | str, *, source_tool: str) -> ParseResult`
    2. Each record's `identifiers` should populate as many of {doi, pmid, arxiv,
       s2, url} as the source provides — `pick_cite_id()` will pick the strongest
    3. Each snippet ends with `cite → {{cite:<id>}}` so the LLM sees
       exactly one canonical placeholder per fact
"""
from .base import build_snippet, ensure_authors_tuple

__all__ = ["build_snippet", "ensure_authors_tuple"]
