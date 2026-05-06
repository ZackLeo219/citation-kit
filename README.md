# citation-kit

Universal citation grounding layer for LLM agents. Decouples synthesis (LLM)
from citation bookkeeping (server). Works with any retrieval API and any
LLM that can preserve a 30-60 char opaque marker character-by-character.

## Why

LLMs writing inline citations have two failure modes:

1. **Chip-style** (`[Title](url "summary")`) — model has to reproduce a 100+
   char string verbatim, often corrupting URLs/titles, dropping
   `## References` sections, or paraphrasing away grounded content.
2. **Numeric** (`[N]`) — model has to maintain index consistency across the
   whole answer, often double-using `[1]`, leaving orphan `[5]` numbers, etc.

Both come from asking the LLM to do **two opposite jobs at once**: creative
synthesis AND mechanical bookkeeping.

`citation-kit` solves this by inverting the contract: **the LLM writes opaque
placeholders, the server does everything else.**

```
LLM writes:    "RTX shows 78% remission {{cite:pmid:24068758}} ..."
Server scans:  found cite_id=pmid:24068758 in registry → assign [1]
Server emits:  "RTX shows 78% remission [1] ..." + auto-generated `## References`
```

## Install

```bash
pip install citation-kit                   # core + 10 retrieval adapters
pip install "citation-kit[postgres]"       # + PostgresStore for prod persistence
```

## Quickstart (single-tool agent)

```python
from citation_kit import CitationRegistry, CitationRenderer
from citation_kit.adapters import tavily as tavily_adapter
from tavily import TavilyClient

registry = CitationRegistry()           # one per thread / conversation
client = TavilyClient(api_key="...")

# 1. Tool wrapper: search → register → embed placeholders into LLM-facing text
def search_tool(query: str) -> str:
    raw = client.search(query, max_results=5)
    parsed = tavily_adapter.parse(raw)
    registry.register_many(parsed.records)
    return "\n\n".join(parsed.snippets)
    # snippets contain: "Title\nsnippet\n[cite this with]: {{cite:url:abc12345}}"

# 2. Run your LLM with `search_tool` exposed; tell it in system prompt:
#    "When citing a fact, copy the {{cite:...}} marker verbatim from the
#    `[cite this with]:` line in the search result. DO NOT write URLs or
#    titles yourself — the server will render them."
llm_output = run_llm(...)
# llm_output: "RTX is effective {{cite:url:abc12345}}, with 78% remission..."

# 3. Render: substitute placeholders + auto-append `## References`
renderer = CitationRenderer(registry, turn_idx=0, mode="numeric")
final = renderer.render(llm_output)
# final: "RTX is effective [1], with 78% remission...\n\n## 参考文献\n1. [...]"
```

## Streaming (SSE-friendly)

```python
async def stream_to_user(llm_chunks):
    async for piece in renderer.render_stream_async(llm_chunks):
        await sse_emit(piece)
    # The footer (`## References`) is yielded as the last chunk before the
    # async iterator closes.
```

The streaming buffer handles placeholders split across chunk boundaries
(`{{ci` + `te:pmid:` + `1}} bar.`).

## Multi-source dedup (PubMed + Semantic Scholar same paper)

```python
from citation_kit.adapters import pubmed, semantic_scholar

# Same paper hit by two APIs
pm_records = pubmed.parse(pubmed_response).records
s2_records = semantic_scholar.parse(s2_response).records

registry.register_many(pm_records)       # registers as doi:10.1038/...
registry.register_many(s2_records)       # SAME doi → idempotent merge
                                         # union of identifiers, prefers richer fields
assert len(registry) == len(set(r.cite_id for r in pm_records + s2_records))
```

`cite_id` is canonical: DOI > PubMed > arXiv > Semantic Scholar > URL hash.
Adapters populate as many identifiers as the API exposes; `pick_cite_id()`
picks the strongest available scheme.

## Multi-agent (parent stitches subagent outputs)

The placeholder protocol means subagents can emit citations independently
without coordinating numbering — server assigns globally consistent `[N]`
at parent's stitch time:

```python
# Each subagent registers into a shared per-thread registry
sub_a_output = "...{{cite:pmid:111}}..."   # subagent A's findings
sub_b_output = "...{{cite:pmid:222}}..."   # subagent B's findings

# Parent stitches with no re-numbering work
combined = sub_a_output + "\n\n" + sub_b_output
final = CitationRenderer(registry, turn_idx=0).render(combined)
# pmid:111 → [1], pmid:222 → [2]
```

## Persistence backends

```python
from citation_kit import InMemoryStore, JSONFileStore  # built-in
from citation_kit.stores import PostgresStore           # requires asyncpg

# Load existing registry on thread reopen:
data = await store.aload(thread_id)
registry = CitationRegistry.from_serializable(data)

# Save after each turn:
await store.asave(thread_id, registry.to_serializable())
```

Custom backend: implement the `RegistryStore` protocol (3 async methods).
Typical for LangGraph users: wrap your checkpointer in a thin adapter so
no double-write occurs.

## Adapters

10 retrieval APIs. Each has a single `parse(raw_response) -> ParseResult`
function returning normalized `CitationRecord` + LLM-facing snippets.

| API | Module | Identifier source |
|-----|--------|-------------------|
| Tavily | `tavily` | URL hash |
| Exa | `exa` | URL hash |
| Brave Search | `brave` | URL hash |
| Serper (Google) | `serper` | URL hash |
| PubMed (E-utilities) | `pubmed` | PMID, DOI |
| Semantic Scholar | `semantic_scholar` | DOI, PMID, arXiv, S2 paperId |
| arXiv | `arxiv` | arXiv ID, DOI |
| Crossref | `crossref` | DOI |
| OpenAlex | `openalex` | DOI, PMID, OpenAlex ID |
| Europe PMC | `europepmc` | DOI, PMID |

## LLM prompt template

```
当你需要引用文献时,**只复制**搜索结果中 `[cite this with]:` 行后的占位符
(形如 `{{cite:doi:10.x/y}}`),一字符不改。

**禁止**自己写 URL、标题或参考文献编号 — 系统会自动展开为可点击链接 + 末尾
参考文献列表。
```

## Validation

```python
from citation_kit import validate, autofix_leaks

result = validate(rendered_text, registry, turn_idx=0)
if not result.ok:
    log.warning("citation issues: %s", result.summary())
    # Auto-fix any leaked placeholders before sending to user
    rendered_text = autofix_leaks(rendered_text, registry)
```

Detects: leaked `{{cite:...}}`, orphan `[N]` not in references, unused
records, duplicate index assignments.

## Tests

```bash
python -m unittest discover -s citation_kit/tests -v
```

89 tests covering canonicalization, registry semantics, streaming buffer
edge cases, validator paths, all 10 adapters, and cross-source dedup.

## License

MIT.
