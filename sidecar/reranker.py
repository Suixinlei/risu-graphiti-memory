"""Dependency-free lexical reranker.

Graphiti's default cross-encoder is an OpenAI-hosted reranker. This local
replacement scores query/passage lexical overlap instead: CJK text is scored
with character bigrams, latin text with lowercase word tokens. Far cheaper
than a hosted reranker and avoids sending retrieval traffic to a third party.
Swap in BGERerankerClient or OpenAIRerankerClient later if ranking quality
matters.
"""

import re

from graphiti_core.cross_encoder.client import CrossEncoderClient

_CJK = re.compile(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]')
_WORD = re.compile(r'[a-z0-9]+')


def _tokens(text: str) -> set[str]:
    chars = ''.join(_CJK.findall(text))
    grams = {chars[i : i + 2] for i in range(len(chars) - 1)}
    grams |= set(_WORD.findall(text.lower()))
    return grams


class LexicalReranker(CrossEncoderClient):
    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        q = _tokens(query)
        if not q:
            return [(p, 0.0) for p in passages]
        scored = []
        for p in passages:
            t = _tokens(p)
            scored.append((p, len(q & t) / len(q) if t else 0.0))
        return scored
