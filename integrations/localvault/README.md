# LocalVault compatibility repair package

## New center interfaces (deployed on qiuyiwu.com, 2026-10-07)

The center now implements optional source-bound candidate submission, scoped
capabilities and metadata checkpoints. See [the candidate contract](../../docs/UPSTREAM-CANDIDATE-INTAKE.md)
and [rollout order](../../docs/INTERFACE-EXPANSION-2026-10-07.md). The stable production
overlay passed separate PostgreSQL rehearsal/migration and public MCP acceptance;
see [the release record](../../docs/INTERFACE-PRODUCTION-2026-10-07.md). This does not
prove that a LocalVault installation has implemented the new client protocol.

After the existing archive receipt, a separately authorized single-inbox writer
can submit up to 20 candidate claims with exact message IDs and Unicode quote
offsets, without another center LLM call. Keep source and candidate receipts
separate; ordinary archive grants gain no new permission. Suggestions remain
candidates, regardless of local model confidence or source role.

For reading, discover actual capabilities before adopting `memory_changes`.
It detects current record metadata changes for refreshing task context; it is
not a source/COS sync feed or a complete event delta. Do not use it to acknowledge
pending archive uploads. The compatibility patches below only fix archive transport;
they do not implement these new node features.

## 2026-10-07 current upstream follow-up

The upstream main revision inspected this round is
`de1e25be5026e03e01ff078b14a3639c185f2ad5`. Use
[the refreshed patch](compatibility-de1e25b.patch) for that revision; do not
apply the old patch on top. Public source blobs were verified against their Git
object hashes. Only an isolated source copy was modified, not a user installation
or the upstream repository.

Upstream now handles HTTP200 tool errors, parses JSON text, and rejects unknown
top-level payload fields. Its current fake-endpoint suite passes **96** assertions.
Real loopback verification still fails at `patched_source_job_receipt_persisted`:
the parser recognizes `source_id` but the center returns `id`. The refresh adds
strict source/job acknowledgements, the actual parent metadata field and job-only
status arguments. It also accounts for Python JSON separator spaces; UTF-8 bytes
alone do not cover the ASCII boundary. The existing UTF-8 limit stays as an extra
conservative local cap, and control-character splitting gets more headroom.

The refreshed isolated copy passes **15 real HTTP checks** (including the new
ASCII separator boundary), with **13 synthetic archived sources**, **zero model
calls**, and retains **96/96** upstream assertions. These counts are distinct
from the previous 14/84 reports below. A missing entry file during initial
snapshot setup was corrected before running the upstream suite; it was not an
upstream product failure.

Next handoff: apply the refreshed patch to the matching revision, implement the
source egress policy from the revised node plan, and run 3–5 authorized real
sources with the actual installation. No real-source quality, live credential,
egress gate or automatic production sync is certified by the synthetic checks.

```sh
# In a clean checkout of de1e25be5026e03e01ff078b14a3639c185f2ad5:
git apply --check /path/to/personal-memory-center/integrations/localvault/compatibility-de1e25b.patch
git apply /path/to/personal-memory-center/integrations/localvault/compatibility-de1e25b.patch
# From the memory-center repository:
.venv/bin/python scripts/check_localvault_compatibility.py /path/to/localvault-checkout --patched
node /path/to/localvault-checkout/mcp-server/test/upstream.js
```

## Previous pinned revision and historical results

Reviewable adapter patch for LocalVault source revision `73be4988553be167ea7073458b1f2bc70ab5a3af` (2026-10-05).
No user installation, credentials, personal documents or remote LocalVault
repository was changed.

## Observed compatibility

The original upstream fake-endpoint suite passed 84 assertions. Our real HTTP
check used actual upstream `MemoryCenterClient` and `newBridge` against a
loopback memory-center service, temporary SQLite vault/ledger and synthetic
sources/grants. No worker or model was used.

The default runner reproduces 22 observations, including defects; this is **not**
a claim of 22 successful compatibility checks:

- MCP text content carries `{id,job_id,duplicate}`. The bridge does not parse
  content text and only recognizes `source_id`, so loses both receipt identifiers.
- HTTP 200 tool `isError:true` is treated as success; the bridge marks a denied
  request receipted and advances its cursor despite no archive.
- Top-level `parent_source_key` is ignored; the actual tool schema requires it
  inside `source_metadata`.
- The status helper's `sourceId` cannot satisfy the tool's required `job_id`.
- 100 messages with compact JSON length 23,491 pass the original validator but
  exceed the center's normalized Python JSON 24,000 Unicode-codepoint boundary.

The default runner first tests the unmodified bridge, then uses an explicitly
marked diagnostic parent-field normalization shim to isolate the remaining
behavior. The external source files are never edited in that run.

Positive evidence: identical accepted payloads deduplicate; external role is
preserved; 50,000 synthetic Chinese characters form 3 batches/9 parts, all
archive successfully and the cursor advances. No batch-versus-part completion
bug was observed.

## Repair

The patch rejects tool errors before accepting replies, requires source and job
acknowledgements, parses structured and text responses, uses status by job,
moves parent lineage into metadata, and measures normalized wire JSON using
Unicode codepoints and Python's separator spaces. Control-character escapes
receive enough splitting headroom.

Tool errors are conservatively non-retryable protocol failures. Current MCP
errors lack stable machine categories; the patch does not guess permission or
transient categories from prose. The ledger retains failures with its cursor
blocked for review. Network uncertainty retains identical-payload replay.

An isolated patched copy passed 14 real HTTP assertions covering these repairs,
long/escaped text, a committed write with lost response then deduplicated replay,
and missing acknowledgements. Eight synthetic sources/jobs were archived; model
calls were zero. The patched copy also retained 84/84 upstream fake-suite passes.

## Reproduce

Use the existing memory-center Python environment and Node 24 (`node:sqlite`).

```sh
.venv/bin/python scripts/check_localvault_compatibility.py /tmp/localvault-original
```

Apply to a separate clean checkout of the pinned source revision:

```sh
cd /tmp/localvault-patched
git apply --check /path/to/personal-memory-center/integrations/localvault/compatibility-73be498.patch
git apply /path/to/personal-memory-center/integrations/localvault/compatibility-73be498.patch
cd /path/to/personal-memory-center
.venv/bin/python scripts/check_localvault_compatibility.py /tmp/localvault-patched --patched
```

The default mode reproduces original defects; `--patched` verifies corrected
behavior. Both force HTTP to an OS-selected loopback port and reject requests
to any other origin. All credentials and documents are synthetic.

This is code compatibility evidence, not acceptance of the user's real
LocalVault instance, its grants or document quality. Source withdrawal
synchronization remains a separate integration task.

## Product and memory-node planning

See [LocalVault 与记忆中心：统一规范与双向协作建议](MEMORY-NODE-PLAN-2026-10-05.md)
for the proposed independent local-memory product, shared governance rules,
versioned exchange, permissions and development sequence. These proposed
candidate/event/delta capabilities are not part of the current archive MCP.
