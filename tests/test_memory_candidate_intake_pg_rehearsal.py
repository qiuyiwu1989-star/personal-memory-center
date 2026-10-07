"""No-network safety checks for the disposable PostgreSQL rehearsal runner."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch

_PATH = Path(__file__).resolve().parents[1] / 'scripts/check_candidate_intake_migration_pg.py'
_SPEC = importlib.util.spec_from_file_location('synthetic_intake_pg_rehearsal', _PATH)
_REHEARSAL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_REHEARSAL)


class CandidateIntakePgRehearsalSafetyTests(unittest.TestCase):
    def test_only_explicit_local_disposable_names_allowed(self):
        for host in ('127.0.0.1', 'localhost', '::1', '/tmp/synthetic-pg-socket'):
            self.assertEqual(_REHEARSAL._local_scratch('dbname=memory_intake_scratch_synthetic host=' + host),
                             'memory_intake_scratch_synthetic')
        for dsn in ('dbname=memory_center host=127.0.0.1',
                    'dbname=memory_intake_scratch_ host=localhost',
                    'dbname=memory_intake_scratch_synthetic',
                    'dbname=memory_intake_scratch_synthetic host=synthetic.example.invalid',
                    'dbname=memory_intake_scratch_synthetic host=127.0.0.1,synthetic.example.invalid',
                    'dbname=memory_intake_scratch_synthetic host=127.0.0.1 hostaddr=192.0.2.1',
                    'dbname=memory_intake_scratch_synthetic host=localhost service=synthetic'):
            with self.subTest(dsn=dsn), patch('psycopg.connect') as connect:
                with self.assertRaises(ValueError): _REHEARSAL.check(dsn)
                connect.assert_not_called()

    def test_missing_scratch_dsn_never_uses_other_database_environment(self):
        with patch.dict(os.environ, {'DATABASE_URL': 'synthetic-non-scratch-dsn'}, clear=True), \
                patch.object(_REHEARSAL, 'check') as check, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(_REHEARSAL.main(), 2)
            check.assert_not_called()

    def test_driver_failure_does_not_print_connection_details(self):
        err = io.StringIO(); out = io.StringIO()
        with patch.dict(os.environ, {'QIU_MEMORY_INTAKE_SCRATCH_DSN': 'synthetic-sensitive-dsn'}), \
                patch.object(_REHEARSAL, 'check', side_effect=RuntimeError('synthetic-sensitive-dsn synthetic-password')), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            self.assertEqual(_REHEARSAL.main(), 1)
        self.assertIn('RuntimeError', err.getvalue())
        self.assertNotIn('synthetic-sensitive', err.getvalue() + out.getvalue())
        self.assertNotIn('synthetic-password', err.getvalue() + out.getvalue())


if __name__ == '__main__': unittest.main()
