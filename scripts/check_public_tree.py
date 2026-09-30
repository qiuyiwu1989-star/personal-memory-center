"""Scan publishable files. Reports filenames/rules only, never matched values."""
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"model.json", "grants.json", "browser.json", "owner-token.txt", "service.env", ".env"}
PRIVATE_DIRS = {"runtime", "archives", "backups", "private", "reports"}
PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github-token": re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
    "model-api-key": re.compile(r"(?:ark-[0-9a-f]{8}-[0-9a-f-]{20,}|sk-[A-Za-z0-9_-]{24,})"),
    "cloud-secret": re.compile(r"AKID[A-Za-z0-9]{16,}"),
    "live-model-endpoint": re.compile(r"ep-[0-9]{14}-[A-Za-z0-9]+"),
    "user-home-path": re.compile(r"/(?:Users)/[^/\s]+/|/(?:home)/(?!runner\b)[^/\s]+/"),
}


def paths():
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            cwd=ROOT, capture_output=True)
    if result.returncode:
        raise RuntimeError("Run inside an initialized repository")
    return sorted(set(Path(x.decode()) for x in result.stdout.split(b"\0") if x))


def main():
    issues = []
    files = paths()
    for relative in files:
        path = ROOT / relative
        if path.is_symlink():
            issues.append((relative, "symlink"))
            continue
        if relative.name in FORBIDDEN or any(p in PRIVATE_DIRS for p in relative.parts) or path.suffix in {".db", ".sqlite3", ".dump", ".zip", ".gz"}:
            issues.append((relative, "private-runtime-file"))
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            issues.append((relative, "unexpected-binary"))
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(text):
                issues.append((relative, name))
        if path.suffix == ".json":
            try:
                fixture = json.loads(text)
                if not isinstance(fixture, dict) or fixture.get("synthetic") is not True:
                    issues.append((relative, "json-must-be-marked-synthetic"))
            except ValueError:
                issues.append((relative, "invalid-json"))
    if issues:
        for path, rule in issues:
            print(str(path) + ": " + rule)
        return 1
    print("Public-tree scan passed: " + str(len(files)) + " files; review scope remains source code and synthetic fixtures only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
