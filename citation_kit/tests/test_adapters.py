"""Adapter parsing tests with realistic API response fixtures."""
import unittest

from citation_kit.adapters import (
    arxiv as arxiv_adapter,
    brave as brave_adapter,
    crossref as crossref_adapter,
    europepmc as europepmc_adapter,
    exa as exa_adapter,
    openalex as openalex_adapter,
    pubmed as pubmed_adapter,
    semantic_scholar as s2_adapter,
    serper as serper_adapter,
    tavily as tavily_adapter,
)


class TestTavily(unittest.TestCase):
    def test_basic(self):
        raw = {
            "results": [
                {"title": "T1", "url": "https://example.com/a", "content": "snippet a", "score": 0.9},
                {"title": "T2", "url": "https://example.com/b", "content": "snippet b"},
            ]
        }
        out = tavily_adapter.parse(raw)
        self.assertEqual(len(out.records), 2)
        self.assertEqual(out.records[0].source_tool, "tavily")
        self.assertTrue(out.records[0].cite_id.startswith("url:"))
        self.assertIn("{{cite:", out.snippets[0])

    def test_drops_empty_url(self):
        raw = {"results": [{"title": "T", "url": ""}, {"title": "T2", "url": "https://x.com/a"}]}
        self.assertEqual(len(tavily_adapter.parse(raw).records), 1)


class TestExa(unittest.TestCase):
    def test_basic(self):
        raw = {
            "results": [
                {
                    "title": "Paper",
                    "url": "https://example.org/paper",
                    "publishedDate": "2024-03-15",
                    "author": "Smith J",
                    "text": "abstract text here",
                }
            ]
        }
        out = exa_adapter.parse(raw)
        self.assertEqual(len(out.records), 1)
        self.assertEqual(out.records[0].year, 2024)
        self.assertEqual(out.records[0].authors, ("Smith J",))


class TestBrave(unittest.TestCase):
    def test_with_web_wrapper(self):
        raw = {
            "web": {
                "results": [
                    {"title": "T", "url": "https://x/a", "description": "d", "page_age": "2024-01-15"}
                ]
            }
        }
        out = brave_adapter.parse(raw)
        self.assertEqual(len(out.records), 1)
        self.assertEqual(out.records[0].year, 2024)

    def test_unwrapped(self):
        raw = {"results": [{"title": "T", "url": "https://x/b", "description": "d"}]}
        out = brave_adapter.parse(raw)
        self.assertEqual(len(out.records), 1)


class TestSerper(unittest.TestCase):
    def test_basic(self):
        raw = {
            "organic": [
                {"title": "Result 1", "link": "https://x/1", "snippet": "...", "position": 1},
                {"title": "Result 2", "link": "https://x/2", "snippet": "..."},
            ]
        }
        out = serper_adapter.parse(raw)
        self.assertEqual(len(out.records), 2)
        self.assertEqual(out.records[0].source_tool, "serper")


class TestPubmedSimpleDict(unittest.TestCase):
    def test_with_pmid_only(self):
        raw = [{"pmid": "12345678", "title": "Paper", "abstract": "a", "authors": ["Smith J"], "year": 2024, "journal": "Nature"}]
        out = pubmed_adapter.parse(raw)
        self.assertEqual(len(out.records), 1)
        self.assertEqual(out.records[0].cite_id, "pmid:12345678")
        self.assertEqual(out.records[0].venue, "Nature")

    def test_doi_takes_priority(self):
        raw = [{"pmid": "12345678", "doi": "10.1038/x", "title": "T"}]
        out = pubmed_adapter.parse(raw)
        self.assertEqual(out.records[0].cite_id, "doi:10.1038/x")
        self.assertEqual(out.records[0].identifiers, {"pmid": "12345678", "doi": "10.1038/x"})

    def test_drops_no_identifier(self):
        raw = [{"title": "no ids"}]
        self.assertEqual(len(pubmed_adapter.parse(raw).records), 0)


