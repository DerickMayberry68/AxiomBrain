"""
AxiomBrain — API Key Authentication
Simple header-based auth middleware for FastAPI.
"""

from __future__ import annotations

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from axiom_brain.config import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(api_key: str = Security(_api_key_header)) -> str:
    """FastAPI dependency — validates the X-API-Key header."""
    settings = get_settings()
    if not api_key or api_key != settings.axiom_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Set X-API-Key header.",
        )
    return api_key
