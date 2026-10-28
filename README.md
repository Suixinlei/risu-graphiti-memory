# risu-graphiti-memory

Long-term memory layer for [RisuAI](https://risuai.net) backed by a
[Graphiti](https://github.com/getzep/graphiti) temporal knowledge graph.

Designed for long roleplay chats where rolling summaries lose the plot: it
tracks **how relationships, promises and states changed over time** (with
validity windows — superseded facts are marked, not deleted) and recalls
relevant facts into the prompt before each generation.

```
RisuAI plugin ──beforeRequest──▶ sidecar /search ──▶ Neo4j (temporal KG)
    │                                │                   ▲
    └──afterRequest──▶ sidecar /episode (async) ──────────┘
                            │
                            ├─ LLM: any OpenAI-compatible endpoint
                            │  (e.g. GLM-5.3-flash with thinking disabled)
                            └─ Embedder: any multilingual OpenAI-compatible
                               embedding endpoint (e.g. qwen3 text-embedding)
```

RisuAI itself is not modified: everything happens through the plugin
`addRisuReplacer('beforeRequest' / 'afterRequest')` hooks.

## Features

- **Temporal facts** — "X promised Y" that later got cancelled is marked
  `[已失效/invalid]`, not forgotten; the prompt injection labels them so the
  model understands the change history.
- **Card-agnostic** — a generic bilingual narrative ontology (Character /
  Event / Item / Location / Organization / Concept); no per-card hardcoding.
- **Separation of concerns** — numeric current state stays in your variable
  system; this layer answers *when/why it changed* and *what happened*.
- **Failure-isolated** — every sidecar call is wrapped; if the sidecar is
  down the chat continues untouched.
- **Cursor-guarded ingestion** — new installs ingest from the current turn;
  history ingestion is an explicit, resumable offline tool.

## Setup

### 1. Run the sidecar + Neo4j

```bash
git clone https://github.com/Suixinlei/risu-graphiti-memory
cd risu-graphiti-memory

# Neo4j (loopback only)
docker run -d --name neo4j-graphmem \
  -p 127.0.0.1:7474:7474 -p 127.0.0.1:7687:7687 \
  -e NEO4J_AUTH=neo4j/change-me \
  -v neo4j-graphmem-data:/data --restart unless-stopped \
  neo4j:5-community

# Sidecar
cd sidecar
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt httpx
cp ../.env.example .env   # edit: endpoints, keys, NEO4J_PASSWORD
.venv/bin/python main.py  # 127.0.0.1:8710
```

Notes from production use (see `sidecar/` code comments for details):

- `EMBEDDING_DIM` **must match** the embedder's real output dimension — the
  Neo4j vector index is created once with this size.
- The LLM should be a cheap non-reasoning model; for GLM-style models the
  default `LLM_EXTRA_BODY={"thinking":{"type":"disabled"}}` prevents reasoning
  tokens from eating the extraction budget.
- Ingestion is serialized (`INGEST_CONCURRENCY=1`): concurrent ingestion
  races entity deduplication and produces duplicate nodes.
- The upstream Aliyun endpoint limits embedding batches to 20 inputs —
  `embedder.py` chunks accordingly.

### 2. Install the plugin

Build (or grab `plugin/dist/plugin.js` from a release) and add it in RisuAI
via *Settings → Plugins → +* (paste code). Grant the **replacer** permission
when prompted — that is what injects/receives chat content.

Settings (plugin arguments):

| arg | default | meaning |
|---|---|---|
| `sidecar_url` | `http://127.0.0.1:8710` | sidecar base URL |
| `enabled` | `true` | master switch |
| `top_k` | `8` | facts injected per request |
| `min_messages` | `8` | only inject for prompts with at least N messages — keeps auxiliary calls (suggestions, summarizers) clean |
| `inject_depth` | `0` | insert the memory block N messages from the end (0 = very end, closest to the action) |
| `query_window` | `2000` | chars of recent conversation used as the search query (server truncates to 400 for the fulltext leg) |

### 3. (Optional) Backfill history

`tools/backfill.py` exports messages from a save and ingests them
resumable (`--skip-existing`):

```bash
python3 tools/backfill.py export --dump <db-dump-dir> --char <chaId> --chat 0 --last 100 --out msgs.jsonl
python3 tools/backfill.py ingest --file msgs.jsonl --group <chaId>-<chatId> --skip-existing
```

The group id must match the plugin's `${chaId}-${chat.id}` scheme.

## Development

```bash
cd plugin && npm i && npm run build   # typecheck + bundle to dist/plugin.js
cd sidecar && .venv/bin/python main.py
python3 tools/eval.py --group <id>     # retrieval sanity questions
python3 tools/fake_llm.py              # capture-prompt endpoint for E2E tests
```

## Known limitations

- Chinese fulltext search in Neo4j is per-character Lucene tokenization;
  long queries hit the `maxClauseCount` limit — the sidecar truncates the
  fulltext query to 400 chars as a guard, ranking leans on the semantic leg.
- Very long messages can exceed the extraction `max_tokens` and fail the
  episode (visible in `/health` `failed` counter; re-run backfill to retry).
- Regenerated replies are ingested as new episodes; the old version's facts
  remain with provenance and are subject to temporal invalidation.

## License

MIT
