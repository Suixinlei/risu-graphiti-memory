"""risu-graphiti-memory sidecar.

FastAPI service wrapping graphiti-core: turns chat messages into a temporal
knowledge graph (Neo4j) and answers hybrid retrieval queries for prompt
injection.

Endpoints:
  POST /episode  — queue a message/document for background ingestion (202)
  POST /search   — hybrid search, returns temporal facts for injection
  GET  /health   — neo4j connectivity + queue depth
  GET  /stats    — per-group node/edge/episode counts
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from graphiti_core import Graphiti
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.nodes import EpisodeType
from graphiti_core.search.search_filters import SearchFilters

from config import config
from llm import ExtraBodyLLMClient
from ontology import ENTITY_TYPES, EXTRACTION_INSTRUCTIONS
from reranker import LexicalReranker

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
logger = logging.getLogger('graphmem')

graphiti = Graphiti(
    uri=config.neo4j_uri,
    user=config.neo4j_user,
    password=config.neo4j_password,
    llm_client=ExtraBodyLLMClient(),
    embedder=OpenAIEmbedder(
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


class EpisodeRequest(BaseModel):
    group_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    body: str = Field(min_length=1)
    source: Literal['message', 'text', 'json'] = 'message'
    source_description: str = ''
    reference_time: Optional[datetime] = None


class SearchRequest(BaseModel):
    group_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


async def ingest_worker(name: str):
    while True:
        req = await queue.get()
        try:
            await graphiti.add_episode(
                name=req.name,
                episode_body=req.body,
                source_description=req.source_description or 'chat',
                reference_time=req.reference_time or datetime.now(timezone.utc),
                source=EpisodeType(req.source),
                group_id=req.group_id,
                entity_types=ENTITY_TYPES,
                custom_extraction_instructions=EXTRACTION_INSTRUCTIONS,
            )
            ingest_stats['processed'] += 1
            logger.info('[%s] ingested %s (qsize=%d)', name, req.name, queue.qsize())
        except Exception:
            ingest_stats['failed'] += 1
            logger.exception('[%s] FAILED %s', name, req.name)
        finally:
            queue.task_done()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await graphiti.build_indices_and_constraints()
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
        await graphiti.close()


app = FastAPI(title='risu-graphiti-memory', lifespan=lifespan)


@app.post('/episode', status_code=202)
async def add_episode(req: EpisodeRequest):
    queue.put_nowait(req)
    return {'queued': True, 'position': queue.qsize(), 'name': req.name}


@app.post('/search')
async def search(req: SearchRequest):
    try:
        edges = await graphiti.search(
            req.query,
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
        **ingest_stats,
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
