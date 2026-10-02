# 本人陈述与人工维护切片

`owner_memory.create(store, principal, scope, body)` 新增本人填写的陈述；`owner_memory.revise(store, principal, scope, record_id, body)` 统一处理文字与审核字段的不可变版本编辑。REST/UI 已接入：本人可新增陈述和补充/修改；本模块不创建新表、不调用模型，写操作只在本人明确操作时进行。

## 输入与权限

只接受服务端已验证的 trusted_user=True、明确 owner/id，以及目标 scope 的 read/write。外部导入、只读 Token、Agent 材料整理不得调用此本人入口，也不得自行指定 role/source_type/trusted_user/source_id。author 是执行本人维护的账号，不等于陈述中的主张者 holder；默认 holder 不从 owner 或 principal.id 推断，引用他人观点需本人填入稳定实体 ID。

create body：request_key、statement，及可选 topic、kind、subject、governance。request_key 必填；topic 默认 topics、kind 默认 claim、subject 默认未指定。正文最多 2000 字符。governance 可含 holder/subject_id/as_of/valid_until/state/priority/note，默认 candidate/P3，其余归属/日期未知。

revise 还需 revision 与 governance_revision，分别与原记录及审核元数据作并发比较；字段没变化也不能略过版本校验。旧记录必须 active，任一版本不符直接 Conflict，请刷新后再提交。

## 原子、幂等与版本

新增在一个事务中写来源、archive-only job、record、明确 candidate governance、审核事件、版本事件和 index generation。request_key 在 owner/scope/principal/操作内固定；相同请求返回原记录，不新增任何事件或 dirty generation；同键不同内容拒绝。不同 principal 的相同 request_key 属于不同请求。

正文变化会新建本人陈述来源，状态 user_stated，但这只表示来源性质，不代表核实通过。旧 record 保留 superseded，新 record revision 加一，supersedes 指向前版；旧来源、governance 和事件都保留。

正文未变、仅审核元数据变化时，新 record 保留原 source_id、message_id、quote、status；旧摘要仍是 imported_summary，AI 发言仍保持原角色归属。另建本人审核 audit source 记录本次操作，以 source_envelope.locator 关联新 record；它不是原事实的替代证据。返回 source_id 是本次 audit/entry source，新 record 的事实 source_id 可能不同，UI 应从 snapshot 展示原来源。

新的治理状态默认 candidate。旧 holder、subject_id、成立/失效日期、priority 和 verified 不自动继承；本人可在表单看到旧值，但保存时需要再次提交相关字段。元数据编辑的正文不变时，现有展示译文复制到新 revision，原译文保留；正文变化时不继承旧译文，避免错译展示。

## 明确确认的边界

常规 UI 不传 explicit_confirmation，默认保存候选，再用现有核实入口逐条确认。本模块可支持明确 `explicit_confirmation=True`，但必须对应 state=verified，并在本次请求重新填写 holder、subject_id、as_of；实体必须已登记（owner 内建实体仅在显式填入时使用），日期必须规范 YYYY-MM-DD、当前已成立且未失效。未来或已失效陈述不能静默标为当前 verified；可保留 candidate 或明确 historical。

仅有 state=verified、旧状态为 verified、正文引用匹配、摘要重复或 Agent 导入均不构成确认。manual authorship 与判断 holder 仍分开；明确确认不会把原 AI/摘要的来源角色改为 user。维护账号的 trusted_user 权限必须由服务器已有会话提供，不能由请求体声明。

## 技术标记与验证

manual entry/audit jobs 的 usage 明确为 method=owner_manual、operation、model_skipped=true、total_tokens=0；其状态 archived，不会进入 LLM 提炼。metadata-only 新 record 的 processing_method 仍来自原 source 的实际 provenance，不因本次操作者而覆盖成 manual。

9 项合成测试覆盖：默认候选及未知 holder；来源逐字证据、archived job/索引入队；request_key 幂等和冲突/principal 隔离；明确确认与稳定实体/未来失效日期拒绝；不可变更正及旧审核保留；metadata-only 摘要归属保留；双版本 CAS；trusted/owner/scope/read/write 守卫；事务中途失败时来源、记录、supersession、事件、index generation 全部回滚；导入字段及推断确认拒绝。
