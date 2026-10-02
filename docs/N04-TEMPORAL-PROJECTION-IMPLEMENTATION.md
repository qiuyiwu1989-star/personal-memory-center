# N04 最小时间审计与派生刷新切片

本轮交付追加事件，不建立可编辑的第二份判断。`007_temporal_projection_audit.sql` 必须作为
独立迁移步骤应用；代码不会自动创建此结构。`temporal.setup` 仅供明确调用的临时恢复演练。
旧接口在未迁移的库上继续运行；使用新显式字段时会拒绝并回滚整个修改事务，不半写记录。

## 明确动作与时间

本人新增、修改与治理审核接口额外接受 `change_kind`：metadata_update、evidence_update、
interpretation_correction、viewpoint_change、withdrawal、legacy_unspecified。省略时保留
legacy_unspecified，不通过文本差异推断“本人观点改变”。动作标签本身不确认记忆，不自动
改变治理状态；原有权限、revision 和 explicit_confirmation 继续执行。

`previous_valid_until` 仅 viewpoint_change 可以提供，要求规范 YYYY-MM-DD 且不早于旧
明确 as_of。未提供则保持未知；不是用纠正时刻猜事实失效日期。新事实期仍由治理的
as_of / valid_until 编辑，事件只是其审计快照；旧治理不被静默覆盖。

memory_change_events 记录关联新旧记录、记录和治理版本、动作标签、事实期审计快照、
明确的旧事实终点、actor、request_key、recorded_at 和 previous_retired_at。后两个是系统
版本进入/退出时间；同记录治理审核时代表治理版本退出，不能冒充事实终点。迁移前的
历史时间不回填，覆盖范围只能称 since-migration-only，不能宣称完整双时间追溯。

新增/修改与事件、scope dirty generation 同事务；同 request_key 重试在原幂等检查返回，
不会再次追加事件或标脏。审核继续通过旧治理 revision 拒绝并发过时提交。Agent 没有
本人确认/纠正权限，新事件模块本身也检验 trusted_user 和范围写权限。

## 确定性派生刷新

scope_projection_state 只管理 scope 内已知主题文档的 generation/refreshed_generation，
不是第二个事实库，也不负责控制模型预算。改变判断时置 dirty，调用现有 build_documents
后确定性重建文档并在同一事务 acknowledgement。刷新失败保持 dirty，可重试；刷新不会
重新写本人陈述、重复事件或调用模型。文档缓存签名增加日期，避免跨天失效仍复用旧标题。

temporal.status 提供 scoped 只读状态；暂无新 MCP 或后台 endpoint。未迁移显示 unavailable，
迁移后尚无变更显示 untracked，不能把未知当作“已全部刷新”。已知范围文档刷新 ready 也
不等于译文、提炼预览、外部 Agent 缓存或全客户端撤回：这些传播尚未覆盖，仍须各自按
来源/版本核对；context_revision 在下一次读取检测当前可信集合变化，不主动推送撤回。

## 恢复演练与回滚

合成 SQLite 测试把已有旧记录库备份到独立文件，执行 007 SQL 两次验证幂等；旧记录和
未知 as_of 保持原样，新增审计为空。测试还验证新旧版本链、系统/事实期区分、未迁移时
显式字段回滚、日期约束、本人权限、stale revision、幂等修改、刷新失败后的补偿。

生产迁移前另做 PostgreSQL 恢复副本演练，确认搜索路径、索引、原数据计数和旧接口兼容。
本轮未执行生产 SQL、批回填、部署或真实模型。业务回滚可停用新 UI 字段并恢复旧代码；
保留新增事件/状态表，不删除事件，不把 superseded/rejected 复活为 active。恢复整库有
丢失迁移后用户修改风险，不能当作普通代码回滚。

## PostgreSQL 恢复副本验证结果

2026-10-02 使用私有 runner 从生产 memory_center 的只读转储恢复随机隔离 PostgreSQL 数据库，
只在副本执行 007 两次。旧记录计数、治理 as_of / valid_until 非空计数、批次状态与预算保持；
合成本人新增/修改及 legacy correction 都追加审计，unknown 事实期保持空值，重复请求不追加。
文档 dirty→ready 与重复刷新验证通过，第三方确认被拒绝。模型调用为零，未对生产执行 DDL；
恢复数据库与临时远端目录已清理。测试覆盖的是此最小增量与既有兼容，不证明完整历史双时间。

由此可独立应用 007，前提是作为明确的数据库迁移步骤：保留私有备份、显式设置
search_path=memory_center，以模块数据库角色执行 SQL，核对旧计数并留存迁移结果，再发布匹配
模块代码。不要把生产迁移藏在代码发布中，不做旧事实期自动回填。回滚保留事件，不复活旧判断。