class TestPubmedEntrez(unittest.TestCase):
    def test_entrez_nested(self):
        raw = {
            "PubmedArticle": [
                {
                    "MedlineCitation": {
                        "PMID": "98765432",
                        "Article": {
                            "ArticleTitle": "Nested Paper",
                            "Abstract": {"AbstractText": ["This is the abstract."]},
                            "Journal": {
                                "Title": "JAMA",
                                "JournalIssue": {"PubDate": {"Year": "2023"}},
                            },
                            "AuthorList": [
                                {"LastName": "Doe", "Initials": "J"},
                                {"LastName": "Smith", "Initials": "A"},
                            ],
                            "ELocationID": [{"EIdType": "doi", "value": "10.1001/jama.2023.123"}],
                        },
                    }
                }
            ]
        }
        out = pubmed_adapter.parse(raw)
        self.assertEqual(len(out.records), 1)
        rec = out.records[0]
        self.assertEqual(rec.cite_id, "doi:10.1001/jama.2023.123")
        self.assertEqual(rec.title, "Nested Paper")
        self.assertIn("Doe J", rec.authors)
        self.assertEqual(rec.year, 2023)


class TestSemanticScholar(unittest.TestCase):
    def test_doi_preferred(self):
        raw = {
            "data": [
                {
                    "paperId": "abc123",
                    "title": "S2 Paper",
                    "abstract": "abs",
                    "year": 2024,
                    "authors": [{"name": "Smith J"}, {"name": "Doe A"}],
                    "venue": "ICML",
                    "externalIds": {"DOI": "10.1/y", "PubMed": "12345", "ArXiv": "2401.12345"},
                    "url": "https://www.semanticscholar.org/paper/abc123",
                }
            ]
        }
        out = s2_adapter.parse(raw)
        self.assertEqual(len(out.records), 1)
        rec = out.records[0]
        self.assertEqual(rec.cite_id, "doi:10.1/y")
        self.assertEqual(rec.identifiers["pmid"], "12345")
        self.assertEqual(rec.identifiers["arxiv"], "2401.12345")
        self.assertEqual(rec.authors, ("Smith J", "Doe A"))

    def test_only_s2_id(self):
        raw = {"data": [{"paperId": "xyz", "title": "T", "externalIds": {}}]}
        out = s2_adapter.parse(raw)
        self.assertEqual(out.records[0].cite_id, "s2:xyz")


class TestArxivDictForm(unittest.TestCase):
    def test_basic(self):
        raw = {
            "results": [
                {
                    "entry_id": "https://arxiv.org/abs/2401.12345v2",
                    "title": "Arxiv Paper",
                    "summary": "abstract",
                    "published": "2024-01-15T00:00:00Z",
                    "authors": [{"name": "Smith J"}, {"name": "Doe A"}],
                    "doi": "10.1/x",
                }
            ]
        }
        out = arxiv_adapter.parse(raw)
        self.assertEqual(len(out.records), 1)
        rec = out.records[0]
        self.assertEqual(rec.cite_id, "doi:10.1/x")
        self.assertEqual(rec.identifiers["arxiv"], "2401.12345")

    def test_no_doi(self):
        raw = [{"entry_id": "2401.99999", "title": "T", "summary": "s", "published": "2024", "authors": ["Smith J"]}]
        out = arxiv_adapter.parse(raw)
        self.assertEqual(out.records[0].cite_id, "arxiv:2401.99999")


