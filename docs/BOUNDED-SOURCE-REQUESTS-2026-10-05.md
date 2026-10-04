# 长文可用请求适配

## 实现

`pipeline/memory_center/bounded_source_request.py` 把已验证的完整原件与归档计划转换为显式 v22 开发请求。它不使用归档片段 ID 替代原消息 ID，不对分段重新判断作者或参考模板。

每个请求包含原消息可选择的证据集合、准确偏移和原件哈希，以及不可选择为证据的来源语境。先复核归档完整性，再从完整来源继承路由。完整证据跨归档边界时进入阻塞账本，不能截短后提交。普通原文或条件语境过大时阻塞请求，不自动截断。

来源语境保留邻近原消息，并带入全来源中显式条件和更正消息。这只是有标记的启发式窗口，不证明已经取得全部语义相关内容。未选的原消息 ID 显式列出；清晰参考尾部可保留准确前缀及尾部省略范围、哈希和原因。省略过任何内容的请求均标记 `context_complete=false`，保持复核要求，不能成为已确认记忆。

调用者使用 `verified_bounded_source_request` 从实际原件重新生成请求并匹配请求 ID；不信任外部提交的 spans 或 fingerprint。返回的 `request` / `spans` / `routes` 与既有 `resolve_plan` 兼容，原定位元数据不会被擅自写成声明内容。

## 接口

```python
packet = plan_bounded_source_requests(envelope, archive_plan,
    version='2026-10-04.22', max_request_bytes=65536)
bundle = verified_bounded_source_request(envelope, archive_plan,
    packet['requests'][0]['request_id'], version='2026-10-04.22')
# bundle['request'] 供显式开发模型入口使用；模型输出仍需 resolve_plan 和治理校验。
```

上限计算与模型入口一致的 JSON UTF-8 DATA 字节（含空格），不是字符数，也不是 token。该上限不包括系统提示词、配置附加提示词和模型输出，调用入口仍需单独计算和留足预算。规划器不调用模型、不修改生产、不释放队列。

## 真实开发来源结果

只运行此前固定 development 6 原件的无模型规划，未读取 holdout。8 个请求共保留 2,742 证据字符；0 条边界或请求大小阻塞；3 个请求包含部分语境标记。私有请求和原文保存在仓库外，不进入公开仓库。

这证明请求适配保留了之前继承的证据集合，并不证明语义提炼质量、参考内容挖掘完整度、归属正确或长期价值。下一步使用显式开发模型入口开展小批评测，验证后再决定生产 worker 的独立接入。

## 验证

8 项合成请求测试与 9 项完整来源继承测试通过。测试覆盖原消息定位、参考尾部、角色、跨边界证据拒绝、远处更正、条件、语境不完整声明、实际字节上限、原件篡改及方法隔离。所有请求保持 `quality_approved=false`、`automatic_extraction_authorized=false`，规划模型调用次数为 0。

## 模型开发入口已接通

`Model(store, method_version='2026-10-04.22').extract_bounded_source(envelope, archive_plan, request_id, principal, trial_key)` 会从原件重新生成请求，验证本人 read/source_read/model 权限，先预留已有账本预算（含系统提示、附加提示、DATA字节与输出），再调用配置模型并核验原消息证据。相同试跑键不自动重调；未知用量保留预留，坏产出也结算实际费用。输出不写入记忆或确认质量。

8项合成模型入口测试通过，包含非空受支持产出、原定位、无预算/无模型配置不调用、篡改原件拒绝、重复键、未知用量和坏产出计费。本轮未调用真实模型，没有生产worker接入或预算修改。
