-- AxiomBrain — Migration 005: Multi-workspace support
-- Adds a workspaces table and workspace_id columns to all memory tables.
-- Enables full isolation between teams / workspace instances.
--
-- NOTE: This migration adds workspace_id as nullable. The Python migration
-- runner (migrate.py) handles the post-migration steps:
--   1. Creates the default workspace using the configured API key
--   2. Backfills workspace_id on all existing rows
--   3. Sets workspace_id NOT NULL on all tables
--
-- All match_* and search_all functions are updated to accept an optional
-- p_workspace_id parameter. NULL = no filter (backward-compat during migration).

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Workspaces table
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE workspaces (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name       TEXT        NOT NULL,
    slug       TEXT        NOT NULL UNIQUE,
    api_key    TEXT        NOT NULL UNIQUE,
    is_active  BOOLEAN     NOT NULL DEFAULT TRUE,
    is_admin   BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_workspaces_api_key ON workspaces (api_key);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Add workspace_id to all memory tables (nullable — backfilled by Python)
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE thoughts      ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE;
ALTER TABLE admin         ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE;
ALTER TABLE ideas         ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE;
ALTER TABLE people        ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE;
ALTER TABLE projects      ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE;
ALTER TABLE summaries     ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE;
ALTER TABLE relationships ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE;

-- Indexes for workspace-scoped queries
CREATE INDEX IF NOT EXISTS idx_thoughts_workspace      ON thoughts      (workspace_id);
CREATE INDEX IF NOT EXISTS idx_admin_workspace         ON admin         (workspace_id);
CREATE INDEX IF NOT EXISTS idx_ideas_workspace         ON ideas         (workspace_id);
CREATE INDEX IF NOT EXISTS idx_people_workspace        ON people        (workspace_id);
CREATE INDEX IF NOT EXISTS idx_projects_workspace      ON projects      (workspace_id);
CREATE INDEX IF NOT EXISTS idx_summaries_workspace     ON summaries     (workspace_id);
CREATE INDEX IF NOT EXISTS idx_relationships_workspace ON relationships (workspace_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Update match_* functions to accept workspace_id filter
--    p_workspace_id = NULL  →  no filter (backward compat / admin cross-search)
--    p_workspace_id = <id>  →  only return rows from that workspace
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION match_thoughts(
    query_embedding VECTOR(1536),
    match_count     INT     DEFAULT 10,
    topic_filter    TEXT    DEFAULT NULL,
    person_filter   TEXT    DEFAULT NULL,
    p_workspace_id  UUID    DEFAULT NULL
)
RETURNS TABLE (
    id           UUID,
    content      TEXT,
    content_type TEXT,
    topics       TEXT[],
    people       TEXT[],
    action_items TEXT[],
    source       TEXT,
    created_at   TIMESTAMPTZ,
    similarity   FLOAT
)
LANGUAGE sql STABLE AS $$
    SELECT
        id, content, content_type, topics, people, action_items,
        source, created_at,
        (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) AS similarity
    FROM thoughts
    WHERE
        (p_workspace_id IS NULL OR workspace_id = p_workspace_id)
        AND (topic_filter  IS NULL OR topic_filter  = ANY(topics))
        AND (person_filter IS NULL OR person_filter = ANY(people))
    ORDER BY (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) DESC
    LIMIT match_count;
$$;


CREATE OR REPLACE FUNCTION match_people(
    query_embedding VECTOR(1536),
    match_count     INT  DEFAULT 10,
    topic_filter    TEXT DEFAULT NULL,
    p_workspace_id  UUID DEFAULT NULL
)
RETURNS TABLE (
    id         UUID,
    name       TEXT,
    notes      TEXT,
    topics     TEXT[],
    last_seen  TIMESTAMPTZ,
    similarity FLOAT
)
LANGUAGE sql STABLE AS $$
    SELECT
        id, name, notes, topics, last_seen,
        (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) AS similarity
    FROM people
    WHERE
        (p_workspace_id IS NULL OR workspace_id = p_workspace_id)
        AND (topic_filter IS NULL OR topic_filter = ANY(topics))
    ORDER BY (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) DESC
    LIMIT match_count;
$$;


CREATE OR REPLACE FUNCTION match_projects(
    query_embedding VECTOR(1536),
    match_count     INT  DEFAULT 10,
    status_filter   TEXT DEFAULT NULL,
    p_workspace_id  UUID DEFAULT NULL
)
RETURNS TABLE (
    id          UUID,
    name        TEXT,
    description TEXT,
    status      TEXT,
    topics      TEXT[],
    updated_at  TIMESTAMPTZ,
    similarity  FLOAT
)
LANGUAGE sql STABLE AS $$
    SELECT
        id, name, description, status, topics, updated_at,
        (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) AS similarity
    FROM projects
    WHERE
        (p_workspace_id IS NULL OR workspace_id = p_workspace_id)
        AND (status_filter IS NULL OR status = status_filter)
    ORDER BY (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) DESC
    LIMIT match_count;
$$;


CREATE OR REPLACE FUNCTION match_ideas(
    query_embedding VECTOR(1536),
    match_count     INT  DEFAULT 10,
    topic_filter    TEXT DEFAULT NULL,
    p_workspace_id  UUID DEFAULT NULL
)
RETURNS TABLE (
    id          UUID,
    title       TEXT,
    elaboration TEXT,
    topics      TEXT[],
    created_at  TIMESTAMPTZ,
    similarity  FLOAT
)
LANGUAGE sql STABLE AS $$
    SELECT
        id, title, elaboration, topics, created_at,
        (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) AS similarity
    FROM ideas
    WHERE
        (p_workspace_id IS NULL OR workspace_id = p_workspace_id)
        AND (topic_filter IS NULL OR topic_filter = ANY(topics))
    ORDER BY (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) DESC
    LIMIT match_count;
$$;


CREATE OR REPLACE FUNCTION match_admin(
    query_embedding VECTOR(1536),
    match_count     INT  DEFAULT 10,
    status_filter   TEXT DEFAULT NULL,
    p_workspace_id  UUID DEFAULT NULL
)
RETURNS TABLE (
    id           UUID,
    task         TEXT,
    status       TEXT,
    due_date     TIMESTAMPTZ,
    action_items TEXT[],
    topics       TEXT[],
    created_at   TIMESTAMPTZ,
    similarity   FLOAT
)
LANGUAGE sql STABLE AS $$
    SELECT
        id, task, status, due_date, action_items, topics, created_at,
        (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) AS similarity
    FROM admin
    WHERE
        (p_workspace_id IS NULL OR workspace_id = p_workspace_id)
        AND (status_filter IS NULL OR status = status_filter)
    ORDER BY (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) DESC
    LIMIT match_count;
$$;


-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Update search_all to accept workspace_id filter
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION search_all(
    query_embedding VECTOR(1536),
    match_count     INT  DEFAULT 10,
    p_workspace_id  UUID DEFAULT NULL
)
RETURNS TABLE (
    source_table TEXT,
    id           UUID,
    primary_text TEXT,
    topics       TEXT[],
    created_at   TIMESTAMPTZ,
    similarity   FLOAT
)
LANGUAGE sql STABLE AS $$
    SELECT 'thoughts' AS source_table, id,
           content AS primary_text,
           topics, created_at,
           (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) AS similarity
    FROM thoughts
    WHERE (p_workspace_id IS NULL OR workspace_id = p_workspace_id)
    UNION ALL
    SELECT 'people', id,
           name || COALESCE(': ' || notes, ''),
           topics, created_at,
           (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20)
    FROM people
    WHERE (p_workspace_id IS NULL OR workspace_id = p_workspace_id)
    UNION ALL
    SELECT 'projects', id,
           name || COALESCE(': ' || description, ''),
           topics, created_at,
           (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20)
    FROM projects
    WHERE (p_workspace_id IS NULL OR workspace_id = p_workspace_id)
    UNION ALL
    SELECT 'ideas', id,
           title || COALESCE(': ' || elaboration, ''),
           topics, created_at,
           (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20)
    FROM ideas
    WHERE (p_workspace_id IS NULL OR workspace_id = p_workspace_id)
    UNION ALL
    SELECT 'admin', id,
           task,
           topics, created_at,
           (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20)
    FROM admin
    WHERE (p_workspace_id IS NULL OR workspace_id = p_workspace_id)
    ORDER BY similarity DESC
    LIMIT match_count;
$$;
