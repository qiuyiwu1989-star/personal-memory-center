# 候选逐条隔离：显式诊断契约 v1

目的：一个候选违反来源/时间/模态守卫时，可以解释该条为什么失败，并保留同批其他候选供复核；不丢原文，也不把幸存项自动送入生产。

`pipeline.memory_center.candidate_isolation.diagnose_candidates(plan, spans, source, version='2026-10-03.21', opt_in=True)` 是无模型、无数据库、无持久化的纯诊断入口。调用方必须使用 `prepare_request` 的服务端片段与同一份完整原始 `source.payload`。诊断仅允许已经注册的 v21；未验收方法版本拒绝。

1. 检查完整来源、候选 schema 和服务端片段精确绑定。非法 JSON/schema、重复消息 ID、超出 12 条、伪造偏移/引用/标题/日期等整批拒绝，不生成貌似成功的空结果。
2. 每条依次执行原 `resolve_plan` 与 `core.validate_plan`。不存在的 evidence ID、模型冲突引用、模态/时间/归属等机械守卫拒绝只隔离该条，保存原始序号及失败阶段和原因。
3. 对幸存项再次执行整批验证。助手建议总数等批级限制仍适用；失败时所有幸存项标为 `batch_review_required`，不能删掉几条来绕过限制。
4. 返回 `diagnostic_items`，没有顶层 `claims`。状态 `guard_passed_requires_review` 只表示机械校验通过，不能说明语义蕴含、说话者、当前有效性或用户授权正确。`diagnostic_only=true`，`adoption_allowed=false`。

收据包含：原始 0 起始 ordinal、未经改写的模型候选、所选片段和 exact locator、失败原因、完整消息上下文、来源 payload 的 UTF-8 SHA-256、来源类型和可信用户声明、方法/诊断版本。长片段外的共同条件仍可能被现有切片遗漏，因此必须回查完整上下文；本模块不自动解除条件、补写时间、做普通条件范围切分或确认记忆。

收据含完整原文，必须留在私有位置，不应提交公开仓库，也不能作为记忆读取接口直接返回。此入口没有接入 `Model.extract_source`、worker 或生产接口；原有提炼整批失败行为不变。后续接入需要独立设计私有审核队列和人工/独立评测门槛。

验证：10 项纯合成测试，覆盖 opt-in/版本、默认行为不变、单条失败与顺序、全源/hash/locator、未知或冲突证据、非法结构、伪造服务端绑定、批级助手限制及成功零候选；来源角色与 ingest 契约一致，仅允许 user/assistant/external，external 文档保留 source_reported，system、非列表来源和重复 ID 拒绝。没有模型调用、付费或生产写入。
