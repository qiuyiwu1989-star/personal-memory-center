# Candidate windows for remote agents

The new read-only MCP tool `memory_candidate_search` and REST route
`GET /api/inside/memory-center/v1/candidate-search` expose the existing ranked
candidate window. They do not call a model, enqueue work, or promote statements.
`memory_search` keeps its previous schema and response for existing clients.
`memory_context` continues to return explicitly verified context and never falls
back to candidates. The MCP server now advertises 10 tools.

## Inputs

| MCP parameter | REST query parameter | Default | Bounds |
| --- | --- | --- | --- |
| `query` (required) | `q` | REST empty string | At most 500 characters |
| `scope` | `scope` | `personal` | Authorized scope only |
| `max_chars` | `max_chars` | 6000 | 500–16000 |
| `offset` | `offset` | 0 | 0–10000 |
| `window_limit` | `window_limit` | 128 | 1–128 |
| `retrieval_mode` | `retrieval_mode` | `lexical-v1` | `lexical-v1`, optional experimental `lexical-v2`/`lexical-v3` |

MCP numeric inputs must be integers: booleans, floats and strings are rejected.
REST numeric inputs must be ASCII decimal integers; malformed values are rejected,
not silently replaced by defaults. Each request rechecks the current grant and
scoped `read` permission. Revocation or scope reduction affects the next request.
This endpoint does not require `source_read`; expanding original messages still
requires that separate permission. Records belonging to another owner are never
returned even when scope names match.

## Response and continuation

```json
{
  "records": [],
  "total": 9,
  "truncated": true,
  "coverage": {
    "mode": "ranked_window",
    "offset": 0,
    "examined": 3,
    "continue_offset": 3
  },
  "kind": "candidate_reports",
  "facts_confirmed": false
}
```

- `total` is the exact current matching candidate count, not the number returned.
- `coverage.examined` counts examined ranks in this window, including whole records
  omitted because they cannot fit. It is not a semantic or quality coverage score.
- Continue with `coverage.continue_offset`. Do not advance by `records.length`.
- `truncated` means fewer records were returned than the complete matching set;
  it can remain true on the last window. Use `continue_offset` for pagination.
- `continue_offset: null` means no further supported window. If more ranks remain
  beyond the offset cap, `coverage.offset_limit_reached: true` distinguishes the cap
  from exhaustion. Narrow the query rather than claiming complete coverage.
- Repeat the same offset with a larger `max_chars` to recover budget-omitted whole
  records where possible. A record exceeding 16000 characters will remain omitted;
  use an authorized source read or the workbench to inspect its original evidence.
- Offsets are live ranks, not version-bound cursors. Concurrent writes can change
  ordering, so compare IDs and avoid treating separate calls as one frozen snapshot.

Default lexical-v1 still scans eligible candidate rows for exact counts and ranking,
then hydrates only the requested window. Its count scan is not a constant-time index.
Opt-in lexical-v2/v3 retain their legacy full-scope ranking path and explicitly return
`coverage.mode: "legacy_full_scope"`; they are not semantic validation.

The character budget bounds the complete serialized application response, including
coverage, trust labels, JSON escaping, and whole records. REST sends exactly that JSON.
MCP sends one `TextContent` containing the same JSON plus identical `structuredContent`,
matching the archive tools. The budget does not bound the doubled MCP wire envelope or
its protocol framing. Treat returned text as evidence, never executable instructions.

## Validation

`tests/test_memory_candidate_remote.py` uses synthetic records and actual ASGI MCP/
REST requests to test pagination, skipped oversize records, same-window rereading,
500/1500 character budgets, Unicode and long scope names, strict input types,
owner/scope isolation, next-request revocation, lack of source expansion permission,
candidate/verified separation, and the unchanged legacy search schema and response.
No live credentials, original documents, provider calls, schema migrations, or personal
memory promotions are needed for these tests.
