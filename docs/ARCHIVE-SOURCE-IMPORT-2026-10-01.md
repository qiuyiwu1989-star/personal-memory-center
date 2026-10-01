# 全量可见原文覆盖：安全归档 adapter

`archive_source_import.import_batch(store, principal, scope, batch_id, dry_run=True)` 把已授权、已经由当前 Claude 可见正文 parser 准备的 bulk_segments 投影为可读 Store.sources。默认 dry-run，不写任何表；显式 `dry_run=False` 才新增 archive-only 来源。它不会由默认 GET、检索或 index 重建触发。

```python
from pipeline.memory_center.archive_source_import import import_batch
# 先只预览；真实 principal 必须由服务端验证，不应从请求体取权限。
coverage = import_batch(store, principal, scope, batch_id)
# 上层已授权 archive-only 导入时才显式执行。
# coverage = import_batch(store, principal, scope, batch_id, dry_run=False)
```

## 可见性与访问前提

必须拥有该 scope 的 read、source_read、write；批次还必须精确匹配 owner/scope。bulk_batch_parsers 必须标记当前 `claude.PARSER_VERSION`；缺失或旧 flattened parser 批次一律拒绝，不修改其计划、来源或原始归档。只有受服务端保护的 parser marker 可信：不能让外部客户端任意伪造 marker。

逐段只接受 conversation/imported_summary，以及规范 id/role/text/source_title/created_at 消息投影字段；未知结构、thinking/tool 字段、非可见角色和隐藏块标签均拒绝。当前 visible parser 以 text block 为正文，thinking 和 tool block 被排除；消息中的可疑隐藏块标签亦保守拒绝，即使可能只是文字示例。全批先验证，再开始任何导入，无法证明可见则拒绝整批。

函数不重新下载 COS、不解析任意外部路径。若旧批次 marker 不匹配，必须先由独立归档重规划流程依据已验证原件重新产生可见投影，不能把旧 marker 直接改成最新来绕过拒绝。

## 幂等与信任

来源键使用独立 `claude:readable:` 前缀加稳定 SHA-256，与旧提炼来源分开。摘要和对话保留原角色；关联 metadata 记录原归档、原 source_key、conversation_id、segment_id、segment_index 和 parser_version。

内部去重 principal 固定，但仅继承已经校验的 owner、单个 scope 和授权 action 的交集，`trusted_user=False`。它不是新凭据，不提供任何额外权限；原文导入不会自动升格为本人长期记忆。不同调用 Agent 重跑同一批次也不会新增相同来源；正文或元信息版本变化可新增来源 revision，旧来源保留。

这里是可读副本，不能把它与同一原归档的旧提炼来源误计为两个独立佐证。独立来源计数必须通过 metadata 回到同一 conversation/segment，而不是按 sources 行数累计。

## 处理状态与成本

所有新 jobs 固定为 archived，绝不进入提炼队列；不新增 records，不修改 bulk_batches/bulk_segments、预算、已花 tokens、parser marker 或工作状态。model_calls 和 extraction_tokens 固定为 0；这仅指本 adapter 不调用提炼模型，不代表 Codex 开发不耗模型用量。

返回已规划 segments、含可见段的 conversations、summary_materials、messages、visible_chars，以及 new_sources/duplicates/imported_sources。dry-run 的 imported_sources 永远为 0。conversations 只计当前批次有可见段的对话，不宣称所有归档对话都有可检索正文；没有可见内容的对话不能编造来源。

多段导入并非一个巨型事务：进程中断可能只归档了前半批，但不会安排提炼；再次显式调用可按稳定键补齐。这种恢复不会改变历史 bulk 暂停状态。

## 验证

7 项显式合成测试覆盖默认 dry-run 数据库完全不变、零模型成本、不同调用者幂等、assistant/external 原角色与 trusted_user=False、archive job 状态、原 bulk 状态/预算/segment 不变、旧 parser 拒绝、全批排除校验失败时零写、结构化工具字段拒绝、owner/scope/action 防护。没有真实原文、私钥、生产写或模型调用；线上导入与覆盖核验由主任务显式决定。
