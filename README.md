# citation-kit

Universal citation grounding layer for LLM agents. Decouples synthesis (LLM)
from citation bookkeeping (server). Works with any retrieval API and any
LLM that can preserve a 30-60 char opaque marker character-by-character.

> **v0.2.0** is out (see [CHANGELOG](CHANGELOG.md)) — adds multi-turn
> conversation support (`rewrite_history_with_placeholders()`),
> `SQLiteStore` (stdlib, no extras) + `RedisStore`, optimistic locking
> on all DB backends, and reference integrations for LangGraph /
> SQLAlchemy / `conversations.metadata`-JSONB.

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
pip install citation-kit                       # core + 10 retrieval adapters + sqlite/json/memory stores
pip install "citation-kit[postgres]"           # + asyncpg-backed PostgresStore
pip install "citation-kit[redis]"              # + RedisStore (sub-ms, distributed)
pip install "citation-kit[all]"                # + both prod backends
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

## Multi-turn (registry persisted across turns)

Single-turn citation grounding (everything above) works in any agent. But
real conversations span multiple turns — and there's a subtle trap: after
turn 1 the user-facing text contains substituted `[N]` markers, and most
frontends store + POST that rendered text back as conversation history. On
turn 2 the LLM sees `[N]` markers in history and (often) starts copying
that pattern instead of writing fresh `{{cite:...}}` placeholders, leaving
orphan numeric refs and an empty references section.

Fix is two parts:

**1. Persist the registry across turns** (any backend works):

```python
from citation_kit import CitationRegistry, CitationRenderer
from citation_kit.stores import SQLiteStore  # or PostgresStore / RedisStore

store = SQLiteStore("./registry.db")

# At the start of each turn:
data = await store.aload(conversation_id)
registry = CitationRegistry.from_serializable(data)

# ... run turn ...

# At the end of each turn:
await store.asave(conversation_id, registry.to_serializable())
```

**2. Rewrite history before sending to the LLM** so it sees a consistent
placeholder protocol throughout — `[N]` markers in past assistant messages
get reverse-mapped to `{{cite:cite_id}}`:

```python
from citation_kit import rewrite_history_with_placeholders

# `prior_messages` from the frontend has [N] markers in assistant content.
# `registry` was loaded from store with all past turn allocations intact.
history = rewrite_history_with_placeholders(prior_messages, registry)

# Now feed `history` to your LLM. It sees `{{cite:...}}` everywhere
# (current-turn tool results AND past assistant outputs) and continues
# writing placeholders.
```

Without step 2, the LLM still sees mixed `[N]` (history) + `{{cite:...}}`
(current tool results), and most models will copy whichever pattern is more
prominent in their context — usually `[N]` from a long history.

## Persistence backends

5 backends ship in the box. Pick by deployment shape — see
[BACKENDS.md](BACKENDS.md) for the full decision tree:

| Backend | Setup | When |
|---------|-------|------|
| `InMemoryStore` | none | testing, one-shot |
| `JSONFileStore` | mkdir | dev / single-machine |
| `SQLiteStore` | one path | embedded persistence (stdlib, no extras) |
| `PostgresStore` | DSN | production, distributed (`pip install citation-kit[postgres]`) |
| `RedisStore` | URL | production, sub-ms (`pip install citation-kit[redis]`) |

`SQLiteStore` / `PostgresStore` / `RedisStore` also expose
`aload_with_version` + `asave_with_version` for compare-and-swap (use when
multiple workers may write the same `scope_id`).

Custom backend: implement the 3-method `RegistryStore` protocol. Reference
implementations under `citation_kit/integrations/` for LangGraph
checkpointer state, SQLAlchemy 2.0 async, and the
`conversations.metadata`-JSONB embedding pattern.

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

The agent's system prompt should make the placeholder protocol explicit.
Both flavors below carry the same contract — pick whichever language matches
your model and user base.

### English

```
## Citing sources

When you need to cite a fact you got from a search tool, copy the
placeholder marker from the `[cite this with]:` line of that result
**verbatim, character-for-character**.

  Example marker:  {{cite:doi:10.1038/s41591-024-12345}}
  Example sentence: "RTX shows ~78% complete remission {{cite:doi:10.1038/s41591-024-12345}}."

**Do NOT**:
- Write URLs, titles, authors, or DOI strings yourself
- Number the citations yourself (no `[1]`, `[2]`, ...)
- Write a `## References` / `## Bibliography` section yourself
- Paraphrase, shorten, or "clean up" the marker — even a single character
  change breaks the binding

The server will automatically:
- Expand each marker into a numbered `[N]` (or styled chip, depending on
  configuration)
- Append a single deduplicated `## References` section at the end of your
  answer with one line per cited source

If you didn't see a `[cite this with]:` line for a fact, you cannot cite
it — say so, or call the search tool again to get a citable source.
```

### 中文

```
## 引用文献的规则

当你引用一个来自搜索工具的事实时,把工具返回结果里 `[cite this with]:`
行后面的占位符**一字符不漏地原样复制**到正文中。

  占位符示例:  {{cite:doi:10.1038/s41591-024-12345}}
  正文示例:    "RTX 完全缓解率约 78%{{cite:doi:10.1038/s41591-024-12345}}。"

**禁止**:
- 自己写 URL、标题、作者、DOI 字符串
- 自己给引用编号(不要写 `[1]`、`[2]`……)
- 自己写 `## 参考文献` / `## References` 段落
- 改写、缩写、"美化"占位符 —— 改一个字符就会破坏绑定

服务端会**自动**:
- 把每个占位符展开成 `[N]`(或药丸样式,取决于配置)
- 在你回答末尾自动追加一段去重后的 `## 参考文献`,每行一条来源

如果某个事实**没有**对应的 `[cite this with]:` 行,你就不能引用它 ——
说明无来源,或者再调一次搜索工具拿到可引用的来源。
```

> Both templates assume your tool wrappers emit snippets in the format
> produced by `citation_kit.adapters.base.build_snippet()` (which always
> ends with a `[cite this with]: {{cite:...}}` line). If your wrapper uses
> a different convention, swap the line that says where to look.

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
