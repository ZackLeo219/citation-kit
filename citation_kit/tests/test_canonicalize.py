import unittest

from citation_kit.canonicalize import (
    canonical_url_for,
    canonicalize_url,
    normalize_arxiv_id,
    normalize_doi,
    normalize_pmid,
    pick_cite_id,
    url_hash,
)


class TestNormalizeDoi(unittest.TestCase):
    def test_bare_doi(self):
        self.assertEqual(normalize_doi("10.1038/s41591-024-12345"), "10.1038/s41591-024-12345")

    def test_doi_url(self):
        self.assertEqual(normalize_doi("https://doi.org/10.1038/s41591-024-12345"),
                         "10.1038/s41591-024-12345")

    def test_dx_doi_url(self):
        self.assertEqual(normalize_doi("http://dx.doi.org/10.1038/X"), "10.1038/x")

    def test_lowercase(self):
        self.assertEqual(normalize_doi("10.1038/SOMETHING"), "10.1038/something")

    def test_strip_trailing_punct(self):
        self.assertEqual(normalize_doi("10.1234/abc.;"), "10.1234/abc")

    def test_invalid(self):
        self.assertIsNone(normalize_doi(""))
        self.assertIsNone(normalize_doi("no-doi-here"))
        self.assertIsNone(normalize_doi("10.junk"))


class TestNormalizePmid(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(normalize_pmid("12345678"), "12345678")
        self.assertEqual(normalize_pmid(12345678), "12345678")

    def test_zero_rejected(self):
        self.assertIsNone(normalize_pmid("0"))

    def test_non_numeric(self):
        self.assertIsNone(normalize_pmid("PMID12345"))
        self.assertIsNone(normalize_pmid(""))
        self.assertIsNone(normalize_pmid(None))


class TestNormalizeArxiv(unittest.TestCase):
    def test_new_style(self):
        self.assertEqual(normalize_arxiv_id("2401.12345"), "2401.12345")
        self.assertEqual(normalize_arxiv_id("2401.12345v3"), "2401.12345")

    def test_old_style(self):
        self.assertEqual(normalize_arxiv_id("hep-th/9901001"), "hep-th/9901001")
        self.assertEqual(normalize_arxiv_id("hep-th/9901001v2"), "hep-th/9901001")

    def test_url(self):
        self.assertEqual(normalize_arxiv_id("https://arxiv.org/abs/2401.12345"), "2401.12345")
        self.assertEqual(normalize_arxiv_id("https://arxiv.org/pdf/2401.12345.pdf"), "2401.12345")

    def test_invalid(self):
        self.assertIsNone(normalize_arxiv_id(""))
        self.assertIsNone(normalize_arxiv_id("not-an-id"))


class TestCanonicalizeUrl(unittest.TestCase):
    def test_lowercase_host(self):
        self.assertEqual(canonicalize_url("HTTPS://Example.COM/path"), "https://example.com/path")

    def test_drop_default_port(self):
        self.assertEqual(canonicalize_url("https://example.com:443/x"), "https://example.com/x")
        self.assertEqual(canonicalize_url("http://example.com:80/x"), "http://example.com/x")

    def test_drop_tracking(self):
        u = canonicalize_url("https://example.com/p?utm_source=x&id=42&fbclid=abc")
        self.assertEqual(u, "https://example.com/p?id=42")

    def test_sort_query(self):
        u = canonicalize_url("https://example.com/p?b=2&a=1")
        self.assertEqual(u, "https://example.com/p?a=1&b=2")

    def test_drop_fragment(self):
        self.assertEqual(canonicalize_url("https://example.com/p#section"), "https://example.com/p")

    def test_strip_trailing_slash(self):
        self.assertEqual(canonicalize_url("https://example.com/x/"), "https://example.com/x")

    def test_root_keeps_slash(self):
        self.assertEqual(canonicalize_url("https://example.com/"), "https://example.com/")

    def test_url_hash_stable(self):
        h1 = url_hash("https://example.com/p?utm_source=foo")
        h2 = url_hash("https://example.com/p")
        self.assertEqual(h1, h2)


class TestPickCiteId(unittest.TestCase):
    def test_doi_wins(self):
        cid = pick_cite_id({"doi": "10.1/x", "pmid": "12345", "url": "https://example.com"})
        self.assertEqual(cid, "doi:10.1/x")

    def test_pmid_when_no_doi(self):
        self.assertEqual(pick_cite_id({"pmid": "12345"}), "pmid:12345")

    def test_arxiv_when_no_doi_or_pmid(self):
        self.assertEqual(pick_cite_id({"arxiv": "2401.12345"}), "arxiv:2401.12345")

    def test_url_fallback(self):
        cid = pick_cite_id({"url": "https://example.com/p"})
        self.assertTrue(cid.startswith("url:"))
        self.assertEqual(len(cid), len("url:") + 8)

    def test_raises_when_no_identifiers(self):
        with self.assertRaises(ValueError):
            pick_cite_id({})

    def test_raises_when_invalid_only(self):
        with self.assertRaises(ValueError):
            pick_cite_id({"doi": "not-a-doi", "pmid": "abc"})


class TestCanonicalUrlFor(unittest.TestCase):
    def test_doi_url(self):
        self.assertEqual(canonical_url_for({"doi": "10.1/x"}), "https://doi.org/10.1/x")

    def test_pmid_url(self):
        self.assertEqual(canonical_url_for({"pmid": "12345"}),
                         "https://pubmed.ncbi.nlm.nih.gov/12345/")

    def test_arxiv_url(self):
        self.assertEqual(canonical_url_for({"arxiv": "2401.12345"}),
                         "https://arxiv.org/abs/2401.12345")

    def test_fallback(self):
        self.assertEqual(canonical_url_for({}, "https://example.com/x"), "https://example.com/x")


if __name__ == "__main__":
    unittest.main()
