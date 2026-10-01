# MCP 与加载契约：2026-10-01

目标是按需提供有来源、归属及有效状态的上下文。原文发现、抽取候选、可信上下文是三种不同返回，不能互相冒充；匹配引用不能自动证明语义正确或现在有效。

## 已有工具契约

下表以仓库 `service.py` 当前实现为准；客户端上线前仍应读取实际 `tools/list`。`scope` 默认 personal，身份/owner 来自私有凭据，不能由来源文本设置。

| 工具 | 默认与边界 | 返回含义 / 权限 |
| --- | --- | --- |
| `memory_search` | query 必填；max_chars=6000；retrieval_mode=lexical-v1 | 带治理状态的候选，read；v2/v3 为显式词法实验，无自动降级、无真实性认证 |
| `memory_context` | query 必填；max_chars=1600；retrieval_mode=lexical-v1 | 仅治理层判为可用的 verified/owner-corrected 记录；read；无候选补位 |
| `memory_document_get` | topic_id=''；offset=0；max_chars=4000 | 空 topic 列文档目录，指定 topic 读 MD 页；read；目录 offset 为条数，正文 offset 为字符 |
| `memory_source_get` | source_id/message_id 必填；offset=0；max_chars=4000 | 一条原消息的有界页；同 owner 且 scope 的 source_read 权限 |
| `memory_import` | source_key/messages 必填；source_type=document；processing_policy=archive | scoped write；最多100条、24,000序列化字符，默认只归档，不调用提炼模型 |
| `memory_reextract` | source_id/request_key 必填 | scoped read+write；返回排队 ID，不覆盖旧版，不确认候选；使用当前方法和同一模型预算 |
| `memory_import_status` | job_id 必填 | 同 owner、scope read；返回单任务 state/attempts/error/usage，不返回原文；received 不等于完成 |

所有读取均不调用提炼模型。分页与搜索预算为 **500–16,000 字符**，计算序列化返回信封，不能转换成精确账单 tokens。正文跟随 `next_offset` 拼接；检索返回 `truncated`，当前候选搜索没有 offset 参数，应收窄 query。空返回须说明范围与治理口径，不等于“从未发生”。

导入保存原 message id、role、created_at。source_metadata 支持 original_ref/original_date/author/locator/parser_version/parent_source_key；这些是来源说明，不是授权声明。重试使用稳定 source_key 及一致内容；相同来源键的不同内容不能假定为同一次导入。重提炼 request_key 同源、同方法、同操作保持幂等，冲突拒绝。

## 已实现的原文实验入口（接口冻结）

以下两个工具仍为 experimental，是否线上可用以实际 `tools/list` 为准。它们只检索已建立索引的 **Store.sources**，不读取全部 COS 归档，不新增候选、不确认事实、不调用提炼模型。

| 工具 | 默认与边界 | 返回 / 权限 |
| --- | --- | --- |
| `memory_archive_search` | query 必填，最长1000字符；scope=personal；max_chars=6000；offset=0；limit=20（1–100） | read+source_read；results/total/next_offset，kind=source_evidence，facts_confirmed=false；offset按命中结果计数 |
| `memory_archive_source_get` | locator 必填；scope=personal；offset=0；max_chars=4000 | read+source_read；一条可见消息的 text 页，offset为字符；版本失效、owner/scope不匹配拒绝 |

locator 包含 chunk_id/source_id/source_digest/message_id/message_index，应原样传回，不能自己编造。搜索结果包含角色、材料类型、来源时间、片段位置和有界 snippet；read 返回完整可见消息的分页，不只当前 chunk。分析/隐藏思考不进入可见索引；同源相邻块与候选表示不能算成重复独立证据。显式后台索引重建需 read+source_read+write，读取不隐式重建。

执行前 Store.sources 为276份旧来源。现已从校验通过的归档补入616份可见正文来源；712份来源可检索（616正文分段与96份已有摘要），覆盖352段有正文的对话。13段无可见正文保留原件；180份旧扁平对话投影仍不参与索引。来源数与对话数不同，摘要不是用户原话。三baseline真实答案质量复盘尚未完成。

新资料通过已授权的导入事务自动合并入原文索引队列，独立后台线程更新索引，不调用模型。memory_import_status 的 index_status 只表示该范围技术索引进度，与提炼状态和事实确认分开；idle 不表示历史索引完整。读取工具仍不隐式写入或重建。

轻量加载建议：已有新鲜上下文则零调用；需要个人背景先 1,600 字符可信 context；需要历史或证据再针对性查候选/原文、读取少量原消息；深入复盘才扩页。当前/过往、用户/助手/外部、原话/导入摘要须在回答中分开。

## 模型调用和失败计量

显式 extract、reextract 及翻译会消耗 scope 模型预算；工具收到请求只说明接收，不说明已成功调用。服务端先按完整输入字节及输出 allowance 预留，余量不足暂停。成功或失败请求均按返回 usage 结算；缺失 usage 或崩溃保留预留、状态 usage_unknown，不记为免费。客户端不要把 failed、零候选、没有 usage 当作零账单，也不要自动重复未知失败。共享历史预算仍受服务端限制；质量批准与上限调整不属于读取或导入权限。

## 30 任务预冻结验收框架

`scripts/evaluate_memory_acceptance.py` 验证/冻结契约，并对外部产生的结果评分；它不执行检索、生成答案或评判答案语义。

- 必须至少30个独立任务，按 conversation 整组拆 development/test；同 conversation 不得跨组。
- 必须包含 archive（原文）、candidate（抽取候选）、combined（两者联合）三 baseline，联合 corpus 必须为两种身份的并集。同源两种表示不算两个独立证据。
- 任务 query、直接目标、答案 rubric 与契约 SHA 冻结；报告逐任务 query 与返回 ID 一致，拒绝遗漏、未知或重复身份。
- 检索指标和最终答案评判分开。P@5 固定槽位，R@5/MRR 只算有目标任务；无目标精度/召回为 null，另算空返回。当前框架的 false_returns 表示非直接目标，不自动等同语义上完全无关。
- 最终答案需独立标注正确性、归属、时间、引用支持、弃答与理由；not_run 不允许附带“已评分”答案。评分器只聚合显式判断，不把命中原文转换成正确答案。
- 真实材料、报告及标签只存私有仓库外，0600；公开 fixture 全部为 synthetic。Agent 标签必须声明暂定，不能宣称人工 gold；读过测试结果调参后，该集应视为回归集，再冻结未见留出任务。

公开合成框架为10个会话 × 每个3任务，共30任务，development12/test18。覆盖历史决定、助手草稿、未知当前状态。该数量验证框架，不证明真实质量或充分领域覆盖。

```sh
python scripts/evaluate_memory_acceptance.py \
  --contract /private/contract.json --output /private/freeze.json
python scripts/evaluate_memory_acceptance.py \
  --contract /private/contract.json --report /private/three-baselines.json \
  --output /private/scored.json
```

当前只完成合成框架冻结与拒绝漂移/跨组泄漏等单测；真实三 baseline 与最终答案尚未运行，质量未批准。未新增实际提炼模型调用，也未恢复生产全量队列。
