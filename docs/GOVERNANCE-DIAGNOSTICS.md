# N04 只读治理诊断切片

`pipeline.memory_center.governance_diagnostics.diagnose(existing_store, principal, scope,
sample_limit=3, max_chars=6000, today=None)` 是内部函数；没有新增 MCP、REST 或后台入口。
调用者应提供已经存在的 Store。函数不初始化表、不调用模型，不推断身份、冲突或失效时间，
只输出聚合计数和本范围内记录 ID 样本，不输出原文、姓名、来源 URL、审核备注。

要求 scope 的 read 与 source_read；计数覆盖该 owner + scope 的全部记录版本，active 单独
计数。source payload 与来源 envelope 只查询本范围记录实际引用的同归属、同范围来源，
不扫描全部无记录的档案。不存在的可选表仅报告 coverage_missing，不自动创建。

诊断类别：缺 holder / subject_id / as_of、非规范有效日期、孤立或跨范围 supersedes、
已过失效日但仍 active、当前范围无法核对的实体引用、可读其它范围证实的实体链接、
缺失或范围外来源、来源 payload 无效、消息定位缺失、引用空/不匹配、原始来源 locator 缺失。

`valid_until` 当天已经失效；`expired_active` 只描述留存的 active 结构，不声称这些记录仍
进入 memory_context（现有读取守卫会过滤）。`source_original_locator_missing` 指缺外部回查
位置，内部 source/message ID 仍可能存在；不同类别可以同时命中一条记录，不应相加当作
独立坏记录数。匹配 quote 不证明概括正确，此报告不替代语义评测。

跨范围核验只观察凭据明确可读的 scopes，绝不为分类而探测无权限范围或其它 owner。
`cross_scope_entity_reference` 是可证实的下界；其它无法核对项保留 unresolved，不能猜测
是实体不存在还是存在于无权限空间。内置 owner:<owner> 只代表当前 owner，不回填未知身份。

sample_limit 为 0–10，max_chars 为 1000–16000，限制整个 encoded JSON 包。预算不足时仍
保留 counts，减少样本并标 truncated；摘要本身超预算则拒绝。日期参数用于固定审计基线，
必须为规范 YYYY-MM-DD，不写回事实日期。

合成测试验证跨 owner/scope 授权、类别计数、来源与正文不泄漏、边界日期、整包预算、
可选表缺口，以及诊断期间所有 SQL 均为 SELECT、records/governance/events 数量不变。
本轮未运行真实库诊断、生产读写、DDL、迁移或模型调用。未来 CLI 应采用真正只读连接，
不能为了运行诊断新建会自动初始化 schema 的 Store。
