# Import framing (current MCP)

`memory_import` kwargs:

```json
{
  "scope": "agent:example-inbox",
  "source_key": "synthetic://session/42/boundary/1",
  "source_type": "conversation",
  "processing_policy": "archive",
  "messages": [
    {"id": "message-1", "role": "user", "text": "合成示例：本项目保留历史版本。", "created_at": "2026-01-01"},
    {"id": "message-2", "role": "assistant", "text": "合成示例：建议建立版本对比；尚未获批准。"}
  ],
  "source_metadata": {"original_ref": "synthetic://session/42", "locator": "messages-1-2"}
}
```

Roles: `user`, `assistant`, `external`; types: `conversation`, `document`,
`imported_summary`. Never fabricate a missing date; message date does not establish
the effective date of a decision. A summary stays `imported_summary` even if accurate.
Message keys: id (unique, 1–100 chars), role, nonblank text; optional source_title and
created_at (each ≤300 chars). The server rejects a batch above 100 messages or
24,000 characters of normalized serialized **messages**, including JSON escaping.
This is neither a 24k-token limit nor a total-request byte limit. Count Python
Unicode codepoints after normalizing each message to id/role/text and optional
source_title/created_at, then serializing with
`json.dumps(messages, ensure_ascii=False, sort_keys=True)` (default separator spaces).
JavaScript string.length counts UTF-16 units and compact JSON.stringify has different
separator lengths; neither is this measure. The repository adapter uses the server
serializer. source_key is 1–300 Unicode codepoints; `#` is allowed. Source dates are
preserved strings, not validated facts or inferred effective dates.

Allowed source_metadata keys: original_ref, original_date, author, locator,
parser_version, parent_source_key, visibility; each a string ≤1,000 chars.
visibility accepts unknown (default), visible_only or complete_visible. This is a
source coverage declaration, never proof that attachments were read, author identity
was verified, or memory was confirmed. Omit or use unknown if coverage is uncertain. Permissions, owner,
confirmation and model budgets are server-side, never source metadata.

The repository's deterministic `pipeline.memory_center.import_adapter.prepare_imports`
automatically packs whole messages and splits oversized individual messages. It is a
Python client helper, **not an MCP tool**. On a client without it, use an equivalent
tested adapter rather than manually guessing serialized size or truncating text.
Use the configured inbox grant; a scope string cannot create permission.

Generated split locators retain original_message_id, zero-based char_start/char_end,
original_char_count, message_index and offset_unit=unicode_codepoint. End offsets
are exclusive; concatenate consecutive chunks to reconstruct the exact original.
UTF-16 offsets from a JavaScript client must be converted before comparison. There
is no overlap: a quotation crossing a split boundary needs adjacent chunks or the
original source, not a fabricated reconstructed quote. Ordinary packed batches retain
the original message IDs and a message_start/message_end parent position.

Retry identical payloads and reuse returned source_key. Changed content, different
framing or scope yields a different part key and is a new archive version, not a
correction/supersession. Do not count multiple versions or split chunks as independent
corroboration. Unknown network outcome: retry identical archive payload once or inspect
the known receipt; avoid generating a new ID for a transport retry. Authentication or
validation failure requires resolving the cause, not changing identities or permissions.


## Durable receipt and version ledger

The import response contains **id** (source ID), **job_id** and **duplicate**;
source_id is not the import response field. Persist that receipt against the exact
framed payload, scope, source key, source version and client identity. Read job_id
with memory_import_status; archive state means archived, not extracted or verified.
Index status is separate from the import job and factual governance.

The server deduplicates owner + scope + principal + source_key + normalized content
digest (type, messages and metadata). A different digest under the same source_key
creates a new source version; it does not replace the old source or return a version
conflict. Credential changes that change principal may defeat deduplication. Reconcile
receipts before rotating client identities; do not claim global exactly-once delivery.
Use a stable explicit version/part key and persist the same payload for uncertain retries.
parent_source_key belongs inside source_metadata, not at the tool's top level.
It records linkage only: no prefix lookup, bulk withdrawal or grouped deletion is implied.

A reliable upstream outbox distinguishes prepared, sending/unknown, acknowledged and
rejected. Write the immutable framed payload before sending; acknowledge only a valid
JSON-RPC result without isError and with the required receipt. A timeout after sending
is unknown, not failed/unsent. Retry the same payload under the same principal or
reconcile an existing receipt, with bounded backoff. Never retry extract/reextract
as if archive idempotency guaranteed a free model request. Keep private payloads and
receipts outside the public repository, with restricted file access.

## Changes, withdrawal and authority

A changed source is a new version, not an automatic correction to the owner's judgments.
A local deletion/tombstone is not proof of server withdrawal. Current MCP exposes
memory_source_withdrawal_preview and memory_source_withdraw for the trusted owner
with scoped read + write only. An ordinary inbox writer cannot call them even if
its tools/list advertises both tools. Keep an upstream withdrawal request pending
until the owner performs it and the source-specific receipt is reconciled. Do not
switch credentials, impersonate trusted_user or mark the remote source withdrawn
based on local intent. Current withdrawal retains archive/history; it is not physical
byte erasure. Each imported part has its own source ID; parent linkage does not make
a one-call withdrawal. Unsettled bulk jobs can block withdrawal and require resolution.

## Submit existing suggestions without server extraction

This optional development capability must be advertised and migration-ready;
older deployments still support ordinary archive capture. `memory_capabilities`
reports `candidate_intake.available` and `.authorized`; tools/list alone cannot.
An upstream node needs read/source_read/write/**candidate_write**, exactly one
`agent:…-inbox` scope, and its own source from a successful archive receipt.
The existing archive-only restriction still prevents spending model tokens.

Call `memory_candidate_submit` with that scope, `source_id` (the import receipt's
`id`), a stable `request_key`, and 1–20 `claims`. Each claim contains
message_id, quote, start, end, statement, subject, topic and kind; optional
client_candidate_id links the returned record back to local preparation.
Statement is at most 1,200 characters; quote at most 2,000. Topics are profile,
preferences, people, areas, projects, topics. Kinds are identity, preference,
relationship, decision, plan, event, claim, suggestion.

Offsets count Unicode code points in the exact archived message and end is
exclusive. Check `Array.from(text).slice(start,end).join('') === quote` in a
JavaScript client. After source segmentation, use the returned part's message ID
and **part-local** offsets, retaining parent locators separately; crossing two
parts is not a single quote accepted by this interface. Preserve source roles;
do not submit holder, verified status, effective dates or role overrides.

The response has id (candidate receipt ID), source_id, record_ids, count,
duplicate, candidate_only=true, facts_confirmed=false and model_calls=0. Store
it separately from the source/job receipt. Same principal/scope/request_key with
identical content replays the receipt; changed content conflicts. Unknown
outcomes use the same payload/key, with bounded retries. Withdrawal or revoked
access rejects replay. The full batch commits or fails together.

The server validates quote location and produces reviewable candidates with
unknown identities and dates. It does not semantically approve suggestions,
promote them to personal, or perform another LLM extraction. A node may derive
suggestions locally if separately authorized; center receipt model_calls=0 does
not measure the node's own model usage. The owner reviews in the workbench.
