"""Compare fixed release expectations with an offline, sanitized observation.

No network, credentials, model, deployment or automatic rollback. The caller must
collect current observations independently; a manifest match is not a live probe.
"""
import argparse
import json
from pathlib import Path
import re

SHA = re.compile(r"[0-9a-f]{64}\Z")
RELEASE = re.compile(r"[0-9a-f]{7,64}(?:-ui-only)?\Z")
FIELDS = {"backend_release", "frontend_release", "backend_files", "frontend_files",
          "routes", "required_tools"}


def validate_expected(value):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("invalid_expectation")
    for key in ("backend_release", "frontend_release"):
        if not isinstance(value[key], str) or not RELEASE.fullmatch(value[key]):
            raise ValueError("invalid_release")
    for key in ("backend_files", "frontend_files"):
        files = value[key]
        if not isinstance(files, dict) or not files:
            raise ValueError("missing_file_expectations")
        for name, digest in files.items():
            if (not isinstance(name, str) or not name or name.startswith("/")
                    or ".." in name.split("/") or "\\" in name
                    or not isinstance(digest, str) or not SHA.fullmatch(digest)):
                raise ValueError("invalid_file_expectation")
    routes = value["routes"]
    if not isinstance(routes, dict) or not routes:
        raise ValueError("missing_route_expectations")
    if any(not isinstance(uri, str) or not uri.startswith("/")
           or not isinstance(digest, str) or not SHA.fullmatch(digest)
           for uri, digest in routes.items()):
        raise ValueError("invalid_route_expectation")
    tools = value["required_tools"]
    if (not isinstance(tools, list) or not tools
            or any(not isinstance(t, str) or not re.fullmatch(r"memory_[a-z_]+", t)
                   for t in tools) or len(tools) != len(set(tools))):
        raise ValueError("invalid_tool_expectation")


def check_release(expected, observed):
    """Fail closed on missing/drifting evidence; report reason codes, no inputs."""
    validate_expected(expected)
    if not isinstance(observed, dict):
        raise ValueError("invalid_observation")
    failures = []
    for key in ("backend_release", "frontend_release"):
        if observed.get(key) != expected[key]:
            failures.append(key + "_drift")
    if observed.get("process_release") != expected["backend_release"]:
        failures.append("process_release_drift")
    if observed.get("process_release") != observed.get("backend_release"):
        failures.append("process_pointer_mismatch")
    for key in ("backend_files", "frontend_files", "routes"):
        actual = observed.get(key)
        if not isinstance(actual, dict):
            failures.append(key + "_missing")
        elif any(actual.get(name) != digest for name, digest in expected[key].items()):
            failures.append(key + "_drift")
    tools = observed.get("tools")
    if (not isinstance(tools, list) or any(not isinstance(t, str) for t in tools)
            or len(tools) != len(set(tools))):
        failures.append("tools_invalid")
    elif not set(expected["required_tools"]).issubset(tools):
        failures.append("required_tools_missing")
    if observed.get("health_ok") is not True:
        failures.append("health_not_verified")
    return {"mode": "offline-release-comparison", "matches": not failures,
            "failures": failures, "network_calls": 0, "model_calls": 0,
            "production_writes": 0, "automatic_rollback": False,
            "live_collection_verified": False}


def read_json(path):
    if path.stat().st_size > 1_000_000:
        raise ValueError("input_too_large")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", required=True, type=Path)
    parser.add_argument("--observed", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = check_release(read_json(args.expected), read_json(args.observed))
    except (OSError, UnicodeError, ValueError, TypeError):
        print(json.dumps({"matches": False, "failures": ["invalid_input"]}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["matches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
