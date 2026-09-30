-- Archive catalog only. Does not migrate the live SQLite memory/worker tables.
-- Run transactionally against the selected memory database.
CREATE SCHEMA IF NOT EXISTS memory_center;
REVOKE ALL ON SCHEMA memory_center FROM PUBLIC;
CREATE TABLE IF NOT EXISTS memory_center.archive_batches (
    id text PRIMARY KEY CHECK (length(id)=64),
    owner_id text NOT NULL,
    source_kind text NOT NULL,
    bucket text NOT NULL,
    region text NOT NULL,
    archive_key text NOT NULL UNIQUE,
    archive_sha256 text NOT NULL,
    manifest_key text NOT NULL,
    manifest_sha256 text NOT NULL,
    file_count integer NOT NULL,
    source_bytes bigint NOT NULL,
    archive_bytes bigint NOT NULL,
    status text NOT NULL CHECK (status IN ('archived_verified')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS memory_center.archive_files (
    batch_id text NOT NULL REFERENCES memory_center.archive_batches(id),
    path text NOT NULL,
    bytes bigint NOT NULL,
    sha256 text NOT NULL,
    PRIMARY KEY (batch_id,path)
);
CREATE TABLE IF NOT EXISTS memory_center.archive_conversations (
    batch_id text NOT NULL REFERENCES memory_center.archive_batches(id),
    conversation_id text NOT NULL,
    title text NOT NULL,
    original_created_at text,
    original_updated_at text,
    message_count integer NOT NULL,
    archive_path text NOT NULL DEFAULT 'conversations.json',
    extraction_state text NOT NULL DEFAULT 'not_processed',
    PRIMARY KEY(batch_id,conversation_id)
);
REVOKE ALL ON ALL TABLES IN SCHEMA memory_center FROM PUBLIC;
