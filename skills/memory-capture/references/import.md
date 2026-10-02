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
This is neither a 24k-token limit nor a total-request byte limit.

Allowed source_metadata keys: original_ref, original_date, author, locator,
parser_version, parent_source_key; each a string ≤1,000 chars. Permissions, owner,
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
