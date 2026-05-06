"""citation_kit — universal citation grounding layer for LLM agents.

LLM emits opaque `{{cite:<id>}}` placeholders → server registry tracks identity
→ renderer substitutes to numeric `[N]` or chip-style markdown links → validator
catches inconsistencies. Decouples synthesis (LLM) from bookkeeping (server).

Quickstart:

    from citation_kit import CitationRegistry, CitationRenderer
    from citation_kit.adapters import tavily as tavily_adapter

    registry = CitationRegistry()

    # In your search tool:
    raw = tavily_client.search(query)
    parsed = tavily_adapter.parse(raw)
    registry.register_many(parsed.records)
    tool_result_for_llm = "\\n\\n".join(parsed.snippets)
    return tool_result_for_llm

    # In your LLM call: model sees `{{cite:url:abc123}}` markers, copies them
    # verbatim into its answer.

    # After LLM finishes:
    final = CitationRenderer(registry, turn_idx=0, mode="numeric").render(llm_text)
    # `final` has `[1]`, `[2]`, ... + auto-appended `## 参考文献` section.
"""
from .canonicalize import (
    canonical_url_for,
    canonicalize_url,
    normalize_arxiv_id,
    normalize_doi,
    normalize_pmid,
    pick_cite_id,
    url_hash,
)
from .registry import CitationRegistry, PLACEHOLDER_RE, TurnAllocation
from .renderer import CitationRenderer, DEFAULT_REFS_HEADER, RenderMode
from .stores import InMemoryStore, JSONFileStore, RegistryStore
from .types import (
    CitationRecord,
    ParseResult,
    PLACEHOLDER_CLOSE,
    PLACEHOLDER_OPEN,
)
from .validator import ValidationResult, autofix_leaks, validate

__version__ = "0.1.0"

__all__ = [
    # core types
    "CitationRecord",
    "ParseResult",
    "PLACEHOLDER_OPEN",
    "PLACEHOLDER_CLOSE",
    # registry
    "CitationRegistry",
    "TurnAllocation",
    "PLACEHOLDER_RE",
    # renderer
    "CitationRenderer",
    "RenderMode",
    "DEFAULT_REFS_HEADER",
    # validator
    "validate",
    "autofix_leaks",
    "ValidationResult",
    # stores
    "RegistryStore",
    "InMemoryStore",
    "JSONFileStore",
    # canonicalization
    "pick_cite_id",
    "canonical_url_for",
    "canonicalize_url",
    "normalize_doi",
    "normalize_pmid",
    "normalize_arxiv_id",
    "url_hash",
]
