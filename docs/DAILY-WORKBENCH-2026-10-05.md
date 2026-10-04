# Daily workbench usability — 2026-10-05

## Delivered in the UI

A compact action row uses the existing design tokens and introduces no new tabs:

- **拖入资料 · 先归档** selects the archive policy. Opening this entry does not submit a job or call a model. TXT/Markdown/JSON upload and preview remain the existing implementation.
- **补充个人记忆** switches explicitly to the authorized `personal` scope before opening the owner editor. It saves a candidate; quotation attribution and effective dates still require review. It never assumes that a manually entered quote belongs to the owner.
- **核实当前范围候选** clears text, topic, status and history filters, then displays current-scope candidates.

An empty-personal guide distinguishes candidate records from usable context. The budget status states that archive, manual entry and governance review remain available when the model budget is exhausted. Manual jobs are labeled as not using the model. Records that leave the candidate filter after review are explained rather than silently appearing deleted.

## Bug fixed

A second refresh requested while the first refresh was running was dropped. A quick scope change could therefore leave the old scope's list visible without loading the new scope. A queued refresh now loads the latest selection after the active refresh completes. Existing scope and identity checks continue to discard stale responses.

## Validation

Six new synthetic DOM/transport regressions execute the real UI handlers:

1. Viewing history then using the personal-entry shortcut writes only to `personal` and stays candidate.
2. Read-only clients cannot invoke the personal owner editor.
3. The archive shortcut resets an earlier extract selection without submitting anything.
4. Exhausted budget messaging keeps zero-model paths available.
5. Personal guidance separates candidates from usable records.
6. Switching scopes during an active refresh schedules a fresh request.

The 10 existing UI contract tests and the 6 new regressions pass together.

A private temporary local store with the explicit 007 temporal setup and a zero-token budget was also exercised through the browser. A synthetic owner statement was saved as candidate, then explicitly reviewed with the virtual **本人** entity and its stated effective date; the overview and list showed one usable record. A synthetic external text was successfully archived with no model call. These are functional checks with synthetic data, not evidence of real extraction quality or production acceptance.

## Release compatibility and remaining work

Files: `admin/memory-agent.html`, `assets/memory-center.js`, and `tests/memory-daily-workbench.test.cjs`. All API calls use existing routes. The HTML adds no dependency and the script does not modify extraction prompts, budgets, credentials or backend migrations. A stable-v17 release can carry this UI without adopting the experimental extraction code.

The server must already support owner-record creation, governance review and the independent temporal migration; UI errors remain visible if those capabilities are missing. Production release/owner login acceptance is tracked by the coordinating agent. Actual file dragging and external ArkClaw/LocalVault sessions were not repeated in this slice.
