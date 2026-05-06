import unittest

from citation_kit.registry import CitationRegistry
from citation_kit.types import CitationRecord


def _rec(cite_id="pmid:1", title="T", url="https://example.com", **kw):
    return CitationRecord(cite_id=cite_id, title=title, url=url, **kw)


class TestRegistryBasics(unittest.TestCase):
    def test_register_returns_id(self):
        r = CitationRegistry()
        rec = _rec()
        self.assertEqual(r.register(rec), "pmid:1")
        self.assertEqual(len(r), 1)
        self.assertIn("pmid:1", r)

    def test_register_many(self):
        r = CitationRegistry()
        ids = r.register_many([_rec("pmid:1"), _rec("pmid:2"), _rec("pmid:3")])
        self.assertEqual(ids, ["pmid:1", "pmid:2", "pmid:3"])
        self.assertEqual(len(r), 3)

    def test_idempotent_same_id(self):
        r = CitationRegistry()
        r.register(_rec("pmid:1", title="A", url=""))
        r.register(_rec("pmid:1", title="", url="https://example.com"))
        rec = r.get("pmid:1")
        # Merge: keep non-empty title from first, fill in url from second
        self.assertEqual(rec.title, "A")
        self.assertEqual(rec.url, "https://example.com")
        self.assertEqual(len(r), 1)

    def test_merge_identifiers_union(self):
        r = CitationRegistry()
        r.register(_rec("pmid:1", identifiers={"pmid": "1"}))
        r.register(_rec("pmid:1", identifiers={"doi": "10.1/x"}))
        rec = r.get("pmid:1")
        self.assertEqual(rec.identifiers, {"pmid": "1", "doi": "10.1/x"})


class TestPlaceholderScan(unittest.TestCase):
    def test_scan_basic(self):
        r = CitationRegistry()
        r.register(_rec("pmid:1"))
        r.register(_rec("pmid:2"))
        text = "First {{cite:pmid:1}} then {{cite:pmid:2}} again {{cite:pmid:1}}."
        self.assertEqual(r.scan_placeholders(text), ["pmid:1", "pmid:2"])

    def test_drops_unknown(self):
        r = CitationRegistry()
        r.register(_rec("pmid:1"))
        text = "Real {{cite:pmid:1}} fake {{cite:pmid:999}}."
        self.assertEqual(r.scan_placeholders(text), ["pmid:1"])

    def test_doi_with_slash(self):
        r = CitationRegistry()
        r.register(_rec("doi:10.1038/x"))
        text = "Cite {{cite:doi:10.1038/x}}."
        self.assertEqual(r.scan_placeholders(text), ["doi:10.1038/x"])

    def test_empty(self):
        r = CitationRegistry()
        self.assertEqual(r.scan_placeholders("no placeholders here"), [])


class TestAllocateIndices(unittest.TestCase):
    def test_sequential(self):
        r = CitationRegistry()
        r.register_many([_rec("pmid:1"), _rec("pmid:2"), _rec("pmid:3")])
        idx = r.allocate_indices(turn_idx=0, ordered_cite_ids=["pmid:2", "pmid:1", "pmid:3"])
        self.assertEqual(idx, {"pmid:2": 1, "pmid:1": 2, "pmid:3": 3})

    def test_alloc_persists(self):
        r = CitationRegistry()
        r.register(_rec("pmid:1"))
        r.allocate_indices(turn_idx=5, ordered_cite_ids=["pmid:1"])
        alloc = r.get_turn_allocation(5)
        self.assertIsNotNone(alloc)
        self.assertEqual(alloc.index_map, {"pmid:1": 1})


class TestSerialization(unittest.TestCase):
    def test_round_trip(self):
        r = CitationRegistry()
        r.register(_rec("pmid:1", title="Paper 1", authors=("Smith J", "Doe A"), year=2024))
        r.register(_rec("doi:10.1/x", title="Paper 2"))
        r.allocate_indices(turn_idx=0, ordered_cite_ids=["pmid:1"])
        r.allocate_indices(turn_idx=1, ordered_cite_ids=["pmid:1", "doi:10.1/x"])

        data = r.to_serializable()
        r2 = CitationRegistry.from_serializable(data)
        self.assertEqual(len(r2), 2)
        self.assertEqual(r2.get("pmid:1").authors, ("Smith J", "Doe A"))
        self.assertEqual(r2.get_turn_allocation(0).index_map, {"pmid:1": 1})
        self.assertEqual(r2.get_turn_allocation(1).index_map, {"pmid:1": 1, "doi:10.1/x": 2})

    def test_empty_round_trip(self):
        r = CitationRegistry.from_serializable(None)
        self.assertEqual(len(r), 0)
        r2 = CitationRegistry.from_serializable({})
        self.assertEqual(len(r2), 0)


if __name__ == "__main__":
    unittest.main()
