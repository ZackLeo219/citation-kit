"""Multi-turn history rewriter.

Problem solved
--------------
After a turn renders, user-facing text contains substituted `[N]` markers.
Frontends typically store rendered text and POST it back as conversation
history on subsequent turns. The next-turn LLM then sees a mix of:
  * Tool results with fresh `{{cite:<id>}}` placeholders (current turn)
  * Historical assistant messages with `[N]` markers (past turns)

Faced with this mix, models often fall back to writing `[N]` themselves —
copying historical patterns rather than the current-turn placeholder
protocol. That `[N]` doesn't map to anything in the fresh registry, so
inline citations become orphan refs and the references section comes out
empty.

Fix
---
Before sending history to the LLM, walk past assistant messages and rewrite
their `[N]` markers back to `{{cite:<id>}}` placeholders using the
registry's persisted per-turn allocations. The model then sees a consistent
placeholder protocol throughout history and continues writing placeholders.

Pair with persistent storage (any `RegistryStore` backend) so the registry
survives across turns.
"""
from __future__ import annotations

import re
from typing import Iterable

from .registry import CitationRegistry
from .types import PLACEHOLDER_OPEN, PLACEHOLDER_CLOSE


# Match `[N]` standalone (not `[N, M]` or `[abc]` or `[1.2]`). Greedy on the
# digit run to capture multi-digit indices.
_NUMERIC_REF_RE = re.compile(r"\[(\d{1,4})\]")


def rewrite_history_with_placeholders(
    messages: list[dict],
    registry: CitationRegistry,
    *,
    role_field: str = "role",
    content_field: str = "content",
    turn_boundary_role: str = "user",
    target_roles: Iterable[str] = ("assistant",),
) -> list[dict]:
    """Reverse-map `[N]` in historical messages → `{{cite:<id>}}` placeholders.

    Walk ``messages`` in order, tracking which turn each message belongs to.
    A new turn begins each time a message with ``role == turn_boundary_role``
    is encountered (default: each ``user`` message starts a new turn).

    For each message whose role is in ``target_roles`` (default: assistant
    messages), look up that turn's allocation in the registry. For every
    ``[N]`` marker in the content, find the cite_id with index N and replace
    `[N]` with `{{cite:<id>}}`. Indices that don't resolve are left as-is
    (they were already orphan in the original output and surfacing them
    unchanged lets the validator catch them).

    Returns a new list (does not mutate input messages).

    Example::

        # Conversation: user → assistant(turn 0) → user → assistant(turn 1)
        # Registry has:
        #   turn 0 allocation: {pmid:111: 1, pmid:222: 2}
        #   turn 1 allocation: {pmid:333: 1}
        # Assistant turn-1 message reads "Building on [1] above ..." and may
        # also include current-turn citations.
        # After rewriting, it reads "Building on {{cite:pmid:333}} above ...",
        # which the LLM sees as a clean placeholder it can continue using.

    Edge cases:
      * Messages whose content is None or non-string are passed through
        unchanged (e.g. assistant messages that only carried tool_calls).
      * Multimodal content (lists of parts) is passed through; only the
        text-string case is rewritten. Library users with multimodal
        content can call ``rewrite_text_with_placeholders`` per text part.
    """
    if not messages:
        return []
    target_set = set(target_roles)
    out: list[dict] = []
    turn_idx = -1  # will become 0 at the first turn-boundary message
    for msg in messages:
        role = msg.get(role_field)
        if role == turn_boundary_role:
            turn_idx += 1
        if role not in target_set:
            out.append(dict(msg))
            continue
        content = msg.get(content_field)
        if not isinstance(content, str) or not content:
            out.append(dict(msg))
            continue
        if turn_idx < 0:
            # Assistant message before any user turn boundary — uncommon,
            # treat as turn 0.
            effective_turn = 0
        else:
            effective_turn = turn_idx
        rewritten = rewrite_text_with_placeholders(
            content, registry, turn_idx=effective_turn
        )
        new_msg = dict(msg)
        new_msg[content_field] = rewritten
        out.append(new_msg)
    return out


def rewrite_text_with_placeholders(
    text: str,
    registry: CitationRegistry,
    *,
    turn_idx: int,
) -> str:
    """Replace `[N]` markers in ``text`` with `{{cite:<id>}}` placeholders
    using the allocation for ``turn_idx`` from ``registry``.

    Standalone helper for callers that already know the turn index per chunk
    (e.g. multimodal content parts, or non-standard message layouts).
    Indices not present in the allocation are left as-is.
    """
    alloc = registry.get_turn_allocation(turn_idx)
    if alloc is None or not alloc.index_map:
        return text
    # Build inverse: index → cite_id
    idx_to_cite: dict[int, str] = {v: k for k, v in alloc.index_map.items()}

    def _repl(m: re.Match) -> str:
        try:
            n = int(m.group(1))
        except ValueError:
            return m.group(0)
        cite_id = idx_to_cite.get(n)
        if cite_id is None:
            return m.group(0)
        return f"{PLACEHOLDER_OPEN}{cite_id}{PLACEHOLDER_CLOSE}"

    return _NUMERIC_REF_RE.sub(_repl, text)
