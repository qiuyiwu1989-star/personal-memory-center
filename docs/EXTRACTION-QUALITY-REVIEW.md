# 候选质量提示：先标记，再治理

`extraction_quality.review(claims, source=None)` 对已经完成证据定位的候选返回仅含元信息的质量报告：逐条 `claim_index`、`codes`、有限 findings 和统计；不复制陈述或来源全文。可把报告写入 job usage 的 `quality_assessment`。另用 `review_notes(result, claims)` 生成原完整 statement → 最多400字符中文提示，放入独立 `quality_review_notes`，不覆盖既有 review_notes。source 可用于精确识别服务生成的日期及对话标题前缀，不进入报告。输入候选不被改写、删除、拆分或确认；此模块不访问数据库或模型。

诊断逐条给出 `candidate`、`review_required` 或 `archive_only` **建议**。它们不是实际治理状态，不授予可信资格，不改变当前有效性，也不禁止明确的本人纠正。所有诊断明确 `semantics_verified=false`，总报告始终 `quality_approved=false`。是否隔离或留在档案须由后续明确治理策略决定，不能只因无警告就放行。独立 `quality_policy_version=extraction-quality-review-v1` 与 v14 PROMPT_VERSION 分开，旧试验历史与冻结合同保持不变。

- 证据有条件、陈述无条件信号：标记条件作用域待复核。同段命名事实可能独立于条件，因此不宣称已证明遗漏。
- 陈述同时有命名/发生事实与希望/计划信号：标记混合命题待拆分。仅证据混合而陈述独立的命名事实不因这条规则受罚。
- 可独立主体边界：提示检查是否多个命题，不自动机械逐句分拆。
- 明显一次性处理请求且无持续约束信号：建议 `archive_only`，保留原候选供复核。相邻即时请求不抹掉持续约束。
- 同 topic/kind/subject/status 的逐字相同陈述：关联先前候选；不做近义词判等或跨归属合并。
- 同 topic/subject/status 的逐字共同完整片段：记录关联索引与片段哈希；额外限定仍可能有价值，不据此删除或拼接。

标签判断属于可审计信号，不是语义蕴含、长期价值或真实准确率。标题/日期只在能精确识别服务标签时剥离，避免把来源元信息当作观点。旧冻结合同、真实试验失败与警告保持不变；新合成测试不等于真实材料通过。接入时还需保证 usage 诊断有界，并由服务层保护私有来源与候选内容。
