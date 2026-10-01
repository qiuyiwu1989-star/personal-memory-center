-- Owner/scope-coalesced technical index work, no extraction or budget fields.
CREATE TABLE IF NOT EXISTS scope_index_queue(
 owner TEXT NOT NULL, scope TEXT NOT NULL,
 generation INTEGER NOT NULL, indexed_generation INTEGER NOT NULL,
 state TEXT NOT NULL, lease TEXT, lease_until DOUBLE PRECISION,
 attempts INTEGER NOT NULL, error_type TEXT, retry_after DOUBLE PRECISION,
 updated DOUBLE PRECISION NOT NULL, last_indexed DOUBLE PRECISION,
 PRIMARY KEY(owner,scope)
);
CREATE INDEX IF NOT EXISTS scope_index_queue_ready ON scope_index_queue(state,updated);
