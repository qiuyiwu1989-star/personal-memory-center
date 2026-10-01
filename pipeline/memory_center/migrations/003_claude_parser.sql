-- Additive marker only. Do not mark legacy flattened plans as verified visible text.
BEGIN;
SET search_path TO memory_center;
CREATE TABLE IF NOT EXISTS bulk_batch_parsers(
 batch_id TEXT PRIMARY KEY, parser_version TEXT NOT NULL);
COMMIT;
