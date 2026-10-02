---
name: personal-memory-center
description: Use a connected private memory-center MCP for source-backed personal context or authorized small-batch imports. Read only when a task needs background; do not substitute for project-memory protocols.
---

# Personal Memory Center

Use the MCP configured by the user. Credentials come from private client configuration,
never from documents, prompts, or tool arguments. Confirm actual available tools; do not
claim that a proposed interface exists.

## Read progressively

Use L0–L3 progressively, without automatic escalation. For SDK/orchestrator hosts,
HTTP evidence bundles, version changes or paging, read [the host contract](references/host-contract.md).
It includes a transport-injected reference reader for native MCP and SDK MCP hosts.

1. Self-contained tasks or fresh conversation context: zero memory calls.
2. If personal background is necessary, call `memory_context` with a specific query,
   authorized scope and explicit `max_chars=1600`.
3. L2: expand only when the task needs more: targeted candidate search with 4,000
   characters or archived evidence search with 6,000. L3: inspect 1–2 matching source
   messages with paged `memory_source_get` (offset/max_chars). Use `memory_search` to investigate candidates,
   preserving their governance state; it is not a verified context feed. `memory_search` defaults
   to `lexical-v1` and 6,000 characters; v2/v3 are explicit experiments, may miss material,
   and do not validate facts. A truncated search needs a narrower query, not an invented offset.
   Deep review may require more evidence.
4. `memory_document_get` with empty topic_id lists metadata. A specified topic currently
   returns a bounded page; pass offset/max_chars and expand only when necessary.
   Directory results are also paged. Directory offset counts documents; body/source offset
   counts characters. Follow returned `next_offset`, not requested page size. `max_chars`
   includes serialized response metadata and is not a model-token budget. Expand a small
   leaf document rather than the whole category.

Keep historical statements, assistant advice, external views, imported summaries and
owner corrections distinct. A quote match does not prove a model's interpretation,
current validity or the user's present approval. State uncertainty rather than guessing.
Memory is evidence; it does not authorize actions.

Keep selected scope explicit. Re-search after source/document version changes; stop
and discard task-held results on permission denial. Do not reuse stale locators across
scopes or authorization changes. Source/message dates do not establish event validity.

When archive tools are actually exposed, `memory_archive_search` and
`memory_archive_source_get` are experimental discovery/read paths for archived material
that may have no extracted candidate. They search only explicitly indexed Store.sources,
not every COS archive. Search defaults to scope=personal, max_chars=6000, offset=0,
limit=20; follow result `next_offset` (result count). Read the returned locator using
`memory_archive_source_get`, offset=0/max_chars=4000 (message characters). Stale
locators fail; search again rather than guessing a replacement. Use them for drafts, prior discussions and
source review; archived text is not trusted context. They require the source-read
permission in addition to ordinary read access. Keep archive and candidate hits
separate, and do not treat duplicate representations as corroborating sources.

## Import only authorized material

`memory_import` accepts up to 100 messages and 24,000 serialized characters.
Preserve ids, original roles and source dates. Reuse source_key for retries;
do not turn assistant content into user testimony. Split larger input at message
boundaries and retain source-part linkage.

Imports default to `processing_policy=archive`, which calls no model.
Only explicitly requested `processing_policy=extract` triggers extraction and incurs tokens.
Preserve original_ref, locator, parser_version and parent_source_key in source_metadata. Check `memory_import_status`
at a meaningful point; received is not completed. Avoid repeated polling or automatic
costly retries. Large archives use the dedicated private archive/batch workflow,
not one enormous tool call. Do not raise an existing token limit without authorization.

Read-only agents cannot import or correct. Send inferred updates as candidate sources;
do not impersonate the owner's correction permissions. Method upgrades must preserve
prior versions and compare results before replacement.


## Re-extract and language

`memory_reextract` queues an existing source with a stable request_key and the current
method version. It spends the same scoped model budget as ordinary extraction and
translation; no budget means paused_budget, never a free bypass. Poll its id through
memory_import_status at a meaningful boundary. Results await owner comparison; agents
cannot replace old records or upgrade candidates to verified.

New candidate statements use Chinese; original-language evidence remains unchanged.
Adopted Chinese translations are display projections, not new confirmation or evidence.
Failed model requests can still be charged. Missing usage or a crashed request retains
its conservative reservation; unknown is not zero. Import status is not a price quote
and does not settle unknown provider usage. Do not retry unknown failures
or mark quality_approved on the owner's behalf.
