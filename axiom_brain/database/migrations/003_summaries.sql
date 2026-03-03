-- AxiomBrain Migration 003 — Summaries
-- Stores LLM-generated summaries of memory content.
-- Originals are never deleted — summaries are additive.

BEGIN;

CREATE TABLE IF NOT EXISTS summaries (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    summary_type    TEXT        NOT NULL
                    CHECK (summary_type IN (
                        'daily_thoughts',
                        'project_rollup',
                        'person_profile',
                        'all_tables'
                    )),
    subject_table   TEXT,                          -- 'projects' | 'people' | NULL for global
    subject_id      UUID,                          -- project/person UUID or NULL
    subject_name    TEXT,                          -- human-readable label
    content         TEXT        NOT NULL,          -- the summary text
    embedding       VECTOR(1536),                  -- for semantic search over summaries
    source_count    INT         NOT NULL DEFAULT 0,-- how many memories were compressed
    period_start    TIMESTAMPTZ,                   -- earliest memory covered
    period_end      TIMESTAMPTZ,                   -- latest memory covered
    topics          TEXT[]      NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Semantic search index
CREATE INDEX IF NOT EXISTS idx_summaries_embedding
    ON summaries USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

-- Fast lookup by type and subject
CREATE INDEX IF NOT EXISTS idx_summaries_type        ON summaries (summary_type);
CREATE INDEX IF NOT EXISTS idx_summaries_subject     ON summaries (subject_table, subject_id);
CREATE INDEX IF NOT EXISTS idx_summaries_created_at  ON summaries (created_at DESC);

-- Track which thoughts have been included in a summary
-- (allows incremental summarization — only process new thoughts each run)
ALTER TABLE thoughts
    ADD COLUMN IF NOT EXISTS summarized_at TIMESTAMPTZ DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_thoughts_summarized
    ON thoughts (summarized_at)
    WHERE summarized_at IS NULL;

-- Semantic search function for summaries
CREATE OR REPLACE FUNCTION match_summaries(
    query_embedding VECTOR(1536),
    match_count     INT  DEFAULT 10,
    type_filter     TEXT DEFAULT NULL
)
RETURNS TABLE (
    id           UUID,
    summary_type TEXT,
    subject_name TEXT,
    content      TEXT,
    source_count INT,
    period_start TIMESTAMPTZ,
    period_end   TIMESTAMPTZ,
    topics       TEXT[],
    created_at   TIMESTAMPTZ,
    similarity   FLOAT
)
LANGUAGE sql STABLE AS $$
    SELECT
        id, summary_type, subject_name, content,
        source_count, period_start, period_end,
        topics, created_at,
        1 - (embedding <=> query_embedding) AS similarity
    FROM summaries
    WHERE type_filter IS NULL OR summary_type = type_filter
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;

COMMIT;
