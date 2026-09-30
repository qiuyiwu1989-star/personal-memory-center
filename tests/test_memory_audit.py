"""All fixtures are synthetic. Audits must not alter source data."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from pipeline.memory_center.audit import audit, classify, readonly, save_private_sample
from pipeline.memory_center.core import Store


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.record = {"id": "synthetic-1", "message_id": "m1", "quote": "暂定下月开始",
                       "statement": "示例项目暂定下月开始", "status": "source_reported"}
        self.source = {"source_type": "conversation", "payload": json.dumps([
            {"id": "m1", "role": "user", "text": "暂定下月开始", "created_at": "2026-01-01"}])}
    def tearDown(self):
        self.tmp.cleanup()

    def test_quote_match_never_certifies_semantics_or_validity(self):
        flags = classify(self.record, self.source)
        self.assertNotIn("quote_not_supported", flags)
        self.assertIn("semantic_support_not_reviewed", flags)
        self.assertIn("as_of_missing", flags)
        self.assertIn("temporal_claim_needs_review", flags)

    def test_assistant_and_secondhand_attribution(self):
        source = dict(self.source, payload=json.dumps([
            {"id": "m1", "role": "assistant", "text": "暂定下月开始"}]))
        flags = classify(self.record, source)
        self.assertIn("assistant_statement", flags)
        self.assertIn("attribution_status_mismatch", flags)
        self.assertIn("source_date_missing", flags)
        flags = classify(dict(self.record, status="imported_summary"),
                         dict(self.source, source_type="imported_summary"))
        self.assertIn("secondhand_summary", flags)

    def test_missing_or_invalid_source_is_not_silently_validated(self):
        self.assertIn("source_missing", classify(self.record, None))
        self.assertIn("source_payload_invalid", classify(self.record, dict(self.source, payload="{}")))
        self.assertIn("quote_not_supported", classify(dict(self.record, quote="不存在的证据"), self.source))

    def test_readonly_owner_scope_isolation_and_private_output(self):
        with self.store.db() as db:
            for index, (owner, scope) in enumerate([("owner-a", "personal"), ("owner-b", "personal"), ("owner-a", "other")]):
                sid, rid = "source-" + str(index), "record-" + str(index)
                db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (sid, owner, scope, "synthetic", "digest", "conversation",
                            "synthetic-agent", 0, self.source["payload"], 0))
                db.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (rid, owner, scope, "projects", "plan", "synthetic-project",
                            self.record["statement"], "source_reported", sid, "m1",
                            self.record["quote"], "active", 1, None, 0))
        before = hashlib.sha256(self.store.path.read_bytes()).hexdigest()
        with readonly(self.store.path) as (db, placeholder):
            report, sample = audit(db, placeholder, "owner-a", "personal", 1)
            with self.assertRaises(Exception):
                db.execute("DELETE FROM records")
        self.assertEqual(hashlib.sha256(self.store.path.read_bytes()).hexdigest(), before)
        self.assertEqual(report["records"], 1)
        self.assertNotIn(self.record["statement"], json.dumps(report, ensure_ascii=False))
        self.assertEqual([x["record_id"] for x in sample["records"]], ["record-0"])
        out = Path(self.tmp.name) / "review.json"
        save_private_sample(out, sample)
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            save_private_sample(out, sample)
        with self.assertRaises(ValueError):
            save_private_sample(Path(__file__).parent / "forbidden.json", sample)
