"""
AxiomBrain — Embedder
Converts raw text into 1536-dimensional vectors via OpenRouter.
Includes LRU cache to avoid re-embedding identical strings within a session.
"""

from __future__ import annotations

import asyncio
import hashlib
from functools import lru_cache
from typing import List

import httpx

from axiom_brain.config import get_settings


class Embedder:
    """Async text embedder backed by OpenRouter's embeddings endpoint."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: httpx.AsyncClient | None = None
        # Simple in-process LRU cache keyed by content hash
        self._cache: dict[str, List[float]] = {}
        self._cache_max = self._settings.embedding_cache_size

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._settings.openrouter_base_url,
                headers={
                    "Authorization": f"Bearer {self._settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    def _cache_key(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    async def embed(self, text: str) -> List[float]:
        """Embed a single string, returning a 1536-dim float list."""
        key = self._cache_key(text)
        if key in self._cache:
            return self._cache[key]

        vector = await self._call_api([text])
        result = vector[0]

        # Evict oldest entry if cache is full (simple FIFO)
        if len(self._cache) >= self._cache_max:
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        self._cache[key] = result
        return result

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple strings efficiently. Respects cache."""
        # Separate cached from uncached
        keys = [self._cache_key(t) for t in texts]
        uncached_indices = [i for i, k in enumerate(keys) if k not in self._cache]
        uncached_texts = [texts[i] for i in uncached_indices]

        if uncached_texts:
            # OpenRouter supports batch embedding up to 2048 inputs
            chunk_size = 100
            new_vectors: List[List[float]] = []
            for i in range(0, len(uncached_texts), chunk_size):
                chunk = uncached_texts[i : i + chunk_size]
                chunk_vectors = await self._call_api(chunk)
                new_vectors.extend(chunk_vectors)

            for idx, vector in zip(uncached_indices, new_vectors):
                k = keys[idx]
                if len(self._cache) >= self._cache_max:
                    oldest = next(iter(self._cache))
                    del self._cache[oldest]
                self._cache[k] = vector

        return [self._cache[k] for k in keys]

    async def _call_api(self, texts: List[str]) -> List[List[float]]:
        """Raw API call with retry logic (3 attempts, exponential back-off)."""
        payload = {
            "model": self._settings.embedding_model,
            "input": texts,
        }

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = await self.client.post("/embeddings", json=payload)
                response.raise_for_status()
                data = response.json()
                # OpenAI-compatible response: data.data[].embedding
                return [item["embedding"] for item in data["data"]]
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code in (429, 500, 502, 503):
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
            except httpx.RequestError as exc:
                last_exc = exc
                await asyncio.sleep(2 ** attempt)

        raise RuntimeError(f"Embedding API failed after 3 attempts: {last_exc}")

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Module-level singleton
_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder
