"""
AxiomBrain — Webhook management routes

POST /webhooks/test   — fire a test notification to verify Teams is wired up
GET  /webhooks/status — show current webhook configuration (masked URL)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from axiom_brain.api.auth import require_api_key
from axiom_brain.config import settings
from axiom_brain.notifications.teams import notify_test

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookStatusResponse(BaseModel):
    teams_configured: bool
    teams_url_preview: str  # masked, e.g. "https://...webhook.office.com/webhookb2/abc***"


class WebhookTestResponse(BaseModel):
    success: bool
    message: str


@router.get("/status", response_model=WebhookStatusResponse)
async def webhook_status(_: str = require_api_key):
    """Return current webhook configuration (URL is masked for security)."""
    url = settings.teams_webhook_url
    configured = bool(url)
    preview = ""
    if url:
        # Show protocol + host + first 6 chars of path, then mask the rest
        parts = url.split("/", 3)
        if len(parts) >= 3:
            preview = f"{parts[0]}//{parts[2]}/" + (parts[3][:6] + "***" if len(parts) > 3 else "***")
        else:
            preview = url[:20] + "***"
    return WebhookStatusResponse(teams_configured=configured, teams_url_preview=preview)


@router.post("/test", response_model=WebhookTestResponse)
async def webhook_test(_: str = require_api_key):
    """
    Send a test ping to the configured Teams webhook.
    Returns 200 with success=False if the URL is not configured or the delivery fails.
    Raises 503 only on unexpected internal errors.
    """
    if not settings.teams_webhook_url:
        return WebhookTestResponse(
            success=False,
            message="TEAMS_WEBHOOK_URL is not set in .env — nothing was sent.",
        )

    ok = notify_test()
    if ok:
        return WebhookTestResponse(
            success=True,
            message="Test notification delivered to Teams successfully.",
        )
    else:
        return WebhookTestResponse(
            success=False,
            message="Teams webhook POST failed — check TEAMS_WEBHOOK_URL and server logs.",
        )
