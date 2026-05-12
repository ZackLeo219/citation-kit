"""Adapter helpers shared across vendor implementations."""
from __future__ import annotations

from typing import Any, Iterable

from ..types import CitationRecord


SNIPPET_TEMPLATE = (
    "{title}\n"
    "{snippet}\n"
    "cite → {placeholder}\n"
)


def build_snippet(record: CitationRecord, snippet_text: str = "") -> str:
    """Render an LLM-facing snippet for one record. The trailing
    `cite → {{cite:<id>}}` line is the contract the LLM relies on to know
    which marker to copy verbatim. The arrow form (no square brackets
    around `cite`) is deliberate: the earlier `[cite this with]:` label
    primed instruction-following models — Qwen-class especially — to
    drift into emitting `[cite:pmid:...]` shorthand themselves. Those
    single-bracket strings bypass the renderer's `{{...}}` regex
    entirely, leading to dropped citations and missing references
    sections downstream.

    `snippet_text` defaults to the record's abstract; pass a custom string when
    the search API returns a query-specific excerpt that's more relevant than
    the abstract.
    """
    body = (snippet_text or record.abstract or "").strip()
    return SNIPPET_TEMPLATE.format(
        title=record.title or record.url,
        snippet=body[:1500],  # hard cap to keep ToolMessage size sane
        placeholder=record.cite_placeholder(),
    )


def ensure_authors_tuple(authors: Any) -> tuple[str, ...]:
    """Coerce arbitrary author representation to a tuple of strings.
    Drops empty entries. Handles list[dict] (with `name` key), list[str], or str."""
    if not authors:
        return ()
    if isinstance(authors, str):
        return (authors.strip(),) if authors.strip() else ()
    out: list[str] = []
    for a in authors if isinstance(authors, Iterable) else [authors]:
        if isinstance(a, dict):
            name = a.get("name") or " ".join(filter(None, [a.get("given"), a.get("family")]))
        elif isinstance(a, str):
            name = a
        else:
            name = str(a)
        name = (name or "").strip()
        if name:
            out.append(name)
    return tuple(out)


def safe_int(v: Any) -> int | None:
    """Best-effort int coerce. Returns None for falsy / non-parseable input."""
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        try:
            return int(str(v)[:4])  # year-like prefix
        except (ValueError, TypeError):
            return None
