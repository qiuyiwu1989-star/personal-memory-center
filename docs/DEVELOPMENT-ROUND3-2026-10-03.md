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
