"""Post-render validation + auto-fix.

After the renderer has produced final user-facing markdown, scan it for
inconsistencies (orphan placeholders, leaked `{{cite:...}}` strings, numeric
`[N]` references that don't resolve, etc.) and optionally auto-repair.

Use cases:
  * Server-side guardrail before sending the answer downstream
  * Offline eval — count violation rates across many turns
  * Telemetry — emit metrics for orphan/leak rates over time
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .registry import CitationRegistry, PLACEHOLDER_RE


# `[1]`, `[12]`, etc. — but not `[1, 2]` or `[abc]` (we want pure numeric)
NUMERIC_REF_RE = re.compile(r"\[(\d{1,4})\]")


@dataclass
class ValidationResult:
    leaked_placeholders: list[str] = field(default_factory=list)
    """`{{cite:...}}` markers that survived rendering — renderer bug or unknown cite_id."""

    orphan_numeric_refs: list[int] = field(default_factory=list)
    """`[N]` numbers in the body that don't appear in the references section."""

    unused_records: list[str] = field(default_factory=list)
    """cite_ids registered + allocated to this turn but never appeared in body."""

    duplicate_indices: list[int] = field(default_factory=list)
    """Same `[N]` pointing to different records — violates one-to-one mapping."""

    @property
    def ok(self) -> bool:
        return not (
            self.leaked_placeholders
            or self.orphan_numeric_refs
            or self.duplicate_indices
        )

    def summary(self) -> str:
        if self.ok and not self.unused_records:
            return "OK"
        parts = []
        if self.leaked_placeholders:
            parts.append(f"leaked={len(self.leaked_placeholders)}")
        if self.orphan_numeric_refs:
            parts.append(f"orphan_refs={self.orphan_numeric_refs}")
        if self.duplicate_indices:
            parts.append(f"dupes={self.duplicate_indices}")
        if self.unused_records:
            parts.append(f"unused={len(self.unused_records)}")
        return ", ".join(parts) or "OK"


def validate(
    rendered_text: str,
    registry: CitationRegistry,
    turn_idx: int,
) -> ValidationResult:
    """Inspect a rendered turn output for citation inconsistencies."""
    res = ValidationResult()

    # Leaked placeholders: `{{cite:X}}` that the renderer didn't substitute.
    for m in PLACEHOLDER_RE.finditer(rendered_text):
        res.leaked_placeholders.append(m.group(1).strip())

    alloc = registry.get_turn_allocation(turn_idx)
    if alloc is None:
        return res

    # Orphan numeric refs: `[N]` numbers in body but no corresponding record.
    valid_indices = set(alloc.index_map.values())
    seen_in_text: set[int] = set()
    for m in NUMERIC_REF_RE.finditer(rendered_text):
        try:
            n = int(m.group(1))
        except ValueError:
            continue
        seen_in_text.add(n)
        if n not in valid_indices and n not in res.orphan_numeric_refs:
            res.orphan_numeric_refs.append(n)

    # Unused records: allocated cite_ids whose `[N]` never appeared in body.
    for cid, n in alloc.index_map.items():
        if n not in seen_in_text:
            res.unused_records.append(cid)

    return res


def autofix_leaks(rendered_text: str, registry: CitationRegistry) -> str:
    """Replace any leaked `{{cite:X}}` with a best-effort chip-style fallback
    or drop it if the cite_id isn't in the registry. Idempotent.

    Use this as a last-line guard before sending text to the user. The
    `validate()` step should still log the leak for observability.
    """
    def repl(m):
        cid = m.group(1).strip()
        rec = registry.get(cid)
        if rec is None:
            return ""  # silently drop unknown
        url = rec.url or ""
        label = rec.short_label()
        if url:
            return f"[{label}]({url})"
        return f"[{label}]"
    return PLACEHOLDER_RE.sub(repl, rendered_text)
