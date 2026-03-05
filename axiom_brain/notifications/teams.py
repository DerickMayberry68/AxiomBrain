"""
Microsoft Teams webhook notifier for AxiomBrain.

Uses the Incoming Webhook connector format (MessageCard + Adaptive Card fallback).
Configure TEAMS_WEBHOOK_URL in .env to enable notifications.
"""

import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from axiom_brain.config import settings

logger = logging.getLogger(__name__)


def _build_summary_card(stats: Dict[str, Any], duration_seconds: float) -> Dict:
    """
    Build a Teams Adaptive Card payload for the nightly summary results.

    stats shape expected:
        {
            "thoughts": {"summaries_created": int, "thoughts_processed": int},
            "projects": {"summaries_created": int, ...},
            "people":   {"summaries_created": int, ...},
            "errors":   [...],
        }
    """
    ts = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")

    thoughts_created = stats.get("thoughts", {}).get("summaries_created", 0)
    thoughts_processed = stats.get("thoughts", {}).get("thoughts_processed", 0)
    projects_created = stats.get("projects", {}).get("summaries_created", 0)
    people_created = stats.get("people", {}).get("summaries_created", 0)
    error_count = len(stats.get("errors", []))

    total_summaries = thoughts_created + projects_created + people_created
    status_color = "Good" if error_count == 0 else "Warning"
    status_text = "✅ Completed successfully" if error_count == 0 else f"⚠️ Completed with {error_count} error(s)"

    # Build fact rows
    facts = [
        {"title": "Thoughts summarized", "value": f"{thoughts_created} summaries from {thoughts_processed} thoughts"},
        {"title": "Project summaries",   "value": str(projects_created)},
        {"title": "People summaries",    "value": str(people_created)},
        {"title": "Total summaries",     "value": str(total_summaries)},
        {"title": "Duration",            "value": f"{duration_seconds:.1f}s"},
    ]
    if error_count > 0:
        error_msgs = "; ".join(str(e) for e in stats.get("errors", [])[:3])
        facts.append({"title": "Errors", "value": error_msgs})

    # MessageCard format — supported by all Teams tenants including older ones
    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": "00B294" if error_count == 0 else "FFA500",
        "summary": "AxiomBrain Nightly Summary Complete",
        "sections": [
            {
                "activityTitle": "🧠 AxiomBrain — Nightly Summary Complete",
                "activitySubtitle": ts,
                "activityText": status_text,
                "facts": facts,
                "markdown": True,
            }
        ],
    }
    return payload


def _build_test_card() -> Dict:
    """Simple ping card to verify the webhook is wired up correctly."""
    ts = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
    return {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": "0078D7",
        "summary": "AxiomBrain webhook test",
        "sections": [
            {
                "activityTitle": "🧠 AxiomBrain — Webhook Test",
                "activitySubtitle": ts,
                "activityText": "✅ Your Teams webhook is configured correctly. "
                                "You will receive notifications here after each nightly summary job.",
                "markdown": True,
            }
        ],
    }


def _post_to_teams(payload: Dict) -> bool:
    """
    POST a MessageCard payload to the configured Teams webhook URL.
    Returns True on success, False on any failure.
    Intentionally never raises — notification failures must never crash the main process.
    """
    url = settings.teams_webhook_url
    if not url:
        logger.debug("TEAMS_WEBHOOK_URL not set — skipping Teams notification")
        return False

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            if status == 200:
                logger.info("Teams notification sent successfully")
                return True
            else:
                logger.warning("Teams webhook returned unexpected status %s", status)
                return False
    except urllib.error.HTTPError as exc:
        logger.error("Teams webhook HTTP error %s: %s", exc.code, exc.reason)
        return False
    except urllib.error.URLError as exc:
        logger.error("Teams webhook URL error: %s", exc.reason)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error("Teams webhook unexpected error: %s", exc)
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def notify_summary_complete(stats: Dict[str, Any], duration_seconds: float = 0.0) -> bool:
    """
    Send a nightly-summary-complete notification to Teams.
    Safe to call from background jobs — never raises.
    """
    if not settings.teams_webhook_url:
        return False
    payload = _build_summary_card(stats, duration_seconds)
    return _post_to_teams(payload)


def notify_test() -> bool:
    """Send a test ping to confirm the webhook URL is working."""
    if not settings.teams_webhook_url:
        logger.warning("TEAMS_WEBHOOK_URL is not configured")
        return False
    payload = _build_test_card()
    return _post_to_teams(payload)
