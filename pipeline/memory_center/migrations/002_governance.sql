-- Additive governance migration; does not resume work or change legacy records.
BEGIN;
SET LOCAL search_path=memory_center;

CREATE TABLE IF NOT EXISTS record_governance(
 record_id TEXT PRIMARY KEY, holder TEXT, subject_id TEXT, as_of TEXT,
 valid_until TEXT, state TEXT NOT NULL, priority TEXT NOT NULL,
 revision INTEGER NOT NULL, note TEXT NOT NULL, reviewed DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS governance_events(
 id TEXT PRIMARY KEY, record_id TEXT NOT NULL, actor TEXT NOT NULL,
 previous TEXT NOT NULL, current TEXT NOT NULL, created DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS source_envelopes(
 source_id TEXT PRIMARY KEY, metadata TEXT NOT NULL, policy TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS model_budgets(
 owner TEXT NOT NULL, scope TEXT NOT NULL, token_limit INTEGER NOT NULL,
 tokens_spent INTEGER NOT NULL, quality_approved INTEGER NOT NULL,
 note TEXT NOT NULL, updated DOUBLE PRECISION NOT NULL, PRIMARY KEY(owner,scope));
CREATE TABLE IF NOT EXISTS model_attempts(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL,
 operation TEXT NOT NULL, reference_id TEXT NOT NULL, reservation INTEGER NOT NULL,
 charged INTEGER NOT NULL, state TEXT NOT NULL, usage TEXT, created DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS budget_events(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL,
 actor TEXT NOT NULL, detail TEXT NOT NULL, created DOUBLE PRECISION NOT NULL);

CREATE TABLE IF NOT EXISTS extraction_previews(
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL, method_version TEXT NOT NULL,
 source_digest TEXT NOT NULL, comparison TEXT NOT NULL, created DOUBLE PRECISION NOT NULL);

CREATE TABLE IF NOT EXISTS run_operations(
 run_id TEXT PRIMARY KEY, operation TEXT NOT NULL, record_id TEXT);
CREATE TABLE IF NOT EXISTS record_translations(
 record_id TEXT NOT NULL, language TEXT NOT NULL, text TEXT NOT NULL,
 run_id TEXT NOT NULL, reviewed DOUBLE PRECISION NOT NULL, PRIMARY KEY(record_id,language));
CREATE TABLE IF NOT EXISTS extraction_runs(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL,
 source_id TEXT NOT NULL, source_digest TEXT NOT NULL, method_version TEXT NOT NULL,
 request_key TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL,
 lease TEXT, lease_until DOUBLE PRECISION, preview_id TEXT, error TEXT, usage TEXT, created DOUBLE PRECISION NOT NULL,
 UNIQUE(owner,scope,request_key));

CREATE TABLE IF NOT EXISTS memory_entities(
 owner TEXT NOT NULL, scope TEXT NOT NULL, id TEXT NOT NULL,
 kind TEXT NOT NULL, name TEXT NOT NULL, aliases TEXT NOT NULL,
 PRIMARY KEY(owner,scope,id));

COMMIT;
