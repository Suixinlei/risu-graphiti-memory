"""risu-graphiti-memory sidecar.

FastAPI service wrapping graphiti-core: turns chat messages into a temporal
knowledge graph (Neo4j) and answers hybrid retrieval queries for prompt
injection.

Endpoints:
  POST /episode/submit — idempotent pending/completed receipt (202)
  POST /episode  — compatible alias of /episode/submit
  POST /search   — hybrid search, returns temporal facts for injection
  GET  /health   — neo4j connectivity + queue/active/pending counts
  GET  /stats    — per-group node/edge/episode counts
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from graphiti_core import Graphiti
from graphiti_core.embedder.openai import OpenAIEmbedderConfig
from graphiti_core.nodes import EpisodeType
from graphiti_core.search.search_filters import SearchFilters

from config import config
from embedder import BatchedEmbedder
from llm import ExtraBodyLLMClient
from ontology import ENTITY_TYPES, EXTRACTION_INSTRUCTIONS
from assistant_memory import AssistantMemory
from reranker import LexicalReranker

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
logger = logging.getLogger('graphmem')

# Optional canonical-name roster (see sidecar/roster.txt): teaches the
# extraction LLM that alias variants are one character, so 塞西尔/塞西尔·布兰榭/
# Cécile don't become three nodes. Card-agnostic: it's just text appended to
# the extraction instructions per episode.
ROSTER_FILE = Path(__file__).resolve().parent / 'roster.txt'
_extra_extraction = ''
if ROSTER_FILE.exists():
    _extra_extraction = '\n\n' + ROSTER_FILE.read_text(encoding='utf-8')
    logger.info('roster loaded: %d chars', len(_extra_extraction))

graphiti = Graphiti(
    uri=config.neo4j_uri,
    user=config.neo4j_user,
    password=config.neo4j_password,
    llm_client=ExtraBodyLLMClient(),
    embedder=BatchedEmbedder(
        config=OpenAIEmbedderConfig(
            api_key=config.embedding_api_key,
            base_url=config.embedding_base_url,
            embedding_model=config.embedding_model,
            embedding_dim=config.embedding_dim,
        )
    ),
    cross_encoder=LexicalReranker(),
)

queue: asyncio.Queue['EpisodeRequest'] = asyncio.Queue()
ingest_stats = {'processed': 0, 'failed': 0}
pending: dict[tuple[str, str], 'EpisodeRequest'] = {}
submit_lock = asyncio.Lock()
active = 0
graphiti_write_lock = asyncio.Lock()
assistant_memory = AssistantMemory(graphiti, graphiti_write_lock)


class EpisodeRequest(BaseModel):
    group_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    body: str = Field(min_length=1)
    source: Literal['message', 'text', 'json'] = 'message'
    source_description: str = ''
    reference_time: Optional[datetime] = None
    # Only offline migration uses this; never trust an old name without
    # matching its content, source and reference time as well.
    legacy_name: Optional[str] = Field(default=None, min_length=1, max_length=256)


class SearchRequest(BaseModel):
    group_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


async def ingest_worker(name: str):
    global active
    while True:
        req = await queue.get()
        active += 1
        try:
            async with graphiti_write_lock:
                await graphiti.add_episode(
                    name=req.name,
                    episode_body=req.body,
                    source_description=req.source_description or 'chat',
                    reference_time=req.reference_time or datetime.now(timezone.utc),
                    source=EpisodeType(req.source),
                    group_id=req.group_id,
                    entity_types=ENTITY_TYPES,
                    custom_extraction_instructions=EXTRACTION_INSTRUCTIONS + _extra_extraction,
                )
            ingest_stats['processed'] += 1
            logger.info('[%s] ingested %s (qsize=%d)', name, req.name, queue.qsize())
        except Exception:
            ingest_stats['failed'] += 1
            logger.exception('[%s] FAILED %s', name, req.name)
        finally:
            active -= 1
            pending.pop((req.group_id, req.name), None)
            queue.task_done()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await graphiti.build_indices_and_constraints()
    await assistant_memory.start()
    workers = [
        asyncio.create_task(ingest_worker(f'worker-{i}')) for i in range(config.ingest_concurrency)
    ]
    logger.info(
        'sidecar up: llm=%s embed=%s(dim=%d) neo4j=%s workers=%d',
        config.llm_model,
        config.embedding_model,
        config.embedding_dim,
        config.neo4j_uri,
        config.ingest_concurrency,
    )
    try:
        yield
    finally:
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        await assistant_memory.close()
        await graphiti.close()


app = FastAPI(title='risu-graphiti-memory', lifespan=lifespan)
app.include_router(assistant_memory.router)

# The RisuAI plugin page (e.g. a statically-hosted instance on another local
# port) calls this service cross-origin; it's a localhost-only personal tool,
# so permissive CORS is fine.
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.post('/episode', status_code=202)
@app.post('/episode/submit', status_code=202)
async def add_episode(req: EpisodeRequest):
    if req.name.startswith('live-v2-'):
        raise HTTPException(409, 'legacy live capture disabled; upgrade the plugin and reload RisuAI')
    def receipt(status: str):
        return {'protocol': 2, 'status': status, 'queued': status == 'pending',
                'position': queue.qsize(), 'name': req.name}

    async with submit_lock:
        key = (req.group_id, req.name)
        previous = pending.get(key)
        if previous is not None:
            if previous.model_dump(exclude={'legacy_name'}) != req.model_dump(exclude={'legacy_name'}):
                raise HTTPException(409, 'episode name already used with different content')
            return receipt('pending')
        records = await graphiti.driver.execute_query(
            'MATCH (e:Episodic) WHERE e.group_id = $gid AND e.name IN $names '
            'RETURN e.name AS name, e.content AS content, e.source AS source, '
            'e.source_description AS description, e.valid_at AS reference_time',
            gid=req.group_id, names=[req.name] + ([req.legacy_name] if req.legacy_name else []),
        )
        for record in sorted(records.records, key=lambda row: row['name'] != req.name):
            stored_time = record['reference_time']
            if hasattr(stored_time, 'to_native'):
                stored_time = stored_time.to_native()
            requested_time = req.reference_time
            if requested_time is not None and requested_time.tzinfo is None:
                requested_time = requested_time.replace(tzinfo=timezone.utc)
            matches = (record['content'] == req.body and record['source'] == req.source
                       and record['description'] == (req.source_description or 'chat')
                       and (requested_time is None or stored_time == requested_time))
            if matches:
                return receipt('completed')
            if record['name'] == req.name:
                raise HTTPException(409, 'episode name already used with different content')
        # A response lost after enqueue is safe: retries see pending, and a
        # response lost after commit is safe: retries match the saved episode.
        pending[key] = req
        queue.put_nowait(req)
        return receipt('pending')


@app.post('/search')
async def search(req: SearchRequest):
    # CJK fulltext guard: Neo4j/Lucene tokenizes Chinese per character, and a
    # long query explodes the boolean maxClauseCount (1024). Truncate hard;
    # the semantic leg stays useful and 400 CJK chars ≈ 400 clauses < limit.
    query = req.query[:400]
    try:
        edges = await graphiti.search(
            query,
            group_ids=[req.group_id],
            num_results=req.limit,
            search_filter=SearchFilters(),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f'search failed: {e}') from e

    facts = []
    for e in edges:
        facts.append(
            {
                'fact': e.fact,
                'uuid': e.uuid,
                'valid_at': e.valid_at.isoformat() if e.valid_at else None,
                'invalid_at': e.invalid_at.isoformat() if e.invalid_at else None,
                'expired': e.expired_at is not None,
                'episode_uuids': e.episodes,
            }
        )
    return {'group_id': req.group_id, 'facts': facts}


@app.get('/health')
async def health():
    try:
        await graphiti.driver.execute_query('RETURN 1')
        neo4j = 'ok'
    except Exception as e:
        neo4j = f'error: {e}'
    return {
        'status': 'ok' if neo4j == 'ok' else 'degraded',
        'neo4j': neo4j,
        'queue_depth': queue.qsize(),
        'active': active,
        'pending': len(pending),
        'ingest_protocol': 2,
        'assistant_memory_protocol': 3,
        'assistant_pending': len(assistant_memory.queued),
        'assistant_queue_depth': assistant_memory.queue.qsize(),
        **ingest_stats,
    }


@app.get('/episodes')
async def episodes(group_id: str, limit: int = 2000):
    """Episode names present in a group (for resumable backfill)."""
    result = await graphiti.driver.execute_query(
        'MATCH (e:Episodic) WHERE e.group_id = $gid RETURN e.name AS name ORDER BY e.name',
        gid=group_id,
    )
    return {'names': [r['name'] for r in result.records]}


@app.get('/entities')
async def entities(group_id: str, q: str = '', limit: int = 50):
    """List entities (name, labels, summary) for inspection: duplicate-name
    detection, extraction sanity checks."""
    result = await graphiti.driver.execute_query(
        """
        MATCH (n:Entity) WHERE n.group_id = $gid AND n.name CONTAINS $q
        RETURN n.name AS name, labels(n) AS labels, n.summary AS summary
        ORDER BY size(n.summary) DESC LIMIT $limit
        """,
        gid=group_id,
        q=q,
        limit=limit,
    )
    return {
        'entities': [
            {'name': r['name'], 'labels': [x for x in r['labels'] if x != 'Entity'], 'summary': r['summary']}
            for r in result.records
        ]
    }


@app.get('/stats')
async def stats(group_id: str):
    """Counts for one group. Episodes counted via the episode-by-name helper are
    expensive; use a direct Cypher aggregate instead."""
    driver = graphiti.driver
    counts = {}
    try:
        result = await driver.execute_query(
            """
            MATCH (n) WHERE n.group_id = $gid
            OPTIONAL MATCH (n)-[r]-() WHERE r.group_id = $gid
            RETURN labels(n)[0] AS label, count(DISTINCT n) AS nodes, count(DISTINCT r) AS edges
            """,
            gid=group_id,
        )
        for rec in result.records:
            counts[rec['label']] = {'nodes': rec['nodes'], 'edges': rec['edges']}
        ep_result = await driver.execute_query(
            'MATCH (e:Episodic) WHERE e.group_id = $gid RETURN count(e) AS c', gid=group_id
        )
        episodes = ep_result.records[0]['c'] if ep_result.records else 0
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {'group_id': group_id, 'episodes': episodes, 'by_label': counts}


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host=config.host, port=config.port, log_level='info')
