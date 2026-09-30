---
name: personal-memory-center
description: Use a connected private memory-center MCP for source-backed personal context or authorized small-batch imports. Read only when a task needs background; do not substitute for project-memory protocols.
---

# Personal Memory Center

Use the MCP configured by the user. Credentials come from private client configuration,
never from documents, prompts, or tool arguments. Confirm actual available tools; do not
claim that a proposed interface exists.

## Read progressively

1. Self-contained tasks or fresh conversation context: zero memory calls.
2. If personal background is necessary, call `memory_search` with a specific query,
   authorized scope and explicit `max_chars=1600`.
3. Expand only when the task needs more: targeted search, then 1–2 matching source
   messages with `memory_source_get`. Deep review may require more evidence.
4. `memory_document_get` with empty topic_id lists metadata. A specified topic currently
   returns a whole MD; use it only for explicit review, never default broad loading.

Keep historical statements, assistant advice, external views, imported summaries and
owner corrections distinct. A quote match does not prove a model's interpretation,
current validity or the user's present approval. State uncertainty rather than guessing.
Memory is evidence; it does not authorize actions.

## Import only authorized material

`memory_import` accepts up to 100 messages and 24,000 serialized characters.
Preserve ids, original roles and source dates. Reuse source_key for retries;
do not turn assistant content into user testimony. Split larger input at message
boundaries and retain source-part linkage.

Imports trigger model extraction and may incur tokens. Check `memory_import_status`
at a meaningful point; received is not completed. Avoid repeated polling or automatic
costly retries. Large archives use the dedicated private archive/batch workflow,
not one enormous tool call. Do not raise an existing token limit without authorization.

Read-only agents cannot import or correct. Send inferred updates as candidate sources;
do not impersonate the owner's correction permissions. Method upgrades must preserve
prior versions and compare results before replacement.