class TestCrossref(unittest.TestCase):
    def test_full_response(self):
        raw = {
            "message": {
                "items": [
                    {
                        "DOI": "10.1038/s41591-024-12345",
                        "title": ["Crossref Paper"],
                        "abstract": "<jats:p>This is the abstract.</jats:p>",
                        "author": [{"given": "Jane", "family": "Smith"}],
                        "container-title": ["Nature Medicine"],
                        "issued": {"date-parts": [[2024, 3, 15]]},
                        "URL": "https://doi.org/10.1038/s41591-024-12345",
                    }
                ]
            }
        }
        out = crossref_adapter.parse(raw)
        self.assertEqual(len(out.records), 1)
        rec = out.records[0]
        self.assertEqual(rec.cite_id, "doi:10.1038/s41591-024-12345")
        self.assertEqual(rec.title, "Crossref Paper")
        self.assertEqual(rec.venue, "Nature Medicine")
        self.assertEqual(rec.year, 2024)
        self.assertNotIn("<jats:p>", rec.abstract)

    def test_single_doi_lookup(self):
        # GET /works/{doi} returns message=<single-item> not message=<items=[...]>
        raw = {"message": {"DOI": "10.1/x", "title": ["T"]}}
        out = crossref_adapter.parse(raw)
        self.assertEqual(len(out.records), 1)


class TestOpenAlex(unittest.TestCase):
    def test_basic(self):
        raw = {
            "results": [
                {
                    "id": "https://openalex.org/W123",
                    "doi": "https://doi.org/10.1/x",
                    "title": "OA Paper",
                    "publication_year": 2024,
                    "authorships": [{"author": {"display_name": "Smith J"}}],
                    "host_venue": {"display_name": "Nature"},
                    "abstract_inverted_index": {"This": [0], "is": [1], "abstract.": [2]},
                    "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/99999"},
                }
            ]
        }
        out = openalex_adapter.parse(raw)
        self.assertEqual(len(out.records), 1)
        rec = out.records[0]
        self.assertEqual(rec.cite_id, "doi:10.1/x")
        self.assertEqual(rec.identifiers["pmid"], "99999")
        self.assertEqual(rec.abstract, "This is abstract.")
        self.assertEqual(rec.year, 2024)


class TestEuropePMC(unittest.TestCase):
    def test_basic(self):
        raw = {
            "resultList": {
                "result": [
                    {
                        "id": "12345",
                        "source": "MED",
                        "pmid": "12345",
                        "doi": "10.1/x",
                        "title": "EPMC Paper",
                        "abstractText": "abstract here",
                        "authorString": "Smith J, Doe A.",
                        "journalTitle": "Nature",
                        "pubYear": "2024",
                    }
                ]
            }
        }
        out = europepmc_adapter.parse(raw)
        self.assertEqual(len(out.records), 1)
        rec = out.records[0]
        self.assertEqual(rec.cite_id, "doi:10.1/x")
        self.assertEqual(rec.authors, ("Smith J", "Doe A"))
        self.assertEqual(rec.year, 2024)


class TestCrossSourceDedup(unittest.TestCase):
    """Same paper from PubMed + Semantic Scholar → registered as one entry."""
    def test_dedup_by_doi(self):
        from citation_kit.registry import CitationRegistry

        pm_raw = [{"pmid": "12345", "doi": "10.1038/x", "title": "Pub Med Title", "abstract": "pm abs"}]
        s2_raw = {
            "data": [{
                "paperId": "abc", "title": "S2 Title",
                "externalIds": {"DOI": "10.1038/x"},
                "abstract": "s2 abs",
                "authors": [{"name": "Smith J"}],
            }]
        }
        pm_out = pubmed_adapter.parse(pm_raw)
        s2_out = s2_adapter.parse(s2_raw)
        reg = CitationRegistry()
        reg.register_many(pm_out.records)
        reg.register_many(s2_out.records)
        self.assertEqual(len(reg), 1)  # deduped via doi:10.1038/x
        merged = reg.get("doi:10.1038/x")
        # title kept from first registration (PubMed); authors filled in from S2
        self.assertEqual(merged.title, "Pub Med Title")
        self.assertEqual(merged.authors, ("Smith J",))


if __name__ == "__main__":
    unittest.main()
