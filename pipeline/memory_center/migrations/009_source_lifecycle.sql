CREATE TABLE IF NOT EXISTS source_withdrawals(
 source_id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL,
 actor TEXT NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL, receipt TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS source_withdrawal_scope ON source_withdrawals(owner,scope);
