# Candidate rank window — 2026-10-03

This document records the round-two internal implementation. Round three exposes `memory_candidate_search` over MCP and `/candidate-search` over REST; see [the current remote contract](CANDIDATE-REMOTE-READING.md). The continuation limitations below describe the earlier round-two interface.

The default `lexical-v1` evidence bundle now avoids decoding every candidate's source document to return a small report. `Store.candidate_reports` counts and ranks all active candidate records in the authorized owner/scope, retains a bounded heap of IDs, then calls the existing source/governance hydration path only for the requested ranking window. No schema, model calls, original data, permission policy, or trusted-context fingerprint contract changes.

## Selection and compatibility

- Matching and scoring use the existing legacy lexical-v1 arithmetic over statement, translated statement, subject and topic. This is relevance selection, not semantic verification.
- The default window is 128 matched ranks. `offset` may be 0–10,000; `window_limit` may be 1–128. The heap retains at most `offset + window_limit` small ID/score entries. Source hydration visits at most 128 selected records; repeated source IDs are decoded once.
- Counts include all matches at the lightweight scan, not merely the window. `total` and `truncated` explicitly distinguish the matching population from returned items.
- Snapshot and candidate scanning now break equal `created` ties by `id ASC`. Previously SQL did not specify a tie order. Different timestamps and score ordering remain unchanged. Trusted context already uses its own priority/ID order, so this tie refinement does not change its revision policy.
- An oversized candidate can be skipped within the window, as before. Character-budget trimming retains whole items. It does not increase or rewrite examined-rank coverage.
- Experimental lexical-v2/v3 depend on titles inside source payloads. Their existing full-scope hydration/ranking remains intact, followed by an explicit report window. Their coverage mode is `legacy_full_scope`; this round does not claim reduced internal cost for these modes.

## Coverage envelope

A report adds a small `coverage` object:

```json
{
  "mode": "ranked_window",
  "offset": 0,
  "examined": 128,
  "continue_offset": 128
}
```

`examined` counts ranks considered, including oversized items and items later removed from the final bundle. It is not the displayed count. `continue_offset` points after this examined window, rather than after the last displayed item. A null continuation means either all scanned matches were examined or the offset ceiling prevents another supported window; in the latter case `offset_limit_reached: true` is explicit. Callers can repeat the same window with a different supported budget if they need to inspect budget omissions.

This is currently an internal Python continuation facility and **diagnostic coverage in REST evidence-bundle responses**. The REST bundle does not accept an offset; the current nine-tool MCP has no evidence-bundle tool. An agent cannot yet use this field as a functioning remote continuation cursor. The normal snapshot API remains available with its previous result-limit contract. Adding a public candidate-only continuation tool, or a true opaque pagination cursor, is a separate follow-up.

## Cost limits that remain

The lexical-v1 query still scans the authorized candidate population and transfers lightweight record/translation fields: time and database work remain O(N). SQLite iteration does not build a list of all candidate rows in Python. PostgreSQL's current ordinary psycopg cursor may buffer its full result internally; this implementation does not provide a server-side streaming cursor or guarantee bounded PostgreSQL driver memory.

Selected source count is bounded, **source bytes are not**. A selected document may have a large multi-message payload. Source title/index changes, concurrent source/record updates, and query scans are not a new atomic transaction or cache guarantee. The original-evidence discovery/index path also remains unchanged and can scan the full authorized source index. Therefore neither the whole bundle nor every retrieval mode has fully bounded internal memory or database work.

The 128-rank window can miss a smaller candidate beyond that window when all earlier candidates are too large. This is explicit truncation and limited coverage, not an empty-result claim. Public continuation is still needed before an agent can traverse all ranked windows through MCP. Candidate reports also remain subordinate to original provenance under the bundle's existing final trimming policy.

## Synthetic verification

`tests/test_memory_candidate_window.py` covers:

1. A 5,000-record, unique-source population: 1,000 exact query matches; requesting ranks 5–11 decodes exactly 7 source payloads and preserves their source dates.
2. Legacy/page compatibility for small populations across lexical-v1/v2/v3, blank/selective/no-match queries and translated statements.
3. Oversized candidates and final bundle budgets 1,500–16,000: examined coverage remains unchanged after omissions.
4. A deterministic equal-created tie order.
5. A 10,150-record population at offset 10,000: exact total and explicit offset ceiling, with no invalid advertised continuation.
6. Read permission, owner isolation and input bounds.

All fixtures are synthetic. These tests establish selection and hydration behavior, not production latency, model quality, or semantic correctness. The parent integration run separately verifies PostgreSQL compatibility and the full permission/governance regressions before publication.
