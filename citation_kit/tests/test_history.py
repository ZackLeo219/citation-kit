import unittest

from citation_kit.history import (
    rewrite_history_with_placeholders,
    rewrite_text_with_placeholders,
)
from citation_kit.registry import CitationRegistry
from citation_kit.types import CitationRecord


def _rec(cite_id, title="T", url="https://example.com/x"):
    return CitationRecord(cite_id=cite_id, title=title, url=url)


def _build_registry_with_turns(turn_specs: list[list[str]]) -> CitationRegistry:
    """Helper: turn_specs is a list-of-lists of cite_ids per turn.
    Returns a registry with all records registered and per-turn
    allocations made in the given order."""
    reg = CitationRegistry()
    for ti, cite_ids in enumerate(turn_specs):
        for cid in cite_ids:
            if cid not in reg:
                reg.register(_rec(cid))
        reg.allocate_indices(ti, cite_ids)
    return reg


class TestRewriteText(unittest.TestCase):
    def test_basic(self):
        reg = _build_registry_with_turns([["pmid:111", "pmid:222"]])
        out = rewrite_text_with_placeholders("Foo [1] bar [2].", reg, turn_idx=0)
        self.assertEqual(out, "Foo {{cite:pmid:111}} bar {{cite:pmid:222}}.")

    def test_unmapped_index_left_alone(self):
        reg = _build_registry_with_turns([["pmid:111"]])
        out = rewrite_text_with_placeholders("Foo [1] orphan [9].", reg, turn_idx=0)
        self.assertEqual(out, "Foo {{cite:pmid:111}} orphan [9].")

    def test_no_allocation_returns_input(self):
        reg = CitationRegistry()
        out = rewrite_text_with_placeholders("Foo [1].", reg, turn_idx=99)
        self.assertEqual(out, "Foo [1].")

    def test_doesnt_touch_non_numeric_brackets(self):
        reg = _build_registry_with_turns([["pmid:111"]])
        out = rewrite_text_with_placeholders("[1] vs [N] vs [abc].", reg, turn_idx=0)
        self.assertEqual(out, "{{cite:pmid:111}} vs [N] vs [abc].")

    def test_multidigit_index(self):
        ids = [f"pmid:{i}" for i in range(1, 13)]  # 12 records
        reg = _build_registry_with_turns([ids])
        out = rewrite_text_with_placeholders("Cite [12] please.", reg, turn_idx=0)
        self.assertEqual(out, "Cite {{cite:pmid:12}} please.")


class TestRewriteHistory(unittest.TestCase):
    def test_two_turn_conversation(self):
        # turn 0: assistant cites [1], [2]
        # turn 1: assistant cites [1] (in turn 1's index space, which is a
        #         different paper than turn 0's [1])
        reg = _build_registry_with_turns([
            ["pmid:111", "pmid:222"],   # turn 0
            ["pmid:333"],                # turn 1
        ])
        messages = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "Found [1] and [2]."},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "Building on [1] from earlier..."},
        ]
        out = rewrite_history_with_placeholders(messages, reg)
        self.assertEqual(out[0]["content"], "Q1")
        self.assertEqual(
            out[1]["content"],
            "Found {{cite:pmid:111}} and {{cite:pmid:222}}.",
        )
        self.assertEqual(out[2]["content"], "Q2")
        # turn 1's [1] resolves to pmid:333 (turn 1 alloc), NOT pmid:111
        self.assertEqual(
            out[3]["content"],
            "Building on {{cite:pmid:333}} from earlier...",
        )

    def test_does_not_mutate_input(self):
        reg = _build_registry_with_turns([["pmid:111"]])
        messages = [
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": "A [1]"},
        ]
        original = [dict(m) for m in messages]
        rewrite_history_with_placeholders(messages, reg)
        self.assertEqual(messages, original)

    def test_assistant_with_no_content_passes_through(self):
        reg = _build_registry_with_turns([["pmid:111"]])
        messages = [
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "x"}]},
        ]
        out = rewrite_history_with_placeholders(messages, reg)
        self.assertEqual(out[1]["content"], None)
        self.assertEqual(out[1]["tool_calls"], [{"id": "x"}])

    def test_orphan_indices_left_unchanged(self):
        reg = _build_registry_with_turns([["pmid:111"]])
        messages = [
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": "Real [1] orphan [9]."},
        ]
        out = rewrite_history_with_placeholders(messages, reg)
        self.assertEqual(
            out[1]["content"],
            "Real {{cite:pmid:111}} orphan [9].",
        )

    def test_empty_messages(self):
        reg = CitationRegistry()
        self.assertEqual(rewrite_history_with_placeholders([], reg), [])

    def test_assistant_before_any_user(self):
        reg = _build_registry_with_turns([["pmid:111"]])
        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "assistant", "content": "Pre-greeting [1]"},
            {"role": "user", "content": "Q"},
        ]
        out = rewrite_history_with_placeholders(messages, reg)
        # treats pre-user assistant as turn 0
        self.assertEqual(out[1]["content"], "Pre-greeting {{cite:pmid:111}}")

    def test_custom_field_names(self):
        reg = _build_registry_with_turns([["pmid:111"]])
        messages = [
            {"r": "user", "c": "Q"},
            {"r": "assistant", "c": "A [1]"},
        ]
        out = rewrite_history_with_placeholders(
            messages, reg, role_field="r", content_field="c",
        )
        self.assertEqual(out[1]["c"], "A {{cite:pmid:111}}")

    def test_multimodal_content_passes_through(self):
        reg = _build_registry_with_turns([["pmid:111"]])
        messages = [
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": [{"type": "text", "text": "[1]"}]},
        ]
        out = rewrite_history_with_placeholders(messages, reg)
        # list content is left as-is (caller can iterate parts themselves)
        self.assertEqual(out[1]["content"], [{"type": "text", "text": "[1]"}])


if __name__ == "__main__":
    unittest.main()
