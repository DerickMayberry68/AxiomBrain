-- AxiomBrain — Migration 004: Decay Scoring
-- Adds access tracking + precomputed decay scores to all memory tables.
-- Replaces match_* and search_all functions with decay-weighted versions.
--
-- Decay model: exponential half-life
--   decay_score = exp(-ln(2) / half_life_days * days_since_last_access)
--   Floored at 0.10 so memories never become completely invisible.
--
-- Half-life per table:
--   thoughts   30 days  (short-lived observations)
--   admin      14 days  (tasks go stale quickly)
--   ideas      60 days  (insights stay valuable longer)
--   people     90 days  (contact context is long-lived)
--   projects   90 days  (project context is long-lived)

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Add columns to all five tables
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE thoughts
    ADD COLUMN IF NOT EXISTS access_count    INT         NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS decay_score     FLOAT       NOT NULL DEFAULT 1.0;

ALTER TABLE people
    ADD COLUMN IF NOT EXISTS access_count    INT         NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS decay_score     FLOAT       NOT NULL DEFAULT 1.0;

ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS access_count    INT         NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS decay_score     FLOAT       NOT NULL DEFAULT 1.0;

ALTER TABLE ideas
    ADD COLUMN IF NOT EXISTS access_count    INT         NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS decay_score     FLOAT       NOT NULL DEFAULT 1.0;

ALTER TABLE admin
    ADD COLUMN IF NOT EXISTS access_count    INT         NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS decay_score     FLOAT       NOT NULL DEFAULT 1.0;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Indexes for efficient bulk recalculation
-- ─────────────────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_thoughts_last_accessed  ON thoughts  (last_accessed_at);
CREATE INDEX IF NOT EXISTS idx_people_last_accessed    ON people    (last_accessed_at);
CREATE INDEX IF NOT EXISTS idx_projects_last_accessed  ON projects  (last_accessed_at);
CREATE INDEX IF NOT EXISTS idx_ideas_last_accessed     ON ideas     (last_accessed_at);
CREATE INDEX IF NOT EXISTS idx_admin_last_accessed     ON admin     (last_accessed_at);

-- Index on decay_score for filtered queries (e.g. "fresh memories only")
CREATE INDEX IF NOT EXISTS idx_thoughts_decay  ON thoughts  (decay_score);
CREATE INDEX IF NOT EXISTS idx_people_decay    ON people    (decay_score);
CREATE INDEX IF NOT EXISTS idx_projects_decay  ON projects  (decay_score);
CREATE INDEX IF NOT EXISTS idx_ideas_decay     ON ideas     (decay_score);
CREATE INDEX IF NOT EXISTS idx_admin_decay     ON admin     (decay_score);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Core decay formula (pure SQL, immutable — safe to index/inline)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION compute_decay_score(
    reference_time  TIMESTAMPTZ,  -- last_accessed_at OR created_at
    half_life_days  FLOAT,
    floor_score     FLOAT  DEFAULT 0.10
)
RETURNS FLOAT
LANGUAGE sql IMMUTABLE AS $$
    SELECT GREATEST(
        floor_score,
        EXP(
            -LN(2.0) / half_life_days
            * GREATEST(0, EXTRACT(EPOCH FROM (NOW() - reference_time)) / 86400.0)
        )
    );
$$;

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Bulk recalculation procedure — called nightly by the Python scheduler
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE PROCEDURE recalculate_all_decay()
LANGUAGE plpgsql AS $$
BEGIN
    -- thoughts: 30-day half-life
    UPDATE thoughts
    SET    decay_score = compute_decay_score(
               COALESCE(last_accessed_at, created_at), 30.0
           );

    -- admin: 14-day half-life (tasks go stale fastest)
    UPDATE admin
    SET    decay_score = compute_decay_score(
               COALESCE(last_accessed_at, created_at), 14.0
           );

    -- ideas: 60-day half-life
    UPDATE ideas
    SET    decay_score = compute_decay_score(
               COALESCE(last_accessed_at, created_at), 60.0
           );

    -- people: 90-day half-life (use last_seen as activity proxy)
    UPDATE people
    SET    decay_score = compute_decay_score(
               COALESCE(last_accessed_at, last_seen, created_at), 90.0
           );

    -- projects: 90-day half-life (use updated_at as activity proxy)
    UPDATE projects
    SET    decay_score = compute_decay_score(
               COALESCE(last_accessed_at, updated_at, created_at), 90.0
           );
END;
$$;

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. Replace match_* functions with decay-weighted versions
--
-- Ranked score formula:
--   ranked = cosine_similarity * GREATEST(decay_score, 0.20)
--
-- A fully-fresh memory (decay=1.0) gets 100% of its similarity.
-- A half-decayed memory (decay=0.5) gets 50% — it needs to be semantically
-- twice as relevant to beat the fresh one.
-- Floor of 0.20 means even old memories surface if they're highly relevant.
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
        (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) AS similarity
    FROM thoughts
    WHERE
        (topic_filter IS NULL  OR topic_filter  = ANY(topics))
        AND
        (person_filter IS NULL OR person_filter = ANY(people))
    ORDER BY (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) DESC
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
        (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) AS similarity
    FROM people
    WHERE topic_filter IS NULL OR topic_filter = ANY(topics)
    ORDER BY (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) DESC
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
        (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) AS similarity
    FROM projects
    WHERE status_filter IS NULL OR status = status_filter
    ORDER BY (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) DESC
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
        (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) AS similarity
    FROM ideas
    WHERE topic_filter IS NULL OR topic_filter = ANY(topics)
    ORDER BY (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) DESC
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
        (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) AS similarity
    FROM admin
    WHERE status_filter IS NULL OR status = status_filter
    ORDER BY (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) DESC
    LIMIT match_count;
$$;


-- ─────────────────────────────────────────────────────────────────────────────
-- 6. Replace search_all with decay-weighted version
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
    SELECT 'thoughts' AS source_table, id,
           content AS primary_text,
           topics, created_at,
           (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20) AS similarity
    FROM thoughts
    UNION ALL
    SELECT 'people', id,
           name || COALESCE(': ' || notes, ''),
           topics, created_at,
           (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20)
    FROM people
    UNION ALL
    SELECT 'projects', id,
           name || COALESCE(': ' || description, ''),
           topics, created_at,
           (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20)
    FROM projects
    UNION ALL
    SELECT 'ideas', id,
           title || COALESCE(': ' || elaboration, ''),
           topics, created_at,
           (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20)
    FROM ideas
    UNION ALL
    SELECT 'admin', id,
           task,
           topics, created_at,
           (1 - (embedding <=> query_embedding)) * GREATEST(decay_score, 0.20)
    FROM admin
    ORDER BY similarity DESC
    LIMIT match_count;
$$;
