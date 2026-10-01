# T08/T10：来源依赖预览

`dependency_audit.preview(store, principal, scope, source_id, max_chars=6000)` 是纯读取入口，只给出依赖数量、对象元信息与风险代码。没有 setup、DDL、删除、工作队列变更、文档重建、文件修改或模型调用；结果固定 `preview_only=True`、`deletion_supported=False`，不能用作删除授权。

首先检查 read/source_read、owner/scope，再读取目标来源。不存在、owner/scope 越权或缺少读取权限统一拒绝为「来源不存在或不可访问」，不透露跨权限来源是否存在。只需读取权限，无需 write。适用 SQLite；PostgreSQL 通过现有 adapter 使用相同关系查询和 information_schema 表存在检查。

已核查真实 schema：records 直接以 source_id 相连；jobs 通过 sources 归属；extraction_runs 带 source_id/owner/scope；source_discovery_chunks 是衍生索引；document_topics 只有前缀规则；document_versions 只有 markdown 而无持久化 dependencies。因此预览分清：

- records/jobs/extraction_runs：精确直接关系，仅返回 id、状态及版本元信息，不返回原文、陈述、错误详情、用量或私密配置。
- 主题规则：来源键与前缀匹配标为 `potential_prefix_match`，只是潜在影响；不证明该文档收录了任何事实。
- 已生成文档：检查已有所有 revision 中渲染格式的「记录」引用，与该来源的记录 ID 求交，标为 `stored_record_reference`。不调用 build_documents、不生成新的文档 revision。
- 索引片段：返回物理衍生行数量，包括可能已失效、等待重建的行；不声称数量代表现在可检索的材料。

可选表不存在时，coverage_missing 明确列出，不能把未检查当作零影响。未追踪外部 Agent 缓存、导出文件副本、间接纠正链或转引到别的系统，所以它是当前模块的直接依赖预览，不能宣称完整删除影响分析。主题目录和缓存的间接影响也仅由风险代码提示。

风险代码：record_evidence_dependency（记录的出处依赖）、unfinished_processing（未结束处理任务）、projection_and_history_dependency（投影或历史版本依赖）、derived_index_dependency（衍生索引依赖）、incomplete_optional_table_coverage（可选表覆盖不完整）。这些都是需进一步核查的事项，不是自动执行建议。

max_chars 为 500–16000，计算整个序列化 JSON。对象列表装不下时按稳定顺序截出并标 truncated，counts 仍是准确关系数量；摘要本身装不下则显式报错，不省略风险或伪造完整结果。

5 项显式合成测试覆盖直接关系、潜在主题规则/历史版本引用、索引数量、缺表与数据库完全不变、统一拒绝及无需 write、关联表 owner/scope 防护、截出列表仍保留精确计数、完整 JSON 预算及非法参数。真实生产 PostgreSQL 接入由主任务单独验证。
