import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout

spec = importlib.util.spec_from_file_location("release_check", Path(__file__).parents[1] / "scripts/check_memory_release.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReleaseCheckTests(unittest.TestCase):
    def setUp(self):
        self.expected = {"backend_release": "a" * 40, "frontend_release": "b" * 40 + "-ui-only",
                         "backend_files": {"pipeline/memory_center/model.py": "c" * 64},
                         "frontend_files": {"assets/memory-center.js": "d" * 64},
                         "routes": {"/assets/memory-center.js": "e" * 64},
                         "required_tools": ["memory_candidate_search", "memory_context"]}
        self.observed = copy.deepcopy(self.expected)
        self.observed.pop("required_tools")
        self.observed.update(process_release="a" * 40, health_ok=True,
                             tools=["memory_candidate_search", "memory_context", "memory_search"])

    def check(self):
        return module.check_release(self.expected, self.observed)

    def test_split_backend_frontend_versions_are_valid(self):
        self.assertTrue(self.check()["matches"])
        self.assertFalse(self.check()["live_collection_verified"])

    def test_process_pointer_mismatch(self):
        self.observed["process_release"] = "f" * 40
        self.assertIn("process_pointer_mismatch", self.check()["failures"])

    def test_missing_ui_route(self):
        self.observed["routes"] = {}
        self.assertEqual(self.check()["failures"], ["routes_drift"])

    def test_pointer_match_is_insufficient_for_code_integrity(self):
        self.observed["backend_files"]["pipeline/memory_center/model.py"] = "f" * 64
        self.assertIn("backend_files_drift", self.check()["failures"])

    def test_old_toolset_is_detected(self):
        self.observed["tools"] = ["memory_context", "memory_search"]
        self.assertIn("required_tools_missing", self.check()["failures"])

    def test_health_truthy_is_not_verified(self):
        self.observed["health_ok"] = 1
        self.assertIn("health_not_verified", self.check()["failures"])

    def test_missing_expectation_is_invalid(self):
        self.expected["routes"] = {}
        with self.assertRaises(ValueError):
            self.check()

    def test_malformed_cli_does_not_echo_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.json"
            path.write_text('{"secret": "never-echo-this"}')
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(module.main(["--expected", str(path), "--observed", str(path)]), 2)
            self.assertNotIn("never-echo-this", output.getvalue())

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as temp:
            expected, observed = Path(temp) / "expected.json", Path(temp) / "observed.json"
            expected.write_text(json.dumps(self.expected))
            observed.write_text(json.dumps(self.observed))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(module.main(["--expected", str(expected), "--observed", str(observed)]), 0)
                self.observed["routes"] = {}
                observed.write_text(json.dumps(self.observed))
                self.assertEqual(module.main(["--expected", str(expected), "--observed", str(observed)]), 1)


if __name__ == "__main__":
    unittest.main()
