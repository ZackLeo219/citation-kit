import unittest

from citation_kit.registry import CitationRegistry
from citation_kit.renderer import CitationRenderer
from citation_kit.types import CitationRecord


def _rec(cite_id, title="T", url="https://example.com/x"):
    return CitationRecord(cite_id=cite_id, title=title, url=url, abstract="abs")


class TestNumericRender(unittest.TestCase):
    def test_basic(self):
        reg = CitationRegistry()
        reg.register_many([_rec("pmid:1"), _rec("pmid:2")])
        r = CitationRenderer(reg, turn_idx=0, mode="numeric")
        out = r.render("Foo {{cite:pmid:1}} bar {{cite:pmid:2}} baz {{cite:pmid:1}}.")
        self.assertIn("Foo [1] bar [2] baz [1].", out)
        self.assertIn("## 参考文献", out)
        self.assertIn("1. ", out)
        self.assertIn("2. ", out)

    def test_unknown_placeholder(self):
        reg = CitationRegistry()
        reg.register(_rec("pmid:1"))
        r = CitationRenderer(reg, turn_idx=0, mode="numeric")
        out = r.render("Foo {{cite:pmid:1}} bar {{cite:pmid:999}}.")
        # unknown one becomes [?...?]
        self.assertIn("[1]", out)
        self.assertIn("[?", out)

    def test_no_refs_section_when_none_cited(self):
        reg = CitationRegistry()
        reg.register(_rec("pmid:1"))
        r = CitationRenderer(reg, turn_idx=0, mode="numeric")
        out = r.render("No citations in this text.")
        self.assertNotIn("## 参考文献", out)


class TestChipRender(unittest.TestCase):
    def test_basic(self):
        reg = CitationRegistry()
        reg.register(_rec("pmid:1", title="Cool paper", url="https://example.com/p"))
        r = CitationRenderer(reg, turn_idx=0, mode="chip")
        out = r.render("Hello {{cite:pmid:1}}.")
        self.assertIn("(https://example.com/p", out)
        self.assertIn("Cool paper", out)

    def test_doi_id_preserved(self):
        reg = CitationRegistry()
        reg.register(_rec("doi:10.1038/abc", title="Paper", url="https://doi.org/10.1038/abc"))
        r = CitationRenderer(reg, turn_idx=0, mode="chip")
        out = r.render("Cite {{cite:doi:10.1038/abc}}.")
        self.assertIn("doi.org", out)


class TestStreamingRender(unittest.TestCase):
    def test_chunks_split_inside_placeholder(self):
        reg = CitationRegistry()
        reg.register(_rec("pmid:1"))
        r = CitationRenderer(reg, turn_idx=0, mode="numeric", append_references=False)
        # The placeholder is split across chunks
        chunks = ["Foo {{ci", "te:pmid:", "1}} bar."]
        rendered = "".join(r.render_stream(iter(chunks)))
        self.assertEqual(rendered, "Foo [1] bar.")

    def test_multiple_placeholders_streaming(self):
        reg = CitationRegistry()
        reg.register_many([_rec("pmid:1"), _rec("pmid:2")])
        r = CitationRenderer(reg, turn_idx=0, mode="numeric", append_references=False)
        chunks = ["X {{cite:pmid:1}} Y {{cite:pmid:2}} Z {{cite:pmid:1}}"]
        rendered = "".join(r.render_stream(iter(chunks)))
        self.assertEqual(rendered, "X [1] Y [2] Z [1]")

    def test_partial_open_at_end(self):
        reg = CitationRegistry()
        reg.register(_rec("pmid:1"))
        r = CitationRenderer(reg, turn_idx=0, mode="numeric", append_references=False)
        # Last chunk has half-open `{{` — should be flushed as literal
        chunks = ["text {{"]
        rendered = "".join(r.render_stream(iter(chunks)))
        self.assertEqual(rendered, "text {{")

    def test_streaming_then_footer(self):
        reg = CitationRegistry()
        reg.register(_rec("pmid:1", title="Paper", url="https://a/b"))
        r = CitationRenderer(reg, turn_idx=0, mode="numeric")
        chunks = ["Hello {{cite:pmid:1}}!"]
        out = "".join(r.render_stream(iter(chunks)))
        self.assertIn("Hello [1]!", out)
        self.assertIn("## 参考文献", out)
        self.assertIn("1. ", out)


class TestFeedFlush(unittest.TestCase):
    """Incremental `feed()` / `flush()` API for callers that own their own loop."""

    def test_basic_feed(self):
        reg = CitationRegistry()
        reg.register(_rec("pmid:1"))
        r = CitationRenderer(reg, turn_idx=0, mode="numeric", append_references=False)
        out = r.feed("Hello {{cite:pmid:1}} world.")
        out += r.flush()
        self.assertEqual(out, "Hello [1] world.")

    def test_feed_split_chunks(self):
        reg = CitationRegistry()
        reg.register(_rec("pmid:1"))
        r = CitationRenderer(reg, turn_idx=0, mode="numeric", append_references=False)
        parts = []
        for chunk in ["A {{ci", "te:pmid:", "1}} B"]:
            parts.append(r.feed(chunk))
        parts.append(r.flush())
        self.assertEqual("".join(parts), "A [1] B")

    def test_references_section(self):
        reg = CitationRegistry()
        reg.register(_rec("pmid:1", title="Paper", url="https://a/b"))
        r = CitationRenderer(reg, turn_idx=0, mode="numeric", append_references=False)
        r.feed("Hello {{cite:pmid:1}}")
        r.flush()
        refs = r.references_section()
        self.assertIn("## 参考文献", refs)
        self.assertIn("1. ", refs)

    def test_empty_refs_section(self):
        reg = CitationRegistry()
        r = CitationRenderer(reg, turn_idx=0, mode="numeric")
        r.feed("nothing here")
        r.flush()
        self.assertEqual(r.references_section(), "")


class TestAsyncStreaming(unittest.IsolatedAsyncioTestCase):
    async def test_async_basic(self):
        reg = CitationRegistry()
        reg.register(_rec("pmid:1"))
        r = CitationRenderer(reg, turn_idx=0, mode="numeric", append_references=False)

        async def gen():
            for c in ["A {{cite:", "pmid:1}} B"]:
                yield c

        parts = []
        async for chunk in r.render_stream_async(gen()):
            parts.append(chunk)
        self.assertEqual("".join(parts), "A [1] B")


if __name__ == "__main__":
    unittest.main()
