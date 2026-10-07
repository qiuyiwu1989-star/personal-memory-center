# 来源撤回最小闭环

本轮新增的是经本人明确操作的来源撤回，不是物理删除、自动合并事实或批量取消归档。仅在合成测试中完成验收；未修改生产数据库，未与外部客户端真实联调。

## 权限与接口

`source_lifecycle.preview(store, principal, scope, source_id, max_chars=6000)` 提供有界影响预览。
`source_lifecycle.withdraw(store, principal, scope, source_id, reason='')` 执行来源撤回。

两者要求 `trusted_user is True` 和该范围的 `read`、`write`。外部 Agent 即便有收件箱写权限，也不能撤回来源。本轮不新增外部撤回授权，不改变原有凭据。

MCP 新增 `memory_source_withdrawal_preview` 和 `memory_source_withdraw`，两者均不调用模型。REST 建议采用 `GET /sources/{id}/withdrawal-preview?scope=...` 与 `POST /sources/{id}/withdraw`，提交 `{scope, reason}`。凭据由既有认证层解析，不从提交正文接受本人声明。

`009_source_lifecycle.sql` 创建追加式 `source_withdrawals` 表。SQLite 本机 Store 自动建立；生产 PostgreSQL 需单独应用迁移。未启用迁移时撤回报错，现有读取保持兼容。

## 实际效果

- 首次撤回产生持久回执，重复撤回返回相同回执并标记 `duplicate=true`。
- 来源正文、记录、治理历史和已有文档版本不删除。
- 当前记录检索、候选检索、有界上下文不再返回撤回来源的记录。
- 显式历史读取保留记录并标记 `source_withdrawn=true`、`usable=false`。
- 来源检索和 locator 读取即时排除撤回来源，无需等待索引更新；重建索引会清理其派生索引。
- 当前主题 MD 投影排除该来源的记录；跨进程缓存签名含撤回代数，下一次生成刷新版本。
- MCP 单条来源读取拒绝撤回来源；本人后台仍可查看保留原文作审计。
- 历史 bulk 批次仍在处理或预算未结算时，预览明确返回 `bulk_processing_or_unsettled`，执行报冲突，避免绕过历史专用预留的结算；已完成且结算的来源可以撤回。
- 待执行/处理中提炼任务和待审核重提炼结果转为 `withdrawn`，清除租约；已调用模型仍记录费用，不应用结果。
- 撤回后的重新提炼、翻译和应用操作拒绝执行。

## 有效证据边界

当前记录具有一个直接 `source_id`。只屏蔽直接依赖撤回来源的记录，不按相同文本推断来源合并，也不盲删其他来源支持的记录。主题重新汇总仍有效的独立记录。本人主动纠正创建的独立来源继续作为独立证据；尚未构建跨来源语义合并与依赖传播，不能宣称所有隐含衍生观点已自动重审。

不支持按 `parent_source_key` 或前缀批量撤回。多分段撤回应先设计精确的版本成员清单及原子事务，不能以宽泛匹配代替确认。

撤回使中心后续读取失效，不会强制抹除其他 Agent 已加载的上下文。客户端应对 `context_revision` 变化重新获取，并停止沿用旧结论。物理删除原件、COS 对象、备份及外部缓存属于不同保留策略，需另行实现。

## 验证

合成测试覆盖本人/第三方/跨范围权限、重复撤回、保留历史、有界预览、上下文版本变化、独立来源保留、旧索引 locator 拒绝、MD 更新、排队取消、处理中撤回与费用留存、缺失迁移拒绝写入。
