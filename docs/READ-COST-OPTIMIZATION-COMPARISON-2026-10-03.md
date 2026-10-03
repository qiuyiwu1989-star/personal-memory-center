# Read cost optimization comparison — 2026-10-03

Same synthetic fixture parameters and measurement approach as [baseline](PERMISSION-READ-COST-REVIEW-2026-10-03.md). No LLM, real data, production reads or writes. Baseline receipts are preserved, and optimized receipts use separate `synthetic-read-after-*` filenames under `docs/benchmarks/`.

The instrumented script now additionally records trusted returned count, candidate total/returned count, and raw evidence total/returned count. This is additive measurement only; fixture parameters and timing procedure are unchanged. Three calls per method include one allocation-traced call and two untraced latency calls. The maximum of two untraced observations is not a reliable population p95.

## Cost comparison

| Size | Method | Baseline p50 | Optimized p50 | Baseline Python allocation peak | Optimized peak |
|---:|---|---:|---:|---:|---:|
| 10,000 | context | 0.183 s | 0.006834 s | 22.6 MB | 0.442 MB |
| 10,000 | bundle | 1.534 s | 0.248508 s | 22.6 MB | 21.78 MB |
| 100,000 | context | 1.911 s | 0.079461 s | 225.3 MB | 4.04 MB |
| 100,000 | bundle | 15.513 s | 2.695920 s | 225.3 MB | 217.36 MB |

SELECT count decreased from 4 to 2 for context and from 10 to 6 for bundle. Whole-process peak RSS: optimized 73.9 MB / 373.7 MB at 10,000 / 100,000, compared with baseline 78.7 MB / 511.2 MB. These peaks include fixture setup and allocation tracing, not solely the two untraced requests.

Optimized source hashes are recorded in JSON receipts: core `31d25514…`, governance `440686b7…`, evidence_bundle `bc257d6a…`, reading `0fe6597f…`. Parallel edits after module import did not alter these running benchmark processes.

## Integrity and policy boundary

The optimization is coupled to an intentional trusted-admission policy revision. Bare historical `owner_corrected` records are no longer automatically usable without the complete governance contract. This fixture has only explicit `verified` records with holder, subject, and date; therefore its trusted eligible total remains 100 / 1,000 in both versions. This does not assert legacy correction results are unchanged.

Optimized observations show:

- Context returns two trusted records under its 1,600-character budget; eligible totals are 100 / 1,000.
- Bundle returns ten trusted records under 6,000 characters; eligible candidate totals are 9,900 / 99,000, with zero candidate records retained because trusted content consumes this budget.
- Raw evidence totals/returned counts are zero. The fixture intentionally does not build a source index, so this experiment cannot establish whether the new policy improves preservation of available original evidence.
- Baseline receipts did not capture group returned counts. They preserve trusted total, serialized size, and within-run response hashes. Full bundle content equivalence is therefore not claimed. Source IDs also vary across runs, so hashes cannot prove cross-version equivalence.

The changed trimming policy preserves raw evidence before candidate reports; separate behavior tests must verify its intended content changes. Likewise, bounded output cannot by itself prove selection accuracy. Parent integration tests cover scope isolation, governance, expiry, revision changes and budget selection behavior separately.

## Remaining bottleneck

Trusted context allocation is now proportional to the verified subset in this fixture, with shared source payload decoded once per selected source. Candidate bundle work still materializes nearly the entire candidate scope: at 100,000 records the allocation peak remains 217 MB and untraced median is 2.70 seconds. This is a measured improvement, **not** a fully bounded internal retrieval design.

Further work should define bounded query-stage candidate retrieval with explicit coverage/truncation semantics; retain skip-oversized-item behavior where required; test larger unique source payloads, real source indexes, selective queries, experimental lexical modes, and PostgreSQL separately. Do not turn these SQLite synthetic results into production latency guarantees.
