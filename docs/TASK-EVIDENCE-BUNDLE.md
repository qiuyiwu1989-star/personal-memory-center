# 按任务读取的证据包

`evidence_bundle.bundle(store, principal, scope, query, max_chars=6000, retrieval_mode='lexical-v1')` 组合既有只读接口，查询最多 500 字符，整体序列化 JSON 预算为 1500–16000 字符。此模块不调用模型，不写数据，不构建索引，也不改变默认检索策略。

返回四组，不能合并解释为可信个人事实：

- `trusted_context`：使用 `governance.context`，继续只返回治理规则允许的已核实或本人纠正上下文，保留有效时间限制。
- `source_reports`：候选 snapshot 经过 `reading.search_page`，标为 `candidate_reports` 和 `facts_confirmed=false`。可信组没有结果时，不把候选自动补进去。
- `original_evidence`：使用 `source_discovery.search`。仅在同一 owner/scope 已授权 `read` 与 `source_read` 时返回。缺少原文权限明确返回 `status=unavailable`、`reason=source_read_not_authorized`，不会尝试扩权或调用原文检索。原文索引需另行显式建立；空结果不能说明原文不存在。
- `unresolved_questions`：保守固定提示，提醒归属、成立时间、有效性及索引覆盖仍需判断，不自动推断问题已经解决。

整体预算包括标签、元信息、提示、定位符和 JSON 转义。超预算先移除原文结果，再移除候选，再移除可信项；每项完整保留或完整移除，不截断陈述或定位符。保留总数和截断标记，原文 `next_offset` 指向实际返回后的位置。极端元信息超过预算时显式报错。

合成测试覆盖分组隔离、候选不兜底、原文权限、跨 owner/scope、完整 JSON 预算与读取前后数据库不变。这是读取组合功能的验证，不代表候选质量或检索覆盖达标。REST 接入由服务层完成；本任务不增 MCP 工具，不改变工具契约。
