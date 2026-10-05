"""Real HTTP protocol acceptance with ephemeral synthetic data, never production."""
import unittest

from scripts.check_memory_integration_contract import run_contract


class IntegrationContractHTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_contract()
        cls.checks = set(cls.report['checks_passed'])

    def test_handshake_and_contract_boundaries(self):
        self.assertEqual(self.report['transport'], 'real-loopback-http')
        self.assertTrue({'initialize', 'initialized-notification', 'tools-list',
            'stateless-no-session-header', 'parent-key-is-metadata-not-top-level',
            'source-key-300-codepoints-accepted', 'normalized-json-codepoint-count',
            '24001-normalized-chars-denied', 'unknown-metadata-denied',
            'roles-preserved-external'} <= self.checks)

    def test_retries_archive_context_and_permission_enforcement(self):
        self.assertTrue({'exact-retry-idempotent', 'same-key-changed-digest-new-source',
            'archive-no-model-usage', 'archived-is-not-verified-context',
            'cross-scope-read-denied', 'cross-scope-write-denied',
            'read-only-import-denied', 'read-only-source-withdrawal-denied',
            'extract-denied', 'reextract-denied', 'source-read-action-required',
            'revocation-next-request-401'} <= self.checks)
        self.assertEqual(self.report['model_calls'], 0)
        self.assertEqual(self.report['remote_network_calls'], 0)

    def test_receipt_does_not_claim_external_or_production_acceptance(self):
        self.assertTrue(self.report['synthetic'])
        self.assertFalse(self.report['external_client_verified'])
        self.assertFalse(self.report['production_verified'])
        self.assertTrue(self.report['source_withdrawal_verified'])
        self.assertEqual(self.report['synthetic_fixture_records'], 1)
        self.assertTrue({'agent-source-withdrawal-denied', 'owner-source-impact-preview',
            'owner-source-withdrawal-idempotent', 'withdrawal-hides-context-and-changes-revision',
            'withdrawal-retains-audit-record-and-archive', 'withdrawn-original-hidden-from-agent'} <= self.checks)


if __name__ == '__main__':
    unittest.main()
