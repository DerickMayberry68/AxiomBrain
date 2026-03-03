-- AxiomBrain Initial Schema
-- Run this in Supabase SQL Editor or against your PostgreSQL instance
-- Requires: PostgreSQL 15+, pgvector extension

-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- ─────────────────────────────────────────────────────────────────────────────
-- THOUGHTS  (universal inbox + immutable audit trail)
-- Every ingested item writes here regardless of routing destination
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS thoughts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content         TEXT NOT NULL,
    embedding       VECTOR(1536),
    content_type    TEXT,
    topics          TEXT[]          DEFAULT '{}',
    people          TEXT[]          DEFAULT '{}',
    action_items    TEXT[]          DEFAULT '{}',
    confidence      FLOAT           DEFAULT 0.0,
    source          TEXT,           -- tool that created this (e.g. 'claude_code', 'cursor')
    routed_to       TEXT,           -- which secondary table this was also written to
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS thoughts_embedding_idx
    ON thoughts USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS thoughts_content_type_idx ON thoughts (content_type);
CREATE INDEX IF NOT EXISTS thoughts_source_idx       ON thoughts (source);
CREATE INDEX IF NOT EXISTS thoughts_created_at_idx   ON thoughts (created_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- PEOPLE  (relationship and contact context)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS people (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    notes       TEXT,
    embedding   VECTOR(1536),
    topics      TEXT[]      DEFAULT '{}',
    last_seen   TIMESTAMPTZ DEFAULT NOW(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS people_embedding_idx
    ON people USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

CREATE INDEX IF NOT EXISTS people_name_idx ON people (name);

-- ─────────────────────────────────────────────────────────────────────────────
-- PROJECTS  (work tracking with status)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS projects (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    description TEXT,
    embedding   VECTOR(1536),
    status      TEXT        NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'paused', 'completed')),
    topics      TEXT[]      DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS projects_embedding_idx
    ON projects USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

CREATE INDEX IF NOT EXISTS projects_status_idx ON projects (status);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ─────────────────────────────────────────────────────────────────────────────
-- IDEAS  (insight capture)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ideas (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT NOT NULL,
    elaboration TEXT,
    embedding   VECTOR(1536),
    topics      TEXT[]      DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ideas_embedding_idx
    ON ideas USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

-- ─────────────────────────────────────────────────────────────────────────────
-- ADMIN  (task and action item management)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admin (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task         TEXT NOT NULL,
    embedding    VECTOR(1536),
    status       TEXT        NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending', 'in_progress', 'completed', 'cancelled')),
    due_date     TIMESTAMPTZ,
    action_items TEXT[]      DEFAULT '{}',
    topics       TEXT[]      DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS admin_embedding_idx
    ON admin USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

CREATE INDEX IF NOT EXISTS admin_status_idx ON admin (status);

-- ─────────────────────────────────────────────────────────────────────────────
-- SEMANTIC SEARCH FUNCTIONS
-- Each returns rows ordered by cosine similarity
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION match_thoughts(
    query_embedding VECTOR(1536),
    match_count     INT     DEFAULT 10,
    topic_filter    TEXT    DEFAULT NULL,
    person_filter   TEXT    DEFAULT NULL
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
        1 - (embedding <=> query_embedding) AS similarity
    FROM thoughts
    WHERE
        (topic_filter IS NULL  OR  topic_filter = ANY(topics))
        AND
        (person_filter IS NULL OR  person_filter = ANY(people))
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;


CREATE OR REPLACE FUNCTION match_people(
    query_embedding VECTOR(1536),
    match_count     INT  DEFAULT 10,
    topic_filter    TEXT DEFAULT NULL
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
        1 - (embedding <=> query_embedding) AS similarity
    FROM people
    WHERE topic_filter IS NULL OR topic_filter = ANY(topics)
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;


CREATE OR REPLACE FUNCTION match_projects(
    query_embedding VECTOR(1536),
    match_count     INT  DEFAULT 10,
    status_filter   TEXT DEFAULT NULL
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
        1 - (embedding <=> query_embedding) AS similarity
    FROM projects
    WHERE status_filter IS NULL OR status = status_filter
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;


CREATE OR REPLACE FUNCTION match_ideas(
    query_embedding VECTOR(1536),
    match_count     INT  DEFAULT 10,
    topic_filter    TEXT DEFAULT NULL
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
        1 - (embedding <=> query_embedding) AS similarity
    FROM ideas
    WHERE topic_filter IS NULL OR topic_filter = ANY(topics)
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;


CREATE OR REPLACE FUNCTION match_admin(
    query_embedding VECTOR(1536),
    match_count     INT  DEFAULT 10,
    status_filter   TEXT DEFAULT NULL
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
        1 - (embedding <=> query_embedding) AS similarity
    FROM admin
    WHERE status_filter IS NULL OR status = status_filter
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;


-- ─────────────────────────────────────────────────────────────────────────────
-- CROSS-TABLE SEARCH  (search_all returns unified results from all five tables)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION search_all(
    query_embedding VECTOR(1536),
    match_count     INT  DEFAULT 10
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
    SELECT 'thoughts' AS source_table, id, content AS primary_text,
           topics, created_at, 1 - (embedding <=> query_embedding) AS similarity
    FROM thoughts
    UNION ALL
    SELECT 'people', id, name || COALESCE(': ' || notes, ''),
           topics, created_at, 1 - (embedding <=> query_embedding)
    FROM people
    UNION ALL
    SELECT 'projects', id, name || COALESCE(': ' || description, ''),
           topics, created_at, 1 - (embedding <=> query_embedding)
    FROM projects
    UNION ALL
    SELECT 'ideas', id, title || COALESCE(': ' || elaboration, ''),
           topics, created_at, 1 - (embedding <=> query_embedding)
    FROM ideas
    UNION ALL
    SELECT 'admin', id, task,
           topics, created_at, 1 - (embedding <=> query_embedding)
    FROM admin
    ORDER BY similarity DESC
    LIMIT match_count;
$$;
