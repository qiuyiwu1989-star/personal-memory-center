# 记忆中心第三轮开发总结

继续用户批准的多任务执行安排，三路子 Agent 完成远程候选窗口、渐进读取规范与语义复核收据，主 Agent 合并、验证及发布。

## 完成的能力

1. **候选窗口可以被 Agent 调用**：新增 `memory_candidate_search`，REST 为 `/candidate-search`。支持 offset/window_limit/max_chars，返回完整排名总数、预算截断与检查窗口；明确 kind=candidate_reports、facts_confirmed=false。原 memory_search 保持兼容，memory_context 只加载明确核实且当前有效的判断。
2. **读取 Skill 与接入自检**：仓库中的 Skill 优先少量可信背景，再按具体证据需求查候选和原文。空 personal 不触发事实补位或跨 scope 搜索。自检按实际工具 schema 识别能力，不依赖工具数量；旧服务只在明确边界内降级。没有修改本机已安装 Skill 或第三方客户端。
3. **语义复核可留审计收据**：五维记录归属、承诺、条件、时间与出处。未评仍 not_run，有歧义仍 ambiguous；provider 生成完成和 pipeline 拒绝分开记录。原件、输出、方法、rubric 与评审输入冻结哈希，私有收据排他新建，可以追加父收据 hash。工具不替代语义判断、不认证评审者身份、不改变生产质量门槛。

## 验证

375 项 Python 测试、11 项 Node 测试通过，两个 Skill 的 quick_validate 有效，公开树扫描通过。接入自检为进程内 MCP、合成资料，0 个模型请求、0 个远程客户端调用。新增工具测试覆盖 500/1,500 字符应用响应预算、严格整数输入、权限撤销、跨 owner/scope 隔离、超大项跳过及重读同窗。

没有恢复旧批提炼、提高预算、发行凭据、创建 inbox 或升格个人候选。开发探针和语义收据框架均不等于真实质量验收；旧 case5 仍未判通过。

## 下一步与限制

- 排名 offset 基于实时结果，写入时可能漂移，不是固定快照游标。客户端应检查 coverage；预算遗漏需重读同窗而不能断言不存在。offset 最大 10,000，来源字节、原文索引与实验模式成本仍有待优化。
- 真实语义试验仍需冻结独立资料、执行生成、独立复核和记录实际用量。该轮只补齐记录流程，没有生成真实评测结果。
- personal 可信内容仍待确切审阅；原子库判断不能直接作为本人当前事实。
- 真实 ArkClaw/LocalVault 实例联调、客户端持久补偿和删除传播仍未验收。仓库 Skill 和测试接口不代表这些实例已加载或执行。

专项文档：[候选远程读取](CANDIDATE-REMOTE-READING.md)、[Agent 读取流程](AGENT-READ-PLAYBOOK-2026-10-03.md)、[语义审阅收据](SEMANTIC-REVIEW-RECEIPTS-V1.md)。上线回执随后追加；部署不会运行模型或迁移私人记忆。

## 发布与公网验收

- 模块已上线：`7362fb0e41acbbd698b938ee2baa8f220996f68e`；[CI 37091652479](https://github.com/qiuyiwu1989-star/personal-memory-center/actions/runs/37091652479) 通过。
- 恢复 PostgreSQL 副本通过旧范围、候选总数与窗口、本人确认／纠正隔离、历史保留和索引并发验证，副本已删除。
- 线上 MCP 共 10 工具：新增候选工具能读取 23 条示范范围的总数与两个不重叠窗口；personal 只读权限正常且仍为空。匿名、写入、跨范围及冒充本人纠正均被拒绝。
- 线上 REST 新候选接口在 500 字符预算下实际返回 191 字符应用 JSON，总数保持 23；非法 offset 字符串明确拒绝。
- 生产记录仍 2,228；历史批次仍 paused_budget，1,967,655 / 3,000,000 tokens，代码发布不执行模型或改变额度。真实 ArkClaw 客户端不在这些服务端探针的验收范围。

## 对留存真实输出的额外独立复核

另启一名不继承本会话结论的 Agent，仅读本机既有原文和结果计划副本，先保存来源 rubric 再评审，不读取旧独立评分、不执行历史 runner。旧编号 4–8 保留：案例暂定通过 1、失败 1、未运行 3；4 条候选的 20 个维度暂定通过 14、失败 4、存疑 2。请求／需要增强成执行计划、以及条件在概括中的继承仍需解决。

新结果以 independent_agent/provisional 追加私有收据，未改旧标签、原件或结果。只审查留存 provider_plan 副本，未找到或认证 provider wire 原始响应；这不是人工 gold、新盲冻 holdout 或全库质量结论。该历史输出不是 v17 新生成成绩，不能拿它认证新方法通过或失败。quality_approved=false、production_gate_changed=false，旧失败仍不放行。

复核收据 SHA256：`bdab0d8f1d5b1ab59b2a85e97fecc265cb572291854f1e6b476feddf33786629`；六份收据和包在私人目录排他新建、权限 0600，私人原件未进入公开仓库。本次使用会话 Agent 的推理能力，未新增火山后台模型 API 调用；脚本 model_calls=0 只表示无额外后台 API 调用，不表示 Agent 推理不消耗 Codex 用量。

下一步优先按这些缺陷冻结有界新方法试验，补齐尚未运行的正例、多人归属和后续更正；独立复核与最终质量放行分开。真实 ArkClaw 联调已请求实例侧工具名与只读调用状态回执，未收到前不声称客户端接通。
