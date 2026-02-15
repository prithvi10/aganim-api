"""
Generic text embedding via OpenAI API.

Uses the ``openai`` library directly (no dependency on domain-specific services).
"""
from __future__ import annotations

import os

from src.shared.config.configs import EMBEDDING_MODEL, EMBEDDING_BATCH_SIZE


def embed_texts(texts: list[str], *, model: str | None = None) -> list[list[float]]:
    """
    Embed a list of texts using the OpenAI embeddings API.

    Falls back to ``EMBEDDING_MODEL`` from config when *model* is ``None``.
    """
    if not texts:
        return []

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    # Lazy import so tests that mock embed_texts don't need openai installed
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    embed_model = model or EMBEDDING_MODEL

    vectors: list[list[float]] = []
    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i : i + EMBEDDING_BATCH_SIZE]
        resp = client.embeddings.create(model=embed_model, input=batch)
        vectors.extend([item.embedding for item in resp.data])
    return vectors
