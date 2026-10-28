import os
from dataclasses import dataclass, field
from pathlib import Path

# Load sidecar/.env if present (local dev; safe no-op otherwise).
_env_file = Path(__file__).resolve().parent / '.env'
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _, _v = _line.partition('=')
            os.environ.setdefault(_k.strip(), _v.strip())


def _env(key: str, default: str = '') -> str:
    v = os.environ.get(key, '').strip()
    return v or default


@dataclass
class Config:
    # LLM (extraction) — OpenAI-compatible endpoint
    llm_base_url: str = field(default_factory=lambda: _env('LLM_BASE_URL', 'http://127.0.0.1:8080/v1'))
    llm_api_key: str = field(default_factory=lambda: _env('LLM_API_KEY', 'EMPTY'))
    llm_model: str = field(default_factory=lambda: _env('LLM_MODEL', 'glm-5.3-flash'))
    # Some reasoning models (e.g. GLM) burn the whole budget on reasoning tokens
    # unless thinking is disabled; extra kwargs merged into every completion call.
    llm_extra_body_json: str = field(default_factory=lambda: _env('LLM_EXTRA_BODY', '{"thinking":{"type":"disabled"}}'))
    llm_temperature: float = field(default_factory=lambda: float(_env('LLM_TEMPERATURE', '0.0')))
    llm_max_tokens: int = field(default_factory=lambda: int(_env('LLM_MAX_TOKENS', '16384')))

    # Embedder — OpenAI-compatible endpoint
    embedding_base_url: str = field(default_factory=lambda: _env('EMBEDDING_BASE_URL', 'http://127.0.0.1:8080/v1'))
    embedding_api_key: str = field(default_factory=lambda: _env('EMBEDDING_API_KEY', 'EMPTY'))
    embedding_model: str = field(default_factory=lambda: _env('EMBEDDING_MODEL', 'qwen3.7-text-embedding'))
    # MUST match the embedder's output dim; the Neo4j vector index is created with
    # this size and cannot be changed afterwards without rebuilding the store.
    embedding_dim: int = field(default_factory=lambda: int(_env('EMBEDDING_DIM', '1024')))

    # Neo4j
    neo4j_uri: str = field(default_factory=lambda: _env('NEO4J_URI', 'bolt://127.0.0.1:7687'))
    neo4j_user: str = field(default_factory=lambda: _env('NEO4J_USER', 'neo4j'))
    neo4j_password: str = field(default_factory=lambda: _env('NEO4J_PASSWORD', 'risu-graphmem-2026'))

    # Service
    host: str = field(default_factory=lambda: _env('HOST', '127.0.0.1'))
    port: int = field(default_factory=lambda: int(_env('PORT', '8710')))
    # Episode ingestion workers. MUST stay 1: concurrent ingestion races on
    # entity dedupe (two workers both see an empty graph and create duplicate
    # nodes for the same character). Chat ingestion is naturally serialized
    # (one message lands at a time), so this costs nothing.
    ingest_concurrency: int = field(default_factory=lambda: int(_env('INGEST_CONCURRENCY', '1')))
    ingest_retry: int = field(default_factory=lambda: int(_env('INGEST_RETRY', '3')))

    @property
    def llm_extra_body(self) -> dict:
        import json

        try:
            v = json.loads(self.llm_extra_body_json)
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}


config = Config()
