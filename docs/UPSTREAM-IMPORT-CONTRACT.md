# 上游 MCP + Skill：增量证据进入统一记忆核心

当前实现为客户端适配器 + `memory-capture` Skill，复用现有 `memory_import`，
不新增 MCP 工具、不改变核心表结构、不调用模型。适配器只生成 kwargs；实际网络提交
仍由有授权的 Agent/客户端执行。本轮没有创建生产写入凭据，也没有导入真实资料。

## 进入系统的是什么

先选择授权范围内的有价值协作边界，再归档原文：本人思考与决定、助手建议、外部材料
分别保留角色。归档不是长期记忆确认；治理流程随后核实归属、证据、价值和有效时间。
一次助手的合理概括也不能证明本人批准。原子库素材、会议和文档可使用同一来源契约，
不预设知识原子是个人判断。

来源解析不由该适配器猜测：DOCX/PDF/会议音频等仍需各自解析器获得可见正文与稳定定位。
多人会议不能把所有参与者标为本人；未核实的外部发言使用 external，后续治理再解析
人物归属。助手生成的文章或总结使用 assistant / imported_summary。

完整 MCP 字段约束及重试规则见
[导入参考](../skills/memory-capture/references/import.md)，执行策略见
[memory-capture Skill](../skills/memory-capture/SKILL.md)。

## 自动无损分段

`prepare_imports` 按规范化 JSON 的实际字符数计算上限；正常消息保持完整，最多100条/批。
超过24,000序列化字符的单条消息生成连续、不重叠的字符区间；原角色、日期、标题均保留，
原始消息 id、起止位置与父来源链接放入 locator。所有正文字符可重组；不静默截断、
翻译、过滤或添加摘要。日期仅照录，不作为事实成立时间。

生成的 part key 对父来源、范围、类型、实际正文与元信息内容寻址，重试稳定，改动另存。
不能用这个机制覆盖旧判断。消息切块不是独立证据；跨块引用需展开相邻原文。模型提炼
仍须后续授权与质量验收，单独切块不能保证语义完整。

## 可运行的合成示例

在仓库根目录运行以下 Python（只准备 payload，不发网络请求）：

```python
from pipeline.memory_center.import_adapter import prepare_imports

parts = prepare_imports(
    'synthetic://meeting/1',
    [{'id': 'original-1', 'role': 'external',
      'text': '合成会议发言。' * 10000, 'created_at': '2026-01-01'}],
    scope='agent:example-inbox', source_type='document',
    source_metadata={'original_ref': 'synthetic://meeting/1', 'locator': 'speaker-1'}
)
assert ''.join(p['messages'][0]['text'] for p in parts) == '合成会议发言。' * 10000
assert all(p['processing_policy'] == 'archive' for p in parts)
# 获得实际写入授权后，逐批：await session.call_tool('memory_import', arguments=part)
# 持久保存每个返回的 source/job receipt；不要把 received 说成治理完成。
```

## 失败边界与验收

- 未知消息字段、缺失/重复 id、未知角色、空正文拒绝处理，避免静默丢字段或猜身份。
- 原 locator 与分段描述一起超过1,000字符时明确失败；需要短的稳定原文定位。
- 长纯空白区间无法单独满足服务端“非空白正文”规则时整次准备失败，无半成品返回。
- 无权限、断网、来源不明时不自动换 scope 或扩大抓取；不打印凭据、不接触未见评测集。
- 适配器只接受内存中的正文消息，不遍历本机目录、不决定哪些私有资料可发出去。

合成测试覆盖真实 Store 入库、重复提交、角色/日期、长 Unicode/转义正文重组、100条边界、
内容版本与失败路径。测试的归档任务均 archived，候选记录为0，模型函数不执行。

```sh
.venv/bin/python -m unittest discover -s tests -p test_memory_import_adapter.py -v
```


## 2026-10-05 外围交付与回执边界

外围客户端保留原件和不可变 outbox：每个来源版本/分段的 payload、source_key、scope、
客户端 principal、发送状态、服务端 id/job_id/duplicate 回执与最后一次状态核对。
这些是可靠交付约定，不表示本仓库适配器已替客户端实现持久队列。

同内容重试须使用同 principal 和完全相同 payload。源文件改动另存新版本；本地删除
留存 pending-withdrawal 请求，不能标为已远端撤回。当前撤回 MCP 是 owner-only，
外围 Token 无此权限；工作台本人完成逐来源撤回后才能凭回执对账。parent_source_key
不构成父子批量治理 API，也不表示中心已获取本地附件或完整磁盘资料。

实际客户端联调必须独立验收归档、Unicode 分段、HTTP200工具错误、未知发送结果、
重复回执、权限隔离及 owner 撤回后的读取失效；合成测试通过不等于已接入真实资料。
完整回执/版本规则见 [导入参考](../skills/memory-capture/references/import.md)。
