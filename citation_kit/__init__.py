"""citation_kit — universal citation grounding layer for LLM agents.

LLM emits opaque ``{{cite:<id>}}`` placeholders → server registry tracks
identity → renderer substitutes to numeric ``[N]`` or chip-style markdown
links → validator catches inconsistencies. Decouples synthesis (LLM) from
bookkeeping (server).

Quickstart (single-turn)::

    from citation_kit import CitationRegistry, CitationRenderer
    from citation_kit.adapters import tavily as tavily_adapter

    registry = CitationRegistry()

    # In your search tool:
    raw = tavily_client.search(query)
    parsed = tavily_adapter.parse(raw)
    registry.register_many(parsed.records)
    return "\\n\\n".join(parsed.snippets)
    # snippets contain `[cite this with]: {{cite:url:abc12345}}`

    # After LLM writes its answer (containing those placeholders):
    final = CitationRenderer(registry, turn_idx=0, mode="numeric").render(llm_text)

Multi-turn (registry persisted across turns)::

    from citation_kit import (
        CitationRegistry, CitationRenderer,
        rewrite_history_with_placeholders,
    )
    from citation_kit.stores import SQLiteStore

    store = SQLiteStore("./registry.db")

    # On each turn:
    data = await store.aload(conversation_id)
    registry = CitationRegistry.from_serializable(data)

    # Critical: rewrite past assistant messages' [N] markers back to
    # {{cite:...}} so the LLM sees consistent placeholder protocol throughout
    # history. Without this, the LLM will copy historical [N] patterns and
    # produce orphan refs.
    history = rewrite_history_with_placeholders(prior_messages, registry)

    # ... call your LLM with `history`, register tool results, render output ...
    await store.asave(conversation_id, registry.to_serializable())
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
from .history import (
    rewrite_history_with_placeholders,
    rewrite_text_with_placeholders,
)
from .observability import logger, set_metric_hook
from .registry import CitationRegistry, PLACEHOLDER_RE, TurnAllocation
from .renderer import CitationRenderer, DEFAULT_REFS_HEADER, RenderMode
from .stores import (
    InMemoryStore,
    JSONFileStore,
    PostgresStore,
    RedisStore,
    RegistryStore,
    SQLiteStore,
)
from .types import (
    CitationRecord,
    ParseResult,
    PLACEHOLDER_CLOSE,
    PLACEHOLDER_OPEN,
)
from .validator import ValidationResult, autofix_leaks, validate

__version__ = "0.2.0"

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
    # multi-turn
    "rewrite_history_with_placeholders",
    "rewrite_text_with_placeholders",
    # stores
    "RegistryStore",
    "InMemoryStore",
    "JSONFileStore",
    "SQLiteStore",
    "PostgresStore",
    "RedisStore",
    # canonicalization
    "pick_cite_id",
    "canonical_url_for",
    "canonicalize_url",
    "normalize_doi",
    "normalize_pmid",
    "normalize_arxiv_id",
    "url_hash",
    # observability
    "set_metric_hook",
    "logger",
]
