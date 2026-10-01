# T02：可见原文发现

原文发现为未提炼、没有长期价值、或尚未核实的材料提供查找入口。它返回来源证据，不把命中升格为个人观点或正式记忆。索引与数据库来源独立，可重建；没有 LLM、向量服务和新增依赖。

## 入口

```python
from pipeline.memory_center import source_discovery
source_discovery.setup(store)
source_discovery.rebuild(store, principal, scope, force=False)
result = source_discovery.search(store, principal, scope, query,
                                max_chars=6000, offset=0, limit=20)
page = source_discovery.read(store, principal, scope,
                            result['results'][0]['locator'],
                            offset=0, max_chars=4000)
```

`setup` 初始化 migration 005 的两张衍生索引表。`rebuild` 是显式索引写操作，必须同时具有该 scope 的 read、source_read、write；搜索和分页必须同时有 read、source_read。所有路径先校验权限，再操作数据库。不同 owner、scope 的行不能混入结果，locator 不能绕过这些条件。helper 不发放新权限。

索引只覆盖 Store.sources 中已经存在的 messages。COS 中的原始 Claude 归档不会自动进入索引；归档准备与来源导入由上层独立处理。准备归档不能顺带开启提炼队列。

## 增量与版本

- source_id、声明的 digest、payload/source_type/source_key 指纹和固定 index_version 一起决定是否需要重建。
- 来源不变时跳过；force 重建所得 chunk id 仍一致。
- chunk id 是 owner/scope/source/version/message/index/字符范围的稳定 SHA-256，包含 payload 指纹，避免声明 digest 没更新时旧 locator 指向新版本。
- 搜索与读取 JOIN 当前 sources，并验证当前指纹；来源删除、digest 或 payload 漂移时，旧索引立即失效，不能返回旧正文。显式重建后恢复查找。
- 清理仅移除该 owner/scope 下已不存在来源的衍生索引，不改 sources、候选、正式记忆或事实状态。
- 不同 source_id 的历史版本各保留其索引及明确 digest，不推断最新版本就是当前观点。

## 可见范围与标签

只索引 role 为 user/assistant/external 且有可见 text 的消息。thinking/analysis 类型、thinking 角色、结构中的思考块均不索引；正文中的 thinking/think/analysis 标签片段（包括未闭合尾段）替换为等长空白。隐藏字节既不进入索引也不返回，原始字符位置保留。

返回角色、material_type（conversation/imported_summary/document/correction 等来源类型）、source_key、source_id、source_digest、message_id、标题、来源日期、chunk 字符范围和 locator。material_type 是已记录的来源性质，不是模型猜测的文体或事实分类；暂不自动判断引用是谁的观点。结果始终标明 `source_evidence`、`evidence_only` 和 `facts_confirmed=False`。

## 排名与预算

可见正文切成最多 1000 字符、重叠 100 字符的片段。排序使用已冻结的 lexical-v3 中文二字片段、语法切分、完整词串和英文词边界；只搜索可见正文及来源标题。没有同义扩展、事实核实或自动退回共享单字。相同分数保留来源时间及消息位置的稳定顺序，空查询按来源顺序浏览。

search 的 offset 按结果片段分页，limit 为 1–100；read 的 offset 是该可见消息的原始字符位置，返回 next_offset，可以无损拼接可见消息。完整 JSON 包括元信息在 max_chars（500–16000）内；元信息本身装不下时显式报错，不跳过结果或截掉 locator。search 中 snippet 最多 240 字符，read 不自动截断整条消息。

这版采用可重建的分块表与确定性扫描排名，未引入数据库 FTS/向量索引。数据库 SQL 可用于 SQLite 或 PostgreSQL adapter；大语料的扫描延迟、重叠片段造成的结果重复应继续测量，不能声称已完成千万级检索。排序相关不等于准确性，来源时间也不等于事实成立时间。

## 验证

9 项显式合成测试覆盖：增量/force 幂等和来源不变；角色与来源标签；thinking 排除及字符定位；权限与跨 owner/scope 拒绝；digest/payload 漂移及删除失效；完整 JSON 字符预算、无损消息分页；检索分页稳定；非法参数。不会调用模型，测试来源以 archive 策略录入，不安排提炼任务。真实 PostgreSQL 和公开 MCP/REST 接入由主任务另行验证。
