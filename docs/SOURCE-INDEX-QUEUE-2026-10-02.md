# T12：导入后的零 LLM 自动索引

已有原文索引可以重建，本轮只补导入到索引之间的合并队列。新资料归档后，不用人工全 scope 重建，也不会给每个 source 安排一次昂贵扫描。没有新依赖、进程架构、外部服务、模型调用、提炼预算或事实确认。

## 集成接口

```python
source_index_queue.setup(store)
# 已验证权限的 Store.ingest 写事务内，新增来源成功后调用：
source_index_queue.enqueue(db, owner, scope)
# 现有后台 worker 定期调用，每次最多一个 owner/scope：
source_index_queue.work_once(store, lease_seconds=120, debounce_seconds=2)
# 工作台只读状态：
source_index_queue.status(store, principal, scope)
```

setup 创建 migration 006 的 scope_index_queue，主键 owner/scope。enqueue 是内部 hook，调用者必须已验证 ingest 权限，不是对外导入 API，不应接收未经服务端验证的 owner/scope。它复用 ingest 的 db 和事务；来源与 dirty generation 一起提交或一起回滚，不能另开连接后单独入队。重复来源若没有新版本，也不应为了本 hook 人为增加 generation。

worker/status 不执行 setup 或回填。首轮自动运行只覆盖正常 enqueue 的新变更；历史资料需要单独授权后显式入队，不能通过发布代码自动全量回填。

## 合并、并发和恢复

每次新资料使 generation 加一；pending、ready、failed 合并为一个 pending 行。processing 中的新导入保留原 lease，只提高 generation，不撤销正在工作的 claimant。默认 debounce 为两秒，连续导入期间推迟 claim，减少每 source 都做全 scope 重建。

work_once 在短事务中领取最多一个 pending、可重试 failed 或 lease 已过期的 processing 行，lease 有限（1–900 秒）。随后用技术 principal 执行现有 source_discovery.rebuild：只有原 owner、单个 scope、read/source_read/write，trusted_user=False，没有对外凭据或额外 scope。rebuild 仍扫描该 scope 的来源、按 source digest 判断变化，只重建变化版本；旧 legacy 可见性守卫不变。

完成时比较 lease 与 generation：

- lease 已被其他 worker 换走：不能修改新 claimant 的状态。
- generation 未变且成功：indexed_generation 追上本次 generation，状态 ready。
- 处理中 generation 有变化：状态返回 pending，保留 dirty，稍后再合并处理。
- generation 未变且异常：状态 failed，保留 dirty，按 2–60 秒有界退避重试；只保存异常类名，不保存异常正文、SQL、来源、工具 payload 或 traceback。
- worker 崩溃或超时：lease 过期后可重新领取，旧 claimant 的 lease 不能完成新 claim。

scope 全量扫描可能比 lease 更长；本轮不引入心跳续租，可能发生重叠重建，现有 rebuild 写事务保障索引一致，CAS 防止队列完成覆盖。实际延迟需要继续测量并在 900 秒内调整 lease；不能声称这已经完成无限规模性能优化。

## 状态与边界

status 只要求目标 scope 的 read，并按 owner/scope 查一个行。返回 generation/indexed_generation、state、dirty、lease_active、error_type、retry_after、last_indexed，不返回 owner、lease token、source 明细或正文。未入队返回 idle，不能把 idle 解释为所有历史来源已经建立索引。

队列只自动维护可见证据索引。它不调用提炼模型，不改变 bulk 状态/预算、jobs 的提炼状态、正式 records、信任或事实有效性；ready 表示这轮技术索引完成，不表示资料准确、记忆审核通过或旧 legacy 内容可以读。

## 已接入

Store 初始化建立队列表；新增来源与 enqueue 在同一事务提交，重复来源不新增任务。start_worker 在同一服务内启动独立索引线程，与付费提炼线程共用停止信号。资料卡片与 MCP memory_import_status 分别呈现范围索引状态和提炼状态。公开 MCP 仍为9个工具，未扩大外部权限。

## 验证

10 项显式合成测试覆盖：同 scope 多次 enqueue 只一个行；事务 rollback；处理中导入后 generation 不丢；lease 被抢不能完成；过期恢复；错误只存类型及有界退避；一次只领一个 scope、status 权限与 owner 隔离；debounce；真实 rebuild 不改变原来源/jobs/budget/facts；legacy 内容仍不索引；参数检查。没有实际历史回填或生产写。
