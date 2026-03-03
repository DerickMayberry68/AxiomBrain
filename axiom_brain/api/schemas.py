"""
AxiomBrain — API Schemas
Pydantic v2 request and response models for the REST API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Ingest ────────────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    content:      str  = Field(..., min_length=1, max_length=32_000,
                                description="Text content to store in the brain")
    source:       str  = Field(default="api",
                                description="Identifier for the calling tool (e.g. 'claude_code')")
    target_table: Optional[Literal["thoughts", "people", "projects", "ideas", "admin"]] = Field(
        default=None,
        description="Override automatic routing — write to this table directly"
    )


class IngestResponse(BaseModel):
    thought_id:   UUID
    routed_to:    str
    routed_id:    Optional[UUID]
    content_type: str
    confidence:   float
    topics:       List[str]
    people:       List[str]
    action_items: List[str]


# ── Search ────────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query:         str = Field(..., min_length=1, max_length=2_000)
    tables:        Optional[List[Literal["thoughts", "people", "projects", "ideas", "admin"]]] = Field(
        default=None,
        description="Limit search to specific tables. None = search all."
    )
    limit:         int  = Field(default=10, ge=1, le=50)
    topic_filter:  Optional[str] = Field(default=None, description="Filter results by topic tag")
    person_filter: Optional[str] = Field(default=None, description="Filter results by person name")


class SearchResult(BaseModel):
    source_table:  str
    id:            UUID
    primary_text:  str
    topics:        List[str]
    created_at:    datetime
    similarity:    float
    metadata:      Optional[Dict[str, Any]] = None


class SearchResponse(BaseModel):
    query:    str
    results:  List[SearchResult]
    count:    int


# ── Thoughts paginated list ───────────────────────────────────────────────────

class ThoughtItem(BaseModel):
    id:           UUID
    content:      str
    content_type: Optional[str]
    topics:       List[str]
    people:       List[str]
    source:       Optional[str]
    routed_to:    Optional[str]
    confidence:   float
    created_at:   datetime


class ThoughtsResponse(BaseModel):
    items:  List[ThoughtItem]
    total:  int
    limit:  int
    offset: int


# ── Stats ─────────────────────────────────────────────────────────────────────

class TableStats(BaseModel):
    table:       str
    row_count:   int
    last_update: Optional[datetime]


class StatsResponse(BaseModel):
    tables:  List[TableStats]
    db_ok:   bool


# ── Relationships ─────────────────────────────────────────────────────────────

_TABLE_LITERAL = Literal["thoughts", "people", "projects", "ideas", "admin"]
_REL_LITERAL   = Literal["works_on", "belongs_to", "recorded_in", "originated", "related_to"]


class RelationshipCreate(BaseModel):
    from_table: _TABLE_LITERAL
    from_id:    UUID
    to_table:   _TABLE_LITERAL
    to_id:      UUID
    rel_type:   _REL_LITERAL = "related_to"
    strength:   float        = Field(default=1.0, ge=0.0, le=1.0)
    source:     Optional[str] = None
    metadata:   Optional[Dict[str, Any]] = None


class RelationshipResponse(BaseModel):
    id:            UUID
    from_table:    str
    from_id:       UUID
    to_table:      str
    to_id:         UUID
    rel_type:      str
    strength:      float
    auto_detected: bool
    source:        Optional[str]
    created_at:    datetime
    metadata:      Dict[str, Any]


class RelationshipsListResponse(BaseModel):
    node_table:    str
    node_id:       UUID
    direction:     str
    relationships: List[RelationshipResponse]
    count:         int


# ── Summarization ─────────────────────────────────────────────────────────────

class SummarizeRequest(BaseModel):
    hours_back:        int = Field(default=24, ge=1, le=168,
                                   description="How many hours back to scan for unsummarized thoughts")
    min_thought_count: int = Field(default=3, ge=1,
                                   description="Minimum thoughts required to generate a daily digest")


class SummarizeResponse(BaseModel):
    daily_created:       bool
    projects_summarized: int
    people_summarized:   int
    summary_ids:         List[UUID]
    errors:              List[Any]


class SummaryItem(BaseModel):
    id:           UUID
    summary_type: str
    subject_name: Optional[str]
    content:      str
    source_count: int
    period_start: Optional[datetime]
    period_end:   Optional[datetime]
    topics:       List[str]
    created_at:   datetime


class SummariesListResponse(BaseModel):
    items:  List[SummaryItem]
    total:  int
    limit:  int
    offset: int


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status:  Literal["ok", "degraded"]
    version: str
    db_ok:   bool
