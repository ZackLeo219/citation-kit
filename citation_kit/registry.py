"""CitationRegistry — per-thread citation pool.

Lifecycle:
  1. Tool adapter parses API response → list[CitationRecord]
  2. Tool wrapper calls `registry.register_many(records)` → returns cite_ids
  3. Tool wrapper embeds `{{cite:<id>}}` placeholders into the LLM-facing text
  4. LLM writes answer with placeholders preserved verbatim
  5. End-of-turn: `registry.allocate_indices(turn_idx)` assigns sequential `[N]`
     for the placeholders that actually appear in the LLM's output
  6. Renderer substitutes placeholders + appends `## References` section
  7. Registry is serialized → persisted via the chosen `RegistryStore`

The registry is the **single source of truth** for citation metadata. The LLM
never writes URLs/titles/authors itself; everything user-visible is rendered
from the registry by deterministic server code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .types import CitationRecord, PLACEHOLDER_OPEN, PLACEHOLDER_CLOSE


# Matches `{{cite:<id>}}` where <id> is anything except `}` (so DOIs with
# slashes / dots / colons all work). Captured group is the bare cite_id.
PLACEHOLDER_RE = re.compile(
    re.escape(PLACEHOLDER_OPEN) + r"([^}]+)" + re.escape(PLACEHOLDER_CLOSE)
)


@dataclass
class TurnAllocation:
    """Per-turn assignment of `[N]` indices to cite_ids that actually appeared
    in this turn's output. Stored in the registry so that on thread reopen we
    can re-render past turns with the same numbering."""
    turn_idx: int
    ordered_cite_ids: list[str] = field(default_factory=list)
    # cite_id → 1-based index for this turn
    index_map: dict[str, int] = field(default_factory=dict)


class CitationRegistry:
    """Per-thread citation pool. Not thread-safe; one instance per thread,
    accessed by the single async driver task that owns that thread's turn.
    """

    def __init__(self) -> None:
        self._records: dict[str, CitationRecord] = {}
        self._turns: dict[int, TurnAllocation] = {}

    # ───────── Registration ─────────

    def register(self, record: CitationRecord) -> str:
        """Insert (or merge) one record. Returns the cite_id.

        Idempotent: registering the same cite_id twice keeps the version with
        more populated fields. This handles the common case where one query hit
        the same paper from PubMed (rich metadata) and Tavily (URL + snippet
        only) — we want the union.
        """
        cid = record.cite_id
        if cid in self._records:
            self._records[cid] = self._merge(self._records[cid], record)
        else:
            self._records[cid] = record
        return cid

    def register_many(self, records: list[CitationRecord]) -> list[str]:
        return [self.register(r) for r in records]

    @staticmethod
    def _merge(existing: CitationRecord, incoming: CitationRecord) -> CitationRecord:
        """Field-level merge: prefer non-empty values; for identifiers, union."""
        def pick(a, b):
            return b if (b and not a) else a
        merged_ids = {**existing.identifiers, **{k: v for k, v in incoming.identifiers.items() if v}}
        return CitationRecord(
            cite_id=existing.cite_id,
            title=pick(existing.title, incoming.title),
            url=pick(existing.url, incoming.url),
            abstract=pick(existing.abstract, incoming.abstract),
            authors=existing.authors if existing.authors else incoming.authors,
            year=pick(existing.year, incoming.year),
            venue=pick(existing.venue, incoming.venue),
            source_tool=existing.source_tool or incoming.source_tool,
            identifiers=merged_ids,
            raw=existing.raw or incoming.raw,
        )

    # ───────── Lookup ─────────

    def get(self, cite_id: str) -> CitationRecord | None:
        return self._records.get(cite_id)

    def all_records(self) -> dict[str, CitationRecord]:
        return dict(self._records)

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, cite_id: str) -> bool:
        return cite_id in self._records

    # ───────── Per-turn index allocation ─────────

    def scan_placeholders(self, text: str) -> list[str]:
        """Return the cite_ids that appear in `text`, in order of first
        appearance, deduplicated. Placeholders pointing to cite_ids not in this
        registry are dropped (caller can detect this via `validate()`)."""
        seen: set[str] = set()
        ordered: list[str] = []
        for m in PLACEHOLDER_RE.finditer(text):
            cid = m.group(1).strip()
            if cid in self._records and cid not in seen:
                seen.add(cid)
                ordered.append(cid)
        return ordered

    def allocate_indices(
        self, turn_idx: int, ordered_cite_ids: list[str]
    ) -> dict[str, int]:
        """Assign sequential `[1], [2], ...` indices for this turn. Caller
        passes the de-duplicated cite_ids in their output order (typically from
        `scan_placeholders` on the LLM's complete output).

        Stored on the registry so subsequent renders of the same turn produce
        the same numbering (important when re-opening a thread or replaying
        from a cached message log).
        """
        index_map = {cid: i + 1 for i, cid in enumerate(ordered_cite_ids)}
        self._turns[turn_idx] = TurnAllocation(
            turn_idx=turn_idx,
            ordered_cite_ids=list(ordered_cite_ids),
            index_map=index_map,
        )
        return index_map

    def get_turn_allocation(self, turn_idx: int) -> TurnAllocation | None:
        return self._turns.get(turn_idx)

    # ───────── Serialization ─────────

    def to_serializable(self) -> dict[str, Any]:
        """JSON-safe dict — for persistence via a `RegistryStore` backend."""
        return {
            "records": {cid: r.to_serializable() for cid, r in self._records.items()},
            "turns": [
                {
                    "turn_idx": t.turn_idx,
                    "ordered_cite_ids": list(t.ordered_cite_ids),
                    "index_map": dict(t.index_map),
                }
                for t in sorted(self._turns.values(), key=lambda x: x.turn_idx)
            ],
        }

    @classmethod
    def from_serializable(cls, data: dict[str, Any] | None) -> "CitationRegistry":
        reg = cls()
        if not data:
            return reg
        for cid, rec_dict in (data.get("records") or {}).items():
            reg._records[cid] = CitationRecord.from_serializable(rec_dict)
        for t_dict in (data.get("turns") or []):
            t = TurnAllocation(
                turn_idx=int(t_dict["turn_idx"]),
                ordered_cite_ids=list(t_dict.get("ordered_cite_ids") or []),
                index_map={k: int(v) for k, v in (t_dict.get("index_map") or {}).items()},
            )
            reg._turns[t.turn_idx] = t
        return reg
