"""Render LLM output containing `{{cite:<id>}}` placeholders.

Two modes:
  * `numeric`  — replace `{{cite:X}}` → `[N]`, append `## References` section
  * `chip`     — replace `{{cite:X}}` → `[short](url "title‖abstract")` markdown
                 link with title attribute (frontend renders as pill chip)

Both modes consume the same `CitationRegistry` and produce a final string;
streaming variants are also provided for incremental SSE token transformation.
"""
from __future__ import annotations

from typing import AsyncIterator, Iterator, Literal

from .observability import emit as _emit_metric
from .registry import CitationRegistry, PLACEHOLDER_RE
from .types import PLACEHOLDER_OPEN, PLACEHOLDER_CLOSE


RenderMode = Literal["numeric", "chip"]
DEFAULT_REFS_HEADER = "## 参考文献"


class CitationRenderer:
    """Stateful renderer for one turn.

    Usage (batch):
        renderer = CitationRenderer(registry, turn_idx=3, mode="numeric")
        rendered = renderer.render(llm_output)

    Usage (streaming, async):
        async for chunk in renderer.render_stream(token_stream()):
            await sse_emit(chunk)
        # Footer (## References) is yielded as the final chunk before stream end.
    """

    def __init__(
        self,
        registry: CitationRegistry,
        turn_idx: int,
        mode: RenderMode = "chip",
        refs_header: str = DEFAULT_REFS_HEADER,
        append_references: bool = True,
    ) -> None:
        self.registry = registry
        self.turn_idx = turn_idx
        self.mode = mode
        self.refs_header = refs_header
        self.append_references = append_references
        # Mutable: the cite_ids encountered so far in stream order.
        self._seen_order: list[str] = []
        self._seen_set: set[str] = set()

    # ───────── Batch render ─────────

    def render(self, text: str) -> str:
        """Render a complete LLM output. Calls `allocate_indices` on the
        registry as a side effect so the index assignment persists."""
        ordered = self.registry.scan_placeholders(text)
        index_map = self.registry.allocate_indices(self.turn_idx, ordered)
        rendered_body = self._substitute(text, index_map)
        if self.append_references and ordered:
            return rendered_body + "\n\n" + self._build_references(ordered, index_map)
        return rendered_body

    # ───────── Incremental feed (for ad-hoc loops) ─────────

    def feed(self, chunk: str) -> str:
        """Push one chunk through the renderer; return whatever's safe to emit
        downstream now. Buffers any partial `{{cite:...` that might be
        completed by the next call to `feed()`. Pair with `flush()` after the
        last chunk to drain any trailing buffer.

        Use this when you have your own SSE / queue loop and don't want to
        wrap your existing iterator into `render_stream()`.

        Example::

            r = CitationRenderer(registry, turn_idx, append_references=False)
            async for delta in llm_stream:
                emit(r.feed(delta.content))
            emit(r.flush())                      # drain partial buffer
            emit(r.references_section())         # if you want a footer
        """
        self._buf = getattr(self, "_buf", "") + chunk
        out, self._buf = self._scan_buffer(self._buf)
        return out

    def flush(self) -> str:
        """Drain any partial buffer (called once after the last `feed()`).
        Also persists the per-turn index allocation so subsequent `render()`
        calls on the same final text produce the same numbering."""
        buf = getattr(self, "_buf", "")
        out = ""
        if buf:
            out, _ = self._scan_buffer(buf, flush=True)
            self._buf = ""
        # Persist allocation for re-render consistency
        self.registry.allocate_indices(self.turn_idx, list(self._seen_order))
        return out

    def references_section(self) -> str:
        """Return the auto-generated `## 参考文献` block for everything fed so
        far. Empty string if no placeholders were seen (caller should skip
        emission). Safe to call any time after `flush()`."""
        if not self._seen_order:
            return ""
        index_map = {cid: i + 1 for i, cid in enumerate(self._seen_order)}
        return self._build_references(self._seen_order, index_map)

    # ───────── Streaming render ─────────

    def render_stream(self, chunks: Iterator[str]) -> Iterator[str]:
        """Synchronous streaming variant. Buffers partial placeholders across
        chunk boundaries; replaces eagerly once a complete placeholder is seen.

        Index allocation is **eager**: the first occurrence of an unseen cite_id
        gets the next sequential `[N]`. We don't know the full order in advance
        in the streaming path, so we trade strict reproducibility for streaming
        UX. (A re-render from the saved final text via `render()` will produce
        the same numbering as long as the LLM output is deterministic.)
        """
        buf = ""
        for chunk in chunks:
            buf += chunk
            out, buf = self._scan_buffer(buf)
            if out:
                yield out
        # Flush trailing buffer (no more chunks coming)
        if buf:
            out, _ = self._scan_buffer(buf, flush=True)
            if out:
                yield out
        # Save final allocation so re-render is consistent
        self.registry.allocate_indices(self.turn_idx, list(self._seen_order))
        # Footer
        if self.append_references and self._seen_order:
            index_map = {cid: i + 1 for i, cid in enumerate(self._seen_order)}
            yield "\n\n" + self._build_references(self._seen_order, index_map)

    async def render_stream_async(
        self, chunks: AsyncIterator[str]
    ) -> AsyncIterator[str]:
        """Async streaming variant. Same semantics as `render_stream`."""
        buf = ""
        async for chunk in chunks:
            buf += chunk
            out, buf = self._scan_buffer(buf)
            if out:
                yield out
        if buf:
            out, _ = self._scan_buffer(buf, flush=True)
            if out:
                yield out
        self.registry.allocate_indices(self.turn_idx, list(self._seen_order))
        if self.append_references and self._seen_order:
            index_map = {cid: i + 1 for i, cid in enumerate(self._seen_order)}
            yield "\n\n" + self._build_references(self._seen_order, index_map)

    # ───────── Internals ─────────

    def _scan_buffer(self, buf: str, *, flush: bool = False) -> tuple[str, str]:
        """Find complete `{{cite:...}}` substitutions in `buf`. Return
        `(emit, remainder)` where `emit` is the prefix safe to yield (with
        substitutions done) and `remainder` is what to keep buffered (might
        contain a half-finished placeholder).

        On `flush=True` we yield everything (any `{{cite:...` that never
        completed is yielded as-is — a "leaked" placeholder caught by
        validator).
        """
        out_parts: list[str] = []
        cursor = 0
        while True:
            open_idx = buf.find(PLACEHOLDER_OPEN, cursor)
            if open_idx < 0:
                # No complete open found. If we're flushing, emit everything.
                # Otherwise we need to retain any tail bytes that could be the
                # start of an `{{cite:` split across the next chunk boundary.
                # Find the FIRST `{` from `cursor` whose suffix is a prefix of
                # PLACEHOLDER_OPEN — that's the earliest position from which a
                # legitimate placeholder could still complete.
                if flush:
                    out_parts.append(buf[cursor:])
                    cursor = len(buf)
                    break
                tail_keep_start = len(buf)  # default: nothing to retain
                for i in range(cursor, len(buf)):
                    if buf[i] == "{" and PLACEHOLDER_OPEN.startswith(buf[i:]):
                        tail_keep_start = i
                        break
                out_parts.append(buf[cursor:tail_keep_start])
                cursor = tail_keep_start
                break
            close_idx = buf.find(PLACEHOLDER_CLOSE, open_idx + len(PLACEHOLDER_OPEN))
            if close_idx < 0:
                # Open without close yet — emit prefix, keep `{{cite:...` in buf
                out_parts.append(buf[cursor:open_idx])
                cursor = open_idx
                if flush:
                    # Yield the leaked partial as literal text
                    out_parts.append(buf[cursor:])
                    cursor = len(buf)
                break
            cite_id = buf[open_idx + len(PLACEHOLDER_OPEN) : close_idx].strip()
            replacement = self._substitute_one(cite_id)
            out_parts.append(buf[cursor:open_idx])
            out_parts.append(replacement)
            cursor = close_idx + len(PLACEHOLDER_CLOSE)
        return "".join(out_parts), buf[cursor:]

    def _substitute(self, text: str, index_map: dict[str, int]) -> str:
        """Batch substitution path — knows the full index_map upfront, so each
        replacement is deterministic."""
        def repl(m):
            cid = m.group(1).strip()
            return self._format_one(cid, index_map.get(cid))
        return PLACEHOLDER_RE.sub(repl, text)

    def _substitute_one(self, cite_id: str) -> str:
        """Streaming substitution — assigns next index on first sight."""
        if cite_id not in self._seen_set:
            if cite_id in self.registry:
                self._seen_set.add(cite_id)
                self._seen_order.append(cite_id)
                _emit_metric("citation_kit.placeholder_seen", mode=self.mode)
            else:
                # Unknown placeholder — leave as visible marker for validator
                _emit_metric("citation_kit.placeholder_orphan", mode=self.mode)
                return f"[?{cite_id}?]"
        idx = self._seen_order.index(cite_id) + 1
        return self._format_one(cite_id, idx)

    def _format_one(self, cite_id: str, index: int | None) -> str:
        rec = self.registry.get(cite_id)
        if rec is None:
            return f"[?{cite_id}?]"
        if self.mode == "numeric":
            return f"[{index}]" if index else "[?]"
        # chip mode
        title = (rec.title or rec.short_label()).replace('"', "'")
        abstract = (rec.abstract or "").replace('"', "'")[:300]
        attr = f"{title}‖{abstract}" if abstract else title
        # Use `[short label](url "title‖abstract")` so frontend renders as pill.
        short = rec.short_label().replace("[", "(").replace("]", ")")
        url = rec.url or ""
        return f'[{short}]({url} "{attr}")'

    def _build_references(
        self, ordered_cite_ids: list[str], index_map: dict[str, int]
    ) -> str:
        lines = [self.refs_header]
        for cid in ordered_cite_ids:
            rec = self.registry.get(cid)
            if rec is None:
                continue
            n = index_map.get(cid, 0)
            lines.append(f"{n}. {rec.reference_line()}")
        return "\n".join(lines)
