"""
AxiomBrain — Classifier Unit Tests
Tests classification logic with mocked OpenRouter responses.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from axiom_brain.memory.classifier import (
    Classifier,
    ClassificationResult,
    ContentType,
    _fallback_result,
)


@pytest.mark.asyncio
async def test_classify_task():
    mock_response_data = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "content_type": "task",
                    "topics": ["project", "deadline"],
                    "people": [],
                    "action_items": ["Submit report by Friday"],
                    "confidence": 0.92,
                    "reasoning": "Contains an explicit action with a deadline."
                })
            }
        }]
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = mock_response_data
        mock_post.return_value = mock_resp

        classifier = Classifier()
        result = await classifier.classify("Submit the weekly report by Friday.")

    assert result.content_type == ContentType.TASK
    assert result.confidence == 0.92
    assert "project" in result.topics
    assert len(result.action_items) == 1


@pytest.mark.asyncio
async def test_classify_person_note():
    mock_response_data = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "content_type": "person_note",
                    "topics": ["client", "consulting"],
                    "people": ["John Smith"],
                    "action_items": [],
                    "confidence": 0.88,
                    "reasoning": "Describes a named person."
                })
            }
        }]
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = mock_response_data
        mock_post.return_value = mock_resp

        classifier = Classifier()
        result = await classifier.classify("John Smith is the CTO at Acme Corp.")

    assert result.content_type == ContentType.PERSON_NOTE
    assert "John Smith" in result.people


def test_fallback_result():
    result = _fallback_result("some content")
    assert result.content_type == ContentType.OBSERVATION
    assert result.confidence == 0.0
    assert result.topics == ["general"]


def test_topic_normalisation():
    result = ClassificationResult(
        content_type=ContentType.IDEA,
        topics=["  Python  ", "AI ", "DATABASES"],
        confidence=0.7,
    )
    assert "python" in result.topics
    assert "ai" in result.topics
    assert "databases" in result.topics


def test_confidence_bounds():
    with pytest.raises(Exception):
        ClassificationResult(
            content_type=ContentType.TASK,
            topics=["test"],
            confidence=1.5,   # Out of bounds
        )
