# Permission and internal read cost review — 2026-10-03

All fixtures are synthetic. No real credentials, personal data, model calls, production writes or credential registration were used. This is a targeted protocol review, not a complete penetration test.

## Permission boundary

New `tests/test_memory_permission_matrix.py` adds two tests using the real ASGI MCP and Flask REST routes with a dynamic grant loader:

- Read-only agent can read context but cannot import, re-extract, correct, confirm governance, expand source without `source_read`, or read outside its scope. Model call count remains unchanged.
- Scope reduction takes effect on the next MCP and REST request; removing the grant makes both return HTTP 401. MCP authorization errors inside tool calls use `isError`, even when the HTTP transport returns 200.

These two tests pass. Existing five archive-only tests also pass: default archive, denial before source dedup, inability to schedule translation/re-extraction/retry/budget/bulk resume, and shared MCP/REST constraints. Existing three grant lifecycle tests cover expiry/disable/malformed validity and pass. Ten targeted tests pass in total.

Important compatibility boundary: newly created grants require `archive_only=true`; historical grants without that field still retain the old default extraction behavior. This is intentional compatibility, not universal proof that all installed credentials are cost-restricted. Changing a historical grant requires explicit owner configuration; no such change was made here. Revocation applies to future requests, not evidence already loaded into another Agent.

## Reproducible cost baseline

Run each size in its own process:

```sh
.venv/bin/python scripts/benchmark_memory_read_cost.py --size 10000
.venv/bin/python scripts/benchmark_memory_read_cost.py --size 100000
```

The script creates a temporary SQLite Store: one small synthetic source, 1% verified records, remaining candidates, all matching the lexical query `Atlas`. No source index is rebuilt: original evidence is unavailable in this particular read-cost fixture. This measures scope record overhead; it does not assess source search quality or PostgreSQL production load.

Each method runs three times. The first includes `tracemalloc`, so latency summaries use the remaining two untraced observations. With two samples, the reported descriptive p95 is the observed maximum, not a statistically defensible p95. SQL tracing counts SELECT statements, not rows or network bytes. Memory is Python allocation peak plus whole-process peak RSS. Response hashes prove within-run consistency only: temporary source IDs vary between runs. They are not cross-version accuracy proof.

Static bottlenecks confirmed at baseline:

1. `Store.snapshot` materializes full scoped record rows, joined source payloads, governance and translations before applying output limit and filtering.
2. `context` requests a million-row snapshot then selects trusted context, despite a small output budget.
3. `bundle` does a second candidate snapshot after context, duplicating scope work.
4. `reading.search_page` keeps serializing candidate envelopes after the budget fills. A naive early break could alter the existing behavior of skipping a large item and accepting a later smaller item; contract tests must decide this behavior before optimizing.

Further optimization should bound query-stage candidates, defer source payload access, reuse loaded state, and retain scope/governance/time/revision correctness. Short output alone does not establish cheap retrieval. The owner’s current record count or production responsiveness is not inferred from this synthetic baseline.

## Baseline receipts

Measured before retrieval optimization, working base HEAD `32ec92c852c66c8fa10f25dd7ff768fcb2e06be7`. Imported core/governance/bundle had SHA-256 `07420318…`, `e94befdd…`, `e5e4d351…` respectively. Active parallel edits after import do not change an already running Python process. See synthetic JSON receipts in `docs/benchmarks/`.

| Records | Method | Untraced p50 | Observed max (weak p95) | Python peak allocation | SELECTs | Output chars |
|---:|---|---:|---:|---:|---:|---:|
| 10,000 | context | 0.183 s | 0.185 s | 22.6 MB | 4 | 1,167 |
| 10,000 | bundle | 1.534 s | 1.537 s | 22.6 MB | 10 | 5,620 |
| 100,000 | context | 1.911 s | 1.941 s | 225.3 MB | 4 | 1,168 |
| 100,000 | bundle | 15.513 s | 15.528 s | 225.3 MB | 10 | 5,622 |

Whole-process peak RSS was 78.7 MB at 10,000 and 511.2 MB at 100,000. The first traced bundle observation at 100,000 took 149.6 seconds and is explicitly excluded from latency summaries. Subsequent untraced observations were 15.50/15.53 seconds; tracing substantially changes latency.

The fixture reproduces the concern: response size stays nearly constant while work and allocation grow roughly with record count. It does **not** prove current production is slow. Future optimization results need the same fixture parameters and integrity assertions; JSON response hashes are only within-run consistency receipts.
