import unittest

from citation_kit.registry import CitationRegistry
from citation_kit.types import CitationRecord
from citation_kit.validator import autofix_leaks, validate


def _rec(cite_id, title="T", url="https://example.com/x"):
    return CitationRecord(cite_id=cite_id, title=title, url=url)


class TestValidate(unittest.TestCase):
    def setUp(self):
        self.reg = CitationRegistry()
        self.reg.register_many([_rec("pmid:1"), _rec("pmid:2"), _rec("pmid:3")])
        self.reg.allocate_indices(turn_idx=0, ordered_cite_ids=["pmid:1", "pmid:2", "pmid:3"])

    def test_clean_passes(self):
        text = "Foo [1] bar [2] baz [3]."
        res = validate(text, self.reg, turn_idx=0)
        self.assertTrue(res.ok)

    def test_orphan_numeric(self):
        text = "Foo [1] bar [99]."
        res = validate(text, self.reg, turn_idx=0)
        self.assertFalse(res.ok)
        self.assertIn(99, res.orphan_numeric_refs)

    def test_leaked_placeholder(self):
        text = "Foo [1] bar {{cite:pmid:2}}."
        res = validate(text, self.reg, turn_idx=0)
        self.assertFalse(res.ok)
        self.assertIn("pmid:2", res.leaked_placeholders)

    def test_unused_records(self):
        text = "Foo [1]."
        res = validate(text, self.reg, turn_idx=0)
        self.assertEqual(set(res.unused_records), {"pmid:2", "pmid:3"})

    def test_no_allocation(self):
        text = "[1] [2]"
        res = validate(text, self.reg, turn_idx=999)  # no allocation for this turn
        self.assertEqual(res.orphan_numeric_refs, [])  # can't tell without alloc
        self.assertTrue(res.ok)


class TestAutofix(unittest.TestCase):
    def test_autofix_leaks_known(self):
        reg = CitationRegistry()
        reg.register(_rec("pmid:1", title="Paper", url="https://example.com/x"))
        text = "Foo {{cite:pmid:1}} bar."
        fixed = autofix_leaks(text, reg)
        self.assertIn("Paper", fixed)
        self.assertIn("https://example.com/x", fixed)
        self.assertNotIn("{{cite:", fixed)

    def test_autofix_drops_unknown(self):
        reg = CitationRegistry()
        text = "Foo {{cite:pmid:999}} bar."
        fixed = autofix_leaks(text, reg)
        self.assertNotIn("{{cite:", fixed)
        self.assertEqual(fixed, "Foo  bar.")


if __name__ == "__main__":
    unittest.main()
