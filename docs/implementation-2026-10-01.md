# Memory center v0.2 implementation boundary

Production module release: `b06f2f5c766c70dc2394b2a47b10b34aac898b4b`.

Implemented governance companion tables, owner review/entity registration, small Markdown projections and visual directory cards, material inventory, budgeted re-extraction with adopt/discard previews, separate Chinese translation projections, and seven progressive MCP tools. Legacy records are retained as candidates rather than automatically verified. Reads do not invoke a model.

Verification: 61 Python tests, three Node segmentation tests plus eight legacy file validation assertions, public-tree scanner, isolated PostgreSQL governance/workflow tests, synthetic browser review/save/navigation, and production restore rehearsal. The restored 2,228 records and legacy batch aggregates were unchanged. Public live tests verified login protection, anonymous denial, seven MCP tools, bounded document pages, source retrieval, read-only and scope restrictions, and matching published assets. Production needed explicit `QIU_MEMORY_ORIGIN=https://qiuyiwu.com`; a missing origin caused MCP host validation to reject external requests until corrected. Configure the actual deployment origin before release, preserving strict host/origin checks.

Historical Claude extraction remains `paused_budget`, 1,967,655 charged/reserved of 2,000,000 tokens. No new real extraction or translation calls were made in this implementation boundary. New scope budgets default to zero; model task budget changes do not silently resume the historical batch. Historical and new-task accounting mutually constrain dispatch; retries reserve atomically. Usage not returned remains reserved.

A private 50-record stratified baseline has preliminary quotation/statement checks, including an acknowledgement-only source supporting an over-expanded claim. This is not a completed semantic quality evaluation. Guardrails and tests do not prove the revised prompt's real accuracy. Remaining work:

1. [Full-context evidence, attribution, temporal and value review](https://github.com/qiuyiwu1989-star/personal-memory-center/issues/1).
2. [Bounded revised extraction and Chinese translation quality comparison](https://github.com/qiuyiwu1989-star/personal-memory-center/issues/2).
3. [Ten real task retrieval evaluations and loading-policy adjustment](https://github.com/qiuyiwu1989-star/personal-memory-center/issues/3).

Budget expansion follows actual quality acceptance. Format adapters are added per need after locator/parser boundary tests. Private evidence, credentials, evaluation samples, backups and screenshots remain outside this public repository.
