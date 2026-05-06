"""Core type definitions for citation_kit.

A `CitationRecord` is the canonical, source-agnostic representation of a single
referenceable item (a paper / web page / dataset). Adapters parse vendor-specific
API responses into `CitationRecord` instances, and `CitationRegistry` keeps the
per-thread pool keyed by canonical `cite_id`.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


# Placeholder format the LLM emits in its output text. Captured by the renderer
# and replaced with either a numeric `[N]` marker or a chip-style markdown link.
# Format: `{{cite:<scheme>:<opaque-id>}}` where scheme ∈ {doi, pmid, arxiv, s2,
# url} and the opaque-id is whatever the adapter assigned (DOI string, PubMed
# numeric ID, arXiv ID, Semantic Scholar paper ID, or URL hash).
PLACEHOLDER_OPEN = "{{cite:"
PLACEHOLDER_CLOSE = "}}"


@dataclass(frozen=True)
class CitationRecord:
    """Canonical representation of one referenceable item.

    `cite_id` is the persistent key — same paper from different APIs (PubMed
    PMID vs Semantic Scholar paperId vs Crossref DOI) MUST canonicalize to the
    same `cite_id` so the registry deduplicates correctly. Use `pick_cite_id()`
    on the candidates dict the adapter assembles.

    Fields:
      cite_id: e.g. `doi:10.1038/...`, `pmid:12345`, `arxiv:2401.123`, `url:<hex>`
      title: human-readable title
      url: canonical URL (DOI URL preferred, then publisher URL, then archival URL)
      abstract: short snippet (≤ 1500 chars; we store more would bloat checkpoint)
      authors: list of author last names or "First Last" strings
      year: publication year (int) if known
      venue: journal / conference / "preprint" string
      source_tool: which adapter produced this (`tavily`, `pubmed`, ...)
      identifiers: dict of all known identifiers — `{"doi": "...", "pmid": "...",
                   "url": "..."}` — used for cross-source deduplication and link
                   construction in the references list.
      raw: opaque adapter-private payload, preserved for debugging. NOT serialized
           to the LLM context.
    """
    cite_id: str
    title: str
    url: str
    abstract: str = ""
    authors: tuple[str, ...] = field(default_factory=tuple)
    year: int | None = None
    venue: str = ""
    source_tool: str = ""
    identifiers: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] | None = None

    def to_serializable(self) -> dict[str, Any]:
        """JSON-safe dict (drops `raw`). Used when persisting registry to thread state."""
        d = asdict(self)
        d.pop("raw", None)
        d["authors"] = list(self.authors)
        return d

    @classmethod
    def from_serializable(cls, d: dict[str, Any]) -> CitationRecord:
        return cls(
            cite_id=d["cite_id"],
            title=d.get("title", ""),
            url=d.get("url", ""),
            abstract=d.get("abstract", ""),
            authors=tuple(d.get("authors") or ()),
            year=d.get("year"),
            venue=d.get("venue", ""),
            source_tool=d.get("source_tool", ""),
            identifiers=dict(d.get("identifiers") or {}),
            raw=None,
        )

    def cite_placeholder(self) -> str:
        """The opaque marker the LLM should write to cite this record."""
        return f"{PLACEHOLDER_OPEN}{self.cite_id}{PLACEHOLDER_CLOSE}"

    def short_label(self) -> str:
        """Short human label used inside chip-style rendering (`[<short>](url ...)`).

        Prefers first-author + year when available, falls back to truncated title.
        """
        if self.authors and self.year:
            return f"{self.authors[0]} {self.year}"
        if self.authors:
            return self.authors[0]
        title = self.title or self.url
        return title[:60] + ("…" if len(title) > 60 else "")

    def reference_line(self) -> str:
        """Single-line reference entry for the auto-generated `## References` section.

        Format follows a relaxed Vancouver-ish style — readable but no strict CSL.
        Frontend rendering is markdown, so the link is clickable.
        """
        parts: list[str] = []
        if self.authors:
            authors_str = ", ".join(self.authors[:3])
            if len(self.authors) > 3:
                authors_str += ", et al."
            parts.append(authors_str + ".")
        if self.title:
            parts.append(self.title.rstrip(".") + ".")
        if self.venue:
            venue_str = self.venue
            if self.year:
                venue_str += f" {self.year}"
            parts.append(venue_str + ".")
        elif self.year:
            parts.append(f"{self.year}.")
        meta = " ".join(parts).strip() or self.title or self.url
        return f"[{meta}]({self.url})" if self.url else meta


@dataclass
class ParseResult:
    """Adapter return: a list of `CitationRecord` plus a parallel list of
    text snippets the calling tool should embed into its return value to the
    LLM. Each snippet contains the placeholder string the LLM should copy
    verbatim to cite this record.
    """
    records: list[CitationRecord]
    snippets: list[str]
