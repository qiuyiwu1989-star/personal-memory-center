# 下游 Agent 分层检索契约

本轮维护公开 skill 的 L0–L3 加载策略，并提供原生 Skill+MCP、SDK/编排 MCP 两种宿主的同语义参考。无个人背景需求时零调用；必要背景先取1600字符可信上下文；明确证据缺口再定向检索4000–6000字符；相关原文用精确版本 locator 分页，不自动遍历档案或补候选。

契约说明位于 `skills/personal-memory-center/references/host-contract.md`，执行参考为该目录的 `retrieval_contract.py`。参考注入调用器，没有凭据、网络、模型或写入代码。使用9个现有工具中的只读路径，不新增 MCP 工具。

可信、候选、摘要与档案不是同一层。证据包的 trusted_context 仍经治理和有效时间过滤；source_reports、original_evidence 不能充当可信兜底。角色和日期不等于主张归属或事实有效时间。特别注意当前 REST POST /context 读取候选，不可映射成可信 MCP memory_context。

scope、授权身份/epoch、文档或原文版本变更后，丢弃已有结果和 locator，重新检索。服务每次重查授权；本地 epoch 只是宿主失效信号，不代替服务端撤权。没有 server epoch 时不跨任务复用。原文版本漂移或权限错误终止当前展开，不猜定位符、不自动重试。

合成调用轨迹测试通过本地真实治理、候选检索与原文索引函数，覆盖两种响应封装、L0零调用、L1无可信结果不兜底、L2分组、L3 next_offset、预算、scope/版本变化和撤权。测试验证参考执行器的行为，不能证明模型会遵循 skill，不能代替宿主实际连接验收或真实语义评测。
