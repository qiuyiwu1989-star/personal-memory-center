# Agent 对接契约与本地协议验收

本轮已经用真实 TCP 回环 HTTP 跑通 MCP 的协议及归档契约，而非仅调用 Python 方法或检查模拟断言。所有资料、身份和凭据均为合成数据，数据库是临时 SQLite；无生产请求，无模型调用。**这不是 LocalVault 或 ArkClaw 自身运行成功的证明，也不证明生产服务器已更新。**

## 可重复验证

在项目已安装依赖的 Python 环境运行：

```sh
python scripts/check_memory_integration_contract.py
python -m unittest discover -s tests -p 'test_memory_integration_contract*.py' -v
```

脚本自行启动仅绑定 `127.0.0.1`、操作系统分配端口的临时服务，禁用 worker，在临时库显式应用 009 来源撤回迁移，结束后关闭服务并删除临时库。它不接受生产 URL 或生产 Token。输出只含检查名称、是否成功与能力边界，失败时只输出异常类型；HTTP 库的诊断日志可能出现在 stderr。

本轮通过的契约：

- `initialize → notifications/initialized → tools/list → tools/call` 经真实 HTTP 完成。当前服务为 stateless HTTP，初始化无 `Mcp-Session-Id`；后续携带协商所得 `MCP-Protocol-Version`。客户端仍应能够兼容未来服务返回会话标头。
- 默认归档返回 `id`、`job_id`、`duplicate`，状态为 `archived`，模型使用量为空；归档未生成记忆记录或提炼任务。
- 本人、助手、第三方的 `user / assistant / external` 角色按原文保留，传输角色不构成真实身份核验。
- 相同凭据身份、范围、来源标识和规范化内容重试，返回相同来源及任务 ID。相同来源标识、内容改变，产生新来源 ID 并保留旧来源。
- `archive_only=True` 凭据拒绝显式 `extract`、`memory_reextract`；拒绝写入和读取 `personal` 或其他收件范围。原文读取另需 `source_read`。
- 无可用记忆时，`memory_context` 返回空 records、total=0 与 context_revision，不自动把归档或候选当作已核实记忆。
- 撤销凭据后，下个请求返回 HTTP 401。已认证工具中的权限和输入错误表现为 HTTP 200 + MCP result.isError=true，不能只看 HTTP 状态判断业务成功。
- 来源撤回通过真实 HTTP 验证：普通 Agent 无权预览或撤回；合成本人身份能预览影响、撤回并幂等重试；已核实上下文不再返回受影响记录，context_revision 变化，Agent 原文读取被拒绝，原文及记录在审计库仍保留。为此直接装载了一条显式合成候选，并由治理函数核实为合成 fixture；这不是 LLM 提炼、真实用户授权或生产个人记忆。

## 给外围开发者的实际字段契约

以当前 `tools/list` 和运行时验证为准，不根据旧说明假定字段或字符单位。

| 内容 | 当前契约 |
| --- | --- |
| 范围与权限 | 服务端凭据决定 owner、scope、actions、archive_only；资料声明不能扩大权限 |
| 来源标识 | `source_key` 长度 1–300 个 Python Unicode code points；`#` 可使用；300 个非 BMP 字符已实测通过 |
| 父来源 | `parent_source_key` 位于 `source_metadata` 内，不能假定为 MCP 顶层参数；当前并非自动撤回分组协议 |
| 消息 | 1–100 条；id 唯一且 1–100 字符；role 为 user/assistant/external；text 非空 |
| 可选消息字段 | source_title、created_at 为长度不超过 300 的字符串。created_at 当前不是严格 ISO 日期验证；未知日期应省略，不能虚构 |
| 元信息 | 只允许 original_ref、original_date、author、locator、parser_version、parent_source_key、visibility；值为不超过 1,000 字符的字符串；额外字段拒绝 |
| 可见性 | unknown / visible_only / complete_visible 是资料覆盖声明，不是授权或事实验证 |

规范化消息 JSON 不超过 **24,000 code points**。服务端序列化是 `json.dumps(normalized_messages, ensure_ascii=False, sort_keys=True)`，保留 Python 默认分隔空格。它不是 UTF-8 字节数、不是 JavaScript UTF-16 `string.length`，也不是 compact `JSON.stringify` 字符长度。id、role、text 与存在的 source_title、created_at 都参与计算；source_metadata 不参与这个消息上限，但受自身字段限制和 HTTP 请求体上限限制。客户端建议使用已有 `prepare_imports` 分段适配器或实现相同规则，并保留余量；不得自动截断正文。

下面是公开合成的最小参数例子：

```json
{
  "scope": "agent:synthetic-contract-inbox",
  "source_key": "synthetic://doc#v1-part-1",
  "source_type": "document",
  "processing_policy": "archive",
  "source_metadata": {
    "parent_source_key": "synthetic://doc",
    "original_ref": "synthetic://original",
    "parser_version": "synthetic-v1",
    "visibility": "visible_only"
  },
  "messages": [{"id": "external-1", "role": "external", "text": "合成第三方原话。"}]
}
```

归档成功回执示意：`{"id":"synthetic-source-id","job_id":"synthetic-job-id","duplicate":false}`。客户端把 `id` 存成自己的远端 source ID，不能等待不存在的 `source_id` 返回字段。幂等唯一性包含 principal 身份，不承诺换一份凭据身份后仍与旧凭据去重。建议外围用明确版本及分段标识建立 outbox，并保存每段回执。

## 空结果和错误不能混为一谈

`records=[] / total=0` 仅表示当前范围、查询及治理规则下没有匹配的可用记忆，不表示用户没有任何历史。`records=[] / total>0 / truncated=true` 可能是预算不足以容纳整条结果。候选、归档索引与当前可用上下文是不同集合；不得遇空结果就扩大权限或把候选升格。

客户端分别处理：网络超时、HTTP 401/403、JSON-RPC error、MCP result.isError、归档任务状态。服务端尚未对所有工具提供统一稳定错误码和 retryable 字段；不应通过自然语言错误文案推断可重试性。未知归档结果先按同一内容重试并比对回执，不是立即创建新来源。

## 后续验收的真实边界

1. LocalVault / ArkClaw 实际 `initialize`、tools/list 和参数映射仍须由该客户端运行并回传脱敏结果。专用 scope、凭据是否已经正确配发也须单独确认，本脚本没有申请或发放凭据。
2. 完整“归档 → 治理 → Agent 读到个人记忆 → 本人更正 → Agent 再读到新状态”尚未以外部客户端验收。这里只证明归档不会自动变成个人记忆。
3. 来源撤回已在本地合成已迁移数据库验收，报告 source_withdrawal_verified=true；生产是否应用独立 009 迁移及真实外围撤回联调仍未验证。此次不是物理删除，也不支持根据 parent_source_key 自动批量撤回整个文件；每段回执和后续分组协议仍需对齐。
4. 公共代码合成验收不能代替生产升级、数据库迁移、全量质量评估，不能据此放开 LLM 预算。外部 Agent 已缓存的旧上下文也不能由中心强制从历史 prompt 中删除。
