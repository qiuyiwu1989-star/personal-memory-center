-- Apply separately after recovery rehearsal; no historical backfill or inference.
CREATE TABLE IF NOT EXISTS memory_change_events(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL, record_id TEXT NOT NULL,
 previous_record_id TEXT, record_revision INTEGER NOT NULL, governance_revision INTEGER NOT NULL,
 change_kind TEXT NOT NULL, valid_from TEXT, valid_until TEXT, previous_valid_until TEXT,
 recorded_at DOUBLE PRECISION NOT NULL, previous_retired_at DOUBLE PRECISION,
 actor TEXT NOT NULL, request_key TEXT NOT NULL, UNIQUE(owner,scope,request_key));
CREATE TABLE IF NOT EXISTS scope_projection_state(
 owner TEXT NOT NULL, scope TEXT NOT NULL, generation INTEGER NOT NULL,
 refreshed_generation INTEGER NOT NULL, state TEXT NOT NULL, updated DOUBLE PRECISION NOT NULL,
 refreshed_at DOUBLE PRECISION, PRIMARY KEY(owner,scope));
CREATE INDEX IF NOT EXISTS memory_change_scope ON memory_change_events(owner,scope,recorded_at);
