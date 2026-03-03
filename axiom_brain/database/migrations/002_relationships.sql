-- AxiomBrain Migration 002 — Graph Relationships
-- Generic edge table linking any node to any other node across all memory tables.
-- Supports both auto-detected edges (from the ingest classifier) and manual edges.

BEGIN;

-- ── Edge table ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS relationships (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    from_table      TEXT        NOT NULL
                    CHECK (from_table IN ('thoughts','people','projects','ideas','admin')),
    from_id         UUID        NOT NULL,
    to_table        TEXT        NOT NULL
                    CHECK (to_table IN ('thoughts','people','projects','ideas','admin')),
    to_id           UUID        NOT NULL,
    rel_type        TEXT        NOT NULL,
    -- Supported types:
    --   person  → project : 'works_on'
    --   idea    → project : 'belongs_to'
    --   thought → project : 'recorded_in'
    --   person  → idea    : 'originated'
    --   (any)   → (any)   : 'related_to'  (generic fallback)
    strength        FLOAT       NOT NULL DEFAULT 1.0
                    CHECK (strength >= 0.0 AND strength <= 1.0),
    auto_detected   BOOLEAN     NOT NULL DEFAULT FALSE,
    source          TEXT,                          -- which tool created this edge
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB       NOT NULL DEFAULT '{}',
    -- Prevent duplicate edges of the same type between the same pair of nodes
    UNIQUE (from_table, from_id, to_table, to_id, rel_type)
);

-- ── Indexes ───────────────────────────────────────────────────────────────────

-- Fast lookup: "give me all edges FROM this node"
CREATE INDEX IF NOT EXISTS idx_rel_from
    ON relationships (from_table, from_id);

-- Fast lookup: "give me all edges TO this node"
CREATE INDEX IF NOT EXISTS idx_rel_to
    ON relationships (to_table, to_id);

-- Filter by relationship type
CREATE INDEX IF NOT EXISTS idx_rel_type
    ON relationships (rel_type);

-- Auto-detected flag (useful for filtering out manual edges)
CREATE INDEX IF NOT EXISTS idx_rel_auto
    ON relationships (auto_detected);

-- ── Helper function: get all edges for a node (both directions) ───────────────

CREATE OR REPLACE FUNCTION get_node_edges(
    p_table  TEXT,
    p_id     UUID,
    p_dir    TEXT DEFAULT 'both'  -- 'from' | 'to' | 'both'
)
RETURNS TABLE (
    id            UUID,
    from_table    TEXT,
    from_id       UUID,
    to_table      TEXT,
    to_id         UUID,
    rel_type      TEXT,
    strength      FLOAT,
    auto_detected BOOLEAN,
    source        TEXT,
    created_at    TIMESTAMPTZ,
    metadata      JSONB
)
LANGUAGE sql STABLE AS $$
    SELECT id, from_table, from_id, to_table, to_id,
           rel_type, strength, auto_detected, source, created_at, metadata
    FROM   relationships
    WHERE  (p_dir IN ('from','both') AND from_table = p_table AND from_id = p_id)
        OR (p_dir IN ('to',  'both') AND to_table   = p_table AND to_id   = p_id)
    ORDER BY strength DESC, created_at DESC;
$$;

COMMIT;
