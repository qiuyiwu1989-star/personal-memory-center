-- Deterministic visible-source discovery, compatible with SQLite and PostgreSQL.
CREATE TABLE IF NOT EXISTS source_discovery_versions(
 source_id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL,
 source_digest TEXT NOT NULL, payload_digest TEXT NOT NULL, index_version TEXT NOT NULL,
 indexed REAL NOT NULL, messages_count INTEGER NOT NULL, chunks_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS discovery_versions_scope ON source_discovery_versions(owner,scope);
CREATE TABLE IF NOT EXISTS source_discovery_chunks(
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL, owner TEXT NOT NULL, scope TEXT NOT NULL,
 source_digest TEXT NOT NULL, message_id TEXT NOT NULL, message_index INTEGER NOT NULL,
 role TEXT NOT NULL, material_type TEXT NOT NULL, source_key TEXT NOT NULL,
 source_title TEXT NOT NULL, source_date TEXT NOT NULL,
 start_char INTEGER NOT NULL, end_char INTEGER NOT NULL, text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS discovery_chunks_scope ON source_discovery_chunks(owner,scope,source_id);
