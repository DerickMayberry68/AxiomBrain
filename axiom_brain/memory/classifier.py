"""
AxiomBrain — Classifier
Uses a fast LLM (gpt-4o-mini via OpenRouter) to classify incoming content
and extract structured metadata: type, topics, people, action items, confidence.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import List, Optional

import httpx
from pydantic import BaseModel, Field, field_validator

from axiom_brain.config import get_settings


class ContentType(str, Enum):
    OBSERVATION  = "observation"    # General notes / thoughts
    TASK         = "task"           # Actionable item → admin table
    IDEA         = "idea"           # Creative / strategic insight → ideas table
    REFERENCE    = "reference"      # Links, data points, docs → projects table
    PERSON_NOTE  = "person_note"    # Info about a person → people table


class ClassificationResult(BaseModel):
    content_type:  ContentType
    topics:        List[str]   = Field(default_factory=list, min_length=1, max_length=3)
    people:        List[str]   = Field(default_factory=list)
    action_items:  List[str]   = Field(default_factory=list)
    confidence:    float       = Field(ge=0.0, le=1.0)
    reasoning:     Optional[str] = None   # Optional chain-of-thought from LLM

    @field_validator("topics")
    @classmethod
    def normalise_topics(cls, v: List[str]) -> List[str]:
        return [t.lower().strip() for t in v if t.strip()]

    @field_validator("people")
    @classmethod
    def normalise_people(cls, v: List[str]) -> List[str]:
        return [p.strip().title() for p in v if p.strip()]


_SYSTEM_PROMPT = """You are a memory classification assistant for AxiomBrain.
Analyze the provided content and return a JSON object with EXACTLY these fields:

{
  "content_type": "<one of: observation | task | idea | reference | person_note>",
  "topics": ["<1-3 lowercase topic tags>"],
  "people": ["<full names of people mentioned, if any>"],
  "action_items": ["<explicit actionable items, if any>"],
  "confidence": <float 0.0-1.0 representing how confident you are in the classification>,
  "reasoning": "<one sentence explaining the classification>"
}

Classification rules:
- observation: general thoughts, notes, logs, status updates
- task: contains an action to be done, a to-do, or a request with a clear owner/deadline
- idea: creative or strategic insight, hypothesis, or improvement proposal
- reference: a factual data point, URL, documentation reference, or technical specification
- person_note: information specifically about a named person (contact, relationship context)

Return ONLY valid JSON. No markdown, no explanation outside the JSON."""


class Classifier:
    """Classifies content using an LLM via OpenRouter."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._settings.openrouter_base_url,
                headers={
                    "Authorization": f"Bearer {self._settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
                timeout=20.0,
            )
        return self._client

    async def classify(self, content: str) -> ClassificationResult:
        """Classify content and return structured metadata."""
        payload = {
            "model": self._settings.classifier_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": content},
            ],
            "temperature": 0.1,   # Low temperature for deterministic classification
            "max_tokens": 300,
        }

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = await self.client.post("/chat/completions", json=payload)
                response.raise_for_status()
                raw = response.json()["choices"][0]["message"]["content"]
                parsed = json.loads(raw)
                return ClassificationResult(**parsed)

            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                # LLM returned malformed JSON — return safe default
                return _fallback_result(content)

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                # Log the actual response body so we can see the real error
                try:
                    error_body = exc.response.json()
                    print(f"[Classifier] OpenAI error response: {error_body}")
                except Exception:
                    print(f"[Classifier] HTTP {exc.response.status_code}: {exc.response.text}")
                if exc.response.status_code in (429, 500, 502, 503):
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise

            except httpx.RequestError as exc:
                last_exc = exc
                import asyncio
                await asyncio.sleep(2 ** attempt)

        # After retries exhausted, return a safe fallback
        return _fallback_result(content)

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


def _fallback_result(content: str) -> ClassificationResult:
    """Return a safe OBSERVATION fallback when classification fails."""
    return ClassificationResult(
        content_type=ContentType.OBSERVATION,
        topics=["general"],
        people=[],
        action_items=[],
        confidence=0.0,
        reasoning="Classification failed — defaulting to observation",
    )


# Module-level singleton
_classifier: Classifier | None = None


def get_classifier() -> Classifier:
    global _classifier
    if _classifier is None:
        _classifier = Classifier()
    return _classifier
