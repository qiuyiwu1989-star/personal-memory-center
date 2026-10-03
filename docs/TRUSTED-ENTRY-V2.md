# 统一可信入口 v2（2026-10-03）

## 变更与兼容

纠正转述与确认判断是两个动作。旧 `POST /records/{id}/correct` 仍接收
`statement`、记录 `revision` 及既有时间审计字段，但新记录一律为 `candidate`。
正文、引用和取代链保留；已核实旧版本的审核字段留在旧版本，不继承到新正文。
候选更正文也不推定主张者、稳定对象或成立时间。没有模型调用、自动重提炼、预算改变或生产回填。

明确确认使用现有本人审核入口，提交 `state=verified` 和治理 `revision`，
经共享 `judgment_contract.normalize` 与 `validate_verified` 检查：

- 主张者 `holder`、对象 `subject_id`、成立日期 `as_of` 明确；
- 实体在同 owner/scope 注册（本人保留 ID 除外）；
- 日期规范，成立不在未来，失效时间未到；
- 请求人是本人且具有范围写权限，记录仍 active，审核版本匹配。

本人新增/修订继续要求 `explicit_confirmation=true` 与 `verified` 配对。
审核入口本身的 `state=verified` 是明确审核动作，不从旧状态或正文修改推断。
旧纠正入口不接受 `governance` 或 `explicit_confirmation`，防止忽略额外字段而误报已确认。
记录 revision 拒绝布尔值，trusted_user 严格要求布尔 true。

## 旧数据读取

无治理字段的旧 correction 视作 candidate。已有 `owner_corrected` 原样保留、可回查，
但不进入可信上下文，也不自动迁移成 verified。本人应核对归属、对象与成立时间后再明确审核。
这次仅改变准入，不删除来源、修改历史或批量回写旧状态。

可信上下文策略标识变为 `explicit-verified-v2`。只有 active、完整且日期规范、当前有效的
verified 可加载；残缺或非法旧 verified 读取时排除，不修复或写回。
实际语义真值仍需本人判断；结构合法不构成内容正确证明。

## 验证

合成回归覆盖默认纠正不升格、原 verified 更正文重新核实、旧来源/审核历史保留、
旧 owner_corrected 和缺治理记录排除、残缺/非法 verified 排除、确认权限/实体/有效时间、
布尔 revision 和额外确认字段拒绝、两个并发纠正仅一个成功及旧版本审核失败。
既有跨 Agent 更新与 context_revision 测试现在显式审核后再断言可信读取。
所有数据为合成，不运行真实模型或写生产。

迁移行为：无新增 schema。对旧调用的有意兼容变化是“更正即可信”取消；
调用端应先展示候选回执，再用明确审核步骤确认，而不是自动补日期或实体。
