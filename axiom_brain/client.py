"""
AxiomBrain — Lightweight REST Client
For use by custom agents (LangChain, CrewAI, etc.) that integrate via HTTP.

Usage:
    from axiom_brain.client import AxiomBrainClient

    brain = AxiomBrainClient(base_url='http://localhost:8000', api_key='your-key')
    brain.ingest('Decided to use PostgreSQL for persistence', source='my_agent')
    results = brain.search('database decisions', limit=5)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx


class AxiomBrainClient:
    """Synchronous REST client wrapper for custom agent integration."""

    def __init__(self, base_url: str = "http://localhost:8000", api_key: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._headers  = {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        }

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self._base_url, headers=self._headers, timeout=30.0)

    # ── Write ────────────────────────────────────────────────────────────────

    def ingest(
        self,
        content: str,
        source: str = "custom_agent",
        target_table: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store content in the brain. Returns the ingest result."""
        payload: Dict[str, Any] = {"content": content, "source": source}
        if target_table:
            payload["target_table"] = target_table
        with self._client() as c:
            resp = c.post("/ingest", json=payload)
            resp.raise_for_status()
            return resp.json()

    # ── Read ─────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        tables: Optional[List[str]] = None,
        limit: int = 10,
        topic_filter: Optional[str] = None,
        person_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Semantic search. Returns a list of result dicts sorted by similarity."""
        payload: Dict[str, Any] = {"query": query, "limit": limit}
        if tables:
            payload["tables"] = tables
        if topic_filter:
            payload["topic_filter"] = topic_filter
        if person_filter:
            payload["person_filter"] = person_filter
        with self._client() as c:
            resp = c.post("/search", json=payload)
            resp.raise_for_status()
            return resp.json()["results"]

    def health(self) -> Dict[str, Any]:
        with self._client() as c:
            resp = c.get("/health")
            resp.raise_for_status()
            return resp.json()

    def stats(self) -> Dict[str, Any]:
        with self._client() as c:
            resp = c.get("/stats")
            resp.raise_for_status()
            return resp.json()

    def list_thoughts(
        self,
        limit: int = 20,
        offset: int = 0,
        source: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if source:
            params["source"] = source
        with self._client() as c:
            resp = c.get("/thoughts", params=params)
            resp.raise_for_status()
            return resp.json()

    # ── Graph ─────────────────────────────────────────────────────────────────

    def link(
        self,
        from_table: str,
        from_id:    str,
        to_table:   str,
        to_id:      str,
        rel_type:   str   = "related_to",
        strength:   float = 1.0,
        source:     Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a manual relationship edge between two memory nodes."""
        payload: Dict[str, Any] = {
            "from_table": from_table,
            "from_id":    from_id,
            "to_table":   to_table,
            "to_id":      to_id,
            "rel_type":   rel_type,
            "strength":   strength,
        }
        if source:
            payload["source"] = source
        with self._client() as c:
            resp = c.post("/relationships", json=payload)
            resp.raise_for_status()
            return resp.json()

    def get_relationships(
        self,
        table:     str,
        node_id:   str,
        direction: str           = "both",
        rel_type:  Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get all relationship edges for a node."""
        params: Dict[str, Any] = {"direction": direction}
        if rel_type:
            params["rel_type"] = rel_type
        with self._client() as c:
            resp = c.get(f"/relationships/{table}/{node_id}", params=params)
            resp.raise_for_status()
            return resp.json()


class AsyncAxiomBrainClient:
    """Async REST client for use in async agent frameworks (LangGraph, etc.)."""

    def __init__(self, base_url: str = "http://localhost:8000", api_key: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._headers  = {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        }

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, headers=self._headers, timeout=30.0)

    async def ingest(
        self,
        content: str,
        source: str = "async_agent",
        target_table: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"content": content, "source": source}
        if target_table:
            payload["target_table"] = target_table
        async with self._client() as c:
            resp = await c.post("/ingest", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def search(
        self,
        query: str,
        tables: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {"query": query, "limit": limit}
        if tables:
            payload["tables"] = tables
        async with self._client() as c:
            resp = await c.post("/search", json=payload)
            resp.raise_for_status()
            return resp.json()["results"]
