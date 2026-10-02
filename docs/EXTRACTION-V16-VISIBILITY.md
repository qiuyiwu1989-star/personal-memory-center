# 来源可见性提炼契约 v16

方法版本 `2026-10-02.16`。输入新增 `source_visibility`，只有 v16 请求包含；v13–v15 请求形状及 resolver 保持历史兼容。`prepare_request(..., source_metadata=None)` 为唯一构造入口，模型请求、预估与实际执行使用同一投影。`Model.extract_source` 读取 `source['source_metadata']`，不自行查库或读取附件；usage 留存同一声明以便复盘。

来源 envelope 增加可选字符串 `visibility`：

| 值 | 含义 |
|---|---|
| `unknown` | 未声明可见文本是否完整；旧数据、缺字段及无法解析时默认此值 |
| `visible_only` | 提交的是可见文本子集 |
| `complete_visible` | 提交方声明可见文本完整；不表示附件、工具输出、链接或隐藏内容已读 |

显式发送给模型的结构只有 `status`、`declaration_only:true`、`attachments_verified:false`。不转发 author、原件 URL、任何权限或其他 source 元信息。非法值、错误类型、未知字段不能改变权限，也不能把附件声明升级成已验证事实。上游入口应枚举校验；适配器对旧/异常数据保守投影 unknown。正文原件、证据 quote/offset 不受投影影响。

提示要求：所有状态都只是未经核验的覆盖声明；不得推断未见附件/工具内容，不得根据 complete_visible 宣称来源穷尽或观点已完整。未知覆盖不排斥独立明确历史事实；需要缺失上下文的结论应不提炼。此字段本身不作为本人事实候选。

服务端集成由主任务负责：ingest/import_adapter 元信息允许字段和枚举校验；core/reprocessing 执行前加载 source_envelopes.metadata 到 source_metadata；core 的 metadata/modality 方法 guard 加 v16。服务端鉴权仍完全独立于 envelope。

合成回归检验模型请求投影、注入字段不传播、完整声明不证明附件已读、旧版请求不变以及 v13–v16 定位/日期/模态兼容。未调用真实模型，不能以模拟响应证明模型遵守该语义约束；真实独立评测仍需另行验收，不恢复批队列或确认可信记忆。
