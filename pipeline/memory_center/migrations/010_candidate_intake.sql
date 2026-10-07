CREATE TABLE IF NOT EXISTS candidate_intake_receipts(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL,
 principal TEXT NOT NULL, request_key TEXT NOT NULL, digest TEXT NOT NULL,
 source_id TEXT NOT NULL, receipt TEXT NOT NULL, created DOUBLE PRECISION NOT NULL,
 UNIQUE(owner,scope,principal,request_key));
CREATE INDEX IF NOT EXISTS candidate_intake_scope
 ON candidate_intake_receipts(owner,scope,created,id);
CREATE TABLE IF NOT EXISTS candidate_intake_evidence(
 record_id TEXT PRIMARY KEY, receipt_id TEXT NOT NULL,
 client_candidate_id TEXT, message_role TEXT NOT NULL,
 quote_start INTEGER NOT NULL, quote_end INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS candidate_intake_receipt
 ON candidate_intake_evidence(receipt_id,record_id);
