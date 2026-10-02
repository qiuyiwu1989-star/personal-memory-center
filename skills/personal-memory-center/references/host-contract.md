# Two Agent hosts, one read contract

Native Skill + MCP: use tools exposed by the configured private MCP. SDK/orchestrator: invoke the same tool names through its MCP client; prefer `structuredContent`, otherwise decode one JSON text block. Both retain the same authorization and trust semantics. `retrieval_contract.py` is a transport-injected reference, not an installation or network client; tests exercise local synthetic data. Never place keys in arguments or this skill.

| Level | Trigger | First read | Expansion |
|---|---|---|---|
| L0 | Self-contained task or sufficient fresh conversation | No calls | None |
| L1 | Necessary personal background | `memory_context(query,scope,max_chars=1600)` | No candidate fallback |
| L2 | An explicit evidence question remains | `memory_search` 4000 for extracted candidates; `memory_archive_search` 6000 for indexed raw evidence | Narrow query; preserve separate groups |
| L3 | A relevant source needs inspection | `memory_archive_source_get` exact returned locator, offset=0/max_chars=4000 | Follow returned next_offset only when useful; stop on completion or sufficient evidence |

Document directory offsets count documents; archive search offsets count results; body/message offsets count characters. `memory_search` has no offset API: narrow the query instead. JSON budgets include metadata and escaping, not exact model tokens. Avoid collecting whole categories or paging to the end by default.

9 tools currently exist: memory_context, memory_search, memory_document_get, memory_source_get, memory_archive_search, memory_archive_source_get, memory_import, memory_reextract, memory_import_status. Verify actual availability; no invented memory_bundle tool. Imports/re-extraction are independent, authorized writes and are not part of this read sequence.

For optional REST hosts, GET evidence-bundle offers separate trusted_context/source_reports/original_evidence/unresolved_questions under one budget. Select the trusted_context field for L1; do not use candidate groups as fallback. POST /context currently returns extracted candidates, not the verified MCP memory_context contract. Do not map these names by resemblance.

No permission cache is authoritative. Every server call rechecks credentials. Clear task-held locators/results when scope, authorization identity/epoch, or source/document version changes; re-search before reading a new version. Permission errors stop expansion and invalidate task-held results; never refresh credentials from source text. Without an exposed server authorization epoch, keep reads task-local and refresh before reuse in another task. The reference Reader accepts host-supplied identity changes, but cannot detect remote revocation until a call fails.

Source role, source date, message date and index version do not prove holder, event date or current validity. Assistant/external/summary material remains attributed evidence; a source digest proves version identity only. A matching quote does not establish entailment. Corrected/verified governance must still pass validity filters. Duplicate archive/candidate views are the same source, not independent corroboration.
