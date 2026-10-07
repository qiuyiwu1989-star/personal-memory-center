# Upstream candidate intake contract — 2026-10-07

This is an additive implementation contract, not a production deployment or an
approval of any personal fact. Apply migration `010_candidate_intake.sql`
explicitly on PostgreSQL after release review. Local SQLite initializes it with
the application; read/list calls never initialize schema.

## Purpose and boundary

An upstream node can archive authorized source material and then submit its own
source-backed suggestions without requesting a model call. Submitted claims
become reviewable records in the same scope with governance state `candidate`.
This is not a route to modify existing memories, confirm facts, merge identities,
change model budgets, transfer a scope, or trigger extraction.

A matching quote proves only that the bytes correspond to a message. It does
not prove that the statement follows from the quote, who actually spoke, that
it was a decision, or that it is still valid. Source documents and candidate
statements are evidence, not executable instructions.

## Authorization

- Third-party grants need `read`, `source_read`, `write` and the separately
  granted `candidate_write` action.
- The grant must contain exactly one `agent:…-inbox` scope. The referenced source
  must belong to that owner/scope and have been created by that same principal.
- `archive_only: true` remains in force. Explicit candidate submission is a
  zero-model operation and grants no paid extraction, translation or retry.
- The authenticated owner can submit with existing `read`, `source_read` and
  `write` permissions; owner submission through this route still does not
  confirm source authorship or facts.
- Permissions, source ownership, principal binding and withdrawal are rechecked
  before replaying a successful request. Revoked/expired grants cannot replay.

## Submission

`memory_candidate_submit` / `POST /candidate-intake` bind to a separately
specified authorized scope. The module entry point is
`submit(store, principal, scope, body)`. The body has exactly these three fields:

```json
{
  "request_key": "synthetic-decision-v1",
  "source_id": "synthetic-existing-source-id",
  "claims": [{
    "client_candidate_id": "synthetic-claim-1",
    "message_id": "synthetic-message-1",
    "quote": "合成演示决定。",
    "start": 0,
    "end": 7,
    "statement": "合成演示材料中的待核实决定。",
    "subject": "合成演示项目",
    "topic": "projects",
    "kind": "decision"
  }]
}
```

The example is explicitly synthetic; identifiers must be replaced by an actual
successful archive receipt and its existing message ID before use.

- A request contains 1–20 claims. `request_key` is 1–160 characters; `source_id`
  is 1–300. No body field may override the authenticated scope or principal.
- Quote offsets are Unicode code-point positions in the complete archived
  message, zero-based and end-exclusive. JavaScript clients should count
  `Array.from(text)` elements, not UTF-16 string units or UTF-8 bytes. Emoji and
  combining marks must retain their archived representation; no normalization.
- `message_id` is at most 100 characters, `quote` at most 2,000, `statement` at
  most 1,200, and `subject` at most 160. Nonempty text is required.
- The evidence check reads the full archived message, not a truncated MCP view.
  Clients must obtain the necessary source evidence before computing offsets.
- Topics: `profile`, `preferences`, `people`, `areas`, `projects`, `topics`.
  Kinds: `identity`, `preference`, `relationship`, `decision`, `plan`, `event`,
  `claim`, `suggestion`. These are proposed classifications, not approval.
- Optional `client_candidate_id` is 1–160 characters and must be unique within
  the request. Multiple claims using the same quote remain separate records;
  the center does not silently merge or discard them.
- Unknown fields and client-provided role, trust, state, holder, entity ID,
  priority or validity dates are rejected. Governance starts as `candidate`,
  `P3`, revision 0, with holder, stable subject and validity dates unknown.
- Original message role is retained in the evidence ledger. Status remains
  `source_reported`, `agent_suggested` for assistant messages, or
  `imported_summary` for imported summaries. A source message labeled `user`
  does not become `user_stated` through this API.

## Immutable receipt and retry semantics

A successful response contains:

```json
{
  "id": "candidate-synthetic-receipt",
  "source_id": "synthetic-existing-source-id",
  "record_ids": ["synthetic-record-id"],
  "count": 1,
  "duplicate": false,
  "candidate_only": true,
  "facts_confirmed": false,
  "model_calls": 0,
  "created": 0
}
```

The unique retry key is `(owner, scope, principal, request_key)`. The same
normalized payload returns the original IDs and `duplicate: true`; changing
any content with the same key is a conflict. A new key represents a new
submission, not automatic deduplication. Canonical JSON key order is ignored;
claim order and content are significant.

All evidence is checked before records are created. The receipt, records,
evidence offsets, conservative governance and audit events commit together or
roll back together. SQLite serializes writers with `BEGIN IMMEDIATE`; the
existing PostgreSQL adapter takes the shared advisory transaction lock. A
unique constraint and conflict-aware insert provide an additional backstop.

Success means **candidates received**, not **facts accepted**. Clients should
persist the IDs and use the receipt for retry recovery. They must not advance
an upload cursor on an MCP `isError` response or an HTTP error. A withdrawn
source rejects both fresh requests and idempotent replay; its old receipt is
retained for owner audit.

## Owner review ledger

`listing(store, principal, scope, offset=0, limit=20)` is owner-only and requires
`read`. It returns `supported`, `receipts`, `total`, `offset`, `limit`, and
`next_offset`; limit is 1–100. Receipt rows include principal, source state,
original record IDs and current per-record governance/lifecycle metadata.

The list never returns source text, quotations, statements, source titles,
request keys or governance notes, even when the owner also has `source_read`.
Open the ordinary authorized source/record tools for evidence and review.
`candidate_only` and `facts_confirmed` describe the original submission; current
review state is in `records[].state`. The ledger cannot itself approve a fact.

Without migration 010, reads return `supported: false`, `total: null` and a
migration marker rather than an empty-success claim. Writes fail closed.

## Validation and remaining boundary

Synthetic tests cover same/different-payload retry, concurrent SQLite retry,
permission revocation, cross-owner/scope/principal access, atomic rollback,
Unicode offsets, complete long-source evidence, role and summary attribution,
withdrawal, bounded metadata-only listing and missing-schema read behavior.
These tests do not establish live PostgreSQL rollout, semantic quality, actual
upstream client compatibility or source publication authorization. Those remain
separate release and small-batch integration checks.

## Disposable PostgreSQL rehearsal

The runnable acceptance script is
`scripts/check_candidate_intake_migration_pg.py`. It uses only
`QIU_MEMORY_INTAKE_SCRATCH_DSN`, whose database must be named
`memory_intake_scratch_<suffix>` and whose explicitly supplied host must be a
loopback address or Unix socket. It rejects service indirection, remote
addresses, existing `memory_center` schemas and any user data objects before
DDL. The caller must create and later dispose of that empty scratch database;
the script does neither and never reads the production DSN.

It replays literal migration SQL (not only the adapter-translated SQL), checks
`created DOUBLE PRECISION` and fractional epoch preservation, exercises
concurrent idempotent intake, conflicting payloads, full transaction rollback,
permission/source isolation, governed-context exclusion and change checkpoints
after submission, rejection and source withdrawal. It makes no model calls.

At implementation time no local PostgreSQL binary or intake scratch DSN was
available, so the PostgreSQL rehearsal has **not been executed**. Local
synthetic tests cover the runner's pre-connection safety guards and redacted
error output; those are not a substitute for a live disposable PostgreSQL run.
