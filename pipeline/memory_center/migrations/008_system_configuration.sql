
CREATE TABLE IF NOT EXISTS system_config_versions(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL,
 kind TEXT NOT NULL, label TEXT NOT NULL, payload TEXT NOT NULL,
 actor TEXT NOT NULL, created DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS system_config_active(
 owner TEXT NOT NULL, scope TEXT NOT NULL, kind TEXT NOT NULL,
 version_id TEXT NOT NULL, revision INTEGER NOT NULL,
 PRIMARY KEY(owner,scope,kind));
CREATE TABLE IF NOT EXISTS system_config_events(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL,
 kind TEXT NOT NULL, version_id TEXT NOT NULL, previous_id TEXT,
 actor TEXT NOT NULL, note TEXT NOT NULL, created DOUBLE PRECISION NOT NULL);
