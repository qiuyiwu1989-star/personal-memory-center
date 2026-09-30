"""Read-only structural audit. No model calls, writes, or semantic-quality claims."""
import argparse
from collections import Counter, OrderedDict
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

METHOD = "structural-audit-v1"
TRANSIENT = re.compile(r"字数|改写|下一段|继续第|第[一二三四五六七八九十0-9]+章|rewrite|word count", re.I)
TEMPORAL = re.compile(r"计划|暂定|完成|截止|下周|下月|planned|deadline|completed", re.I)


def classify(record, source):
    """Return review signals, not truth labels, priorities, or promotions."""
    flags = []
    message = None
    if source is None:
        flags.append("source_missing")
    else:
        try:
            payload = json.loads(source["payload"])
            if not isinstance(payload, list):
                raise ValueError()
            message = next((m for m in payload if isinstance(m, dict)
                            and m.get("id") == record["message_id"]), None)
        except (ValueError, TypeError):
            flags.append("source_payload_invalid")
        if source["source_type"] == "imported_summary":
            flags.append("secondhand_summary")
    if message is None:
        flags.append("message_missing")
    else:
        quote = record.get("quote")
        text = message.get("text")
        if not isinstance(quote, str) or not quote or not isinstance(text, str) or quote not in text:
            flags.append("quote_not_supported")
        role = message.get("role")
        if role == "assistant":
            flags.append("assistant_statement")
            if record["status"] != "agent_suggested":
                flags.append("attribution_status_mismatch")
        elif role == "external":
            flags.append("external_statement")
        elif role != "user":
            flags.append("speaker_unknown")
        if not message.get("created_at"):
            flags.append("source_date_missing")
    # Legacy records lack these fields. Never substitute import time or
    # message role for a resolved holder, stable entity, or valid-from date.
    for field in ("holder_id", "subject_id", "as_of"):
        if not record.get(field):
            flags.append(field + "_missing")
    if source is not None and source["source_type"] == "correction":
        flags.append("explicit_correction")
    else:
        flags.append("semantic_support_not_reviewed")
    statement = record.get("statement", "")
    if TRANSIENT.search(statement):
        flags.append("transient_task_signal")
    if TEMPORAL.search(statement):
        flags.append("temporal_claim_needs_review")
    return sorted(set(flags))


@contextmanager
def readonly(sqlite_path=None, dsn=None):
    """Do not construct Store: initialization could mutate a live schema."""
    if sqlite_path is not None:
        path = Path(sqlite_path).expanduser().resolve(strict=True)
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        placeholder = "?"
    else:
        import psycopg
        from psycopg.rows import dict_row
        db = psycopg.connect(dsn, row_factory=dict_row)
        db.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        db.execute("SET LOCAL search_path = memory_center")
        db.execute("SET LOCAL statement_timeout = '60s'")
        placeholder = "%s"
    try:
        yield db, placeholder
    finally:
        db.rollback()
        db.close()


def audit(db, placeholder, owner, scope, sample_per_status=5):
    statuses, lifecycles, flags = Counter(), Counter(), Counter()
    samples, cache = {}, OrderedDict()
    total = 0
    query = "SELECT * FROM records WHERE owner={p} AND scope={p} ORDER BY id".format(p=placeholder)
    for raw in db.execute(query, (owner, scope)):
        record = dict(raw)
        source_id = record["source_id"]
        if source_id not in cache:
            source = db.execute("SELECT payload,source_type FROM sources WHERE id={p} AND owner={p} AND scope={p}"
                                .format(p=placeholder), (source_id, owner, scope)).fetchone()
            cache[source_id] = dict(source) if source else None
            if len(cache) > 128:
                cache.popitem(last=False)
        signals = classify(record, cache[source_id])
        total += 1
        statuses[record["status"]] += 1
        lifecycles[record["lifecycle"]] += 1
        flags.update(signals)
        # Stable, bounded strata. IDs/flags are private pointers, never source bodies.
        group = samples.setdefault(record["status"], [])
        group.append({"record_id": record["id"], "flags": signals})
        group.sort(key=lambda item: hashlib.sha256(item["record_id"].encode()).hexdigest())
        del group[sample_per_status:]
    report = {"method": METHOD, "records": total, "statuses": dict(sorted(statuses.items())),
              "lifecycles": dict(sorted(lifecycles.items())), "signals": dict(sorted(flags.items())),
              "limitations": ["Structural signals are not semantic truth or quality scores.",
                              "Missing validity is unknown; import time is not valid-from time.",
                              "No records, queues, budgets, or extraction results were modified."]}
    sample = {"method": METHOD, "owner": owner, "scope": scope,
              "selection": "deterministic sample per status; not a representative quality score",
              "records": [item for key in sorted(samples) for item in samples[key]]}
    return report, sample


def save_private_sample(path, sample):
    path = Path(path).expanduser().resolve()
    root = Path(__file__).resolve().parents[2]
    if path == root or root in path.parents:
        raise ValueError("Audit samples must remain outside the source repository")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Exclusive creation prevents overwriting existing reports or following links.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump(sample, file, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sqlite", help="Existing private SQLite database")
    source.add_argument("--postgres-env", metavar="ENV_NAME", help="Environment variable holding a DSN; never pass DSN as an argument")
    parser.add_argument("--owner", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--sample-per-status", type=int, default=5)
    parser.add_argument("--sample-out", help="Optional new private JSON file outside the checkout")
    args = parser.parse_args()
    if not 1 <= args.sample_per_status <= 100:
        parser.error("sample-per-status must be 1–100")
    dsn = os.environ.get(args.postgres_env) if args.postgres_env else None
    if args.postgres_env and not dsn:
        parser.error("DSN environment variable is not set")
    try:
        with readonly(args.sqlite, dsn) as (db, placeholder):
            report, sample = audit(db, placeholder, args.owner, args.scope, args.sample_per_status)
        if args.sample_out:
            save_private_sample(args.sample_out, sample)
    except Exception as exc:
        # DB/provider messages may contain connection information; do not print them.
        parser.exit(1, "Audit failed: " + type(exc).__name__ + "; no changes applied.\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
