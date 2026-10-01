BEGIN;
SET search_path TO memory_center;
CREATE TABLE IF NOT EXISTS archive_replans(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, batch_id TEXT NOT NULL,
 scope TEXT NOT NULL, archive_digest TEXT NOT NULL, parser_version TEXT NOT NULL,
 payload TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL, adopted REAL);
COMMIT;
