"""LLM client wrapper: OpenAI-compatible, with extra body kwargs support.

Graphiti's stock clients expose no way to pass provider-specific body fields
(e.g. GLM's `thinking: {"type": "disabled"}`). We wrap the underlying
openai client's `chat.completions.create` to merge `extra_body` into every
call, so reasoning models don't burn the token budget on hidden reasoning.
"""

from openai import AsyncOpenAI

from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

from config import config


class ExtraBodyLLMClient(OpenAIGenericClient):
    """OpenAIGenericClient + extra_body merge on every completion call."""

    def __init__(self):
        super().__init__(
            config=LLMConfig(
                api_key=config.llm_api_key,
                model=config.llm_model,
                base_url=config.llm_base_url,
                temperature=config.llm_temperature,
                max_tokens=config.llm_max_tokens,
            ),
            # json_schema (native constrained decoding): the endpoint supports
            # response_format=json_schema, which enforces required fields —
            # json_object mode lets the model omit fields and graphiti's
            # ExtractedEdges validation then rejects the whole episode.
            structured_output_mode='json_schema',
        )
        assert isinstance(self.client, AsyncOpenAI)
        if config.llm_extra_body:
            original_create = self.client.chat.completions.create

            async def create_with_extra_body(**kwargs):
                merged = {**config.llm_extra_body, **(kwargs.get('extra_body') or {})}
                kwargs['extra_body'] = merged
                return await original_create(**kwargs)

            self.client.chat.completions.create = create_with_extra_body  # type: ignore[method-assign]
