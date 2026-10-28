"""Embedder with per-request batch splitting.

The upstream endpoint (Aliyun Maas serving qwen3.7-text-embedding) rejects
embedding requests with more than 20 inputs in one call. Graphiti's
create_batch embeds all extracted facts/entities of an episode at once, which
routinely exceeds that. Split into chunks, fan out, keep order.
"""

from graphiti_core.embedder.openai import OpenAIEmbedder

MAX_BATCH = 20


class BatchedEmbedder(OpenAIEmbedder):
    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(input_data_list), MAX_BATCH):
            out.extend(await super().create_batch(input_data_list[i : i + MAX_BATCH]))
        return out
