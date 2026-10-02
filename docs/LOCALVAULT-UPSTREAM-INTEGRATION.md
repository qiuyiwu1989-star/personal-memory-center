# localvault 与个人记忆中心的上游对接说明

收件人：localvault 开发者或开发 Agent。日期：2026-10-02。

目标是让 localvault 中经用户授权的原始资料，可靠、增量地进入邱懿武的统一记忆中心，供后续提炼和跨 Agent 检索。建议 localvault 负责原件与版本，记忆中心负责记忆治理；同步桥接由普通代码完成，Skill 决定适合捕捉的协作边界，MCP 提供受限的读写接口。

这是接口说明和建议实施顺序，不是已经完成接入的声明。目前仓库链接在现有访问途径返回404，尚未核查 localvault 代码、数据库或已有 MCP 能力。请先报告实际能力，再按下述契约实现最小适配，不要为符合这份文档重建整个项目。

## 双方职责

localvault 保留原始文本/文件、稳定资料ID、版本、可验证的作者/发言者信息和原文定位。已有摘要、知识原子和 AI 分析可以作为派生资料，但必须与原件分开、能够追溯。文档被收录并不说明作者是用户；上传者也不是发言者。

记忆中心接收资料、归档和索引；后续核实谁说的、关于谁、说了什么、何时有效、证据在哪，再产生候选及有治理状态的记忆。原件、候选与正式记忆分层。当前提炼质量未放行，不能借接入恢复全量提炼。

接入桥负责授权范围、版本检测、规范化、自动分段、提交和收据。完整性检查、同步和重试不需要LLM；语言理解及语义核验才消耗模型tokens。无需为每个文件启动一次Agent。

## 请先核查并反馈

1. 资料存储在哪里，有哪些类型，能否取得正文及原件？无需发送真实私人内容。
2. 是否已有稳定ID、修改版本/内容hash、删除标记和增量枚举能力？如果没有，先报告缺口。
3. 是否保留作者、消息角色、段落/页码/时间戳定位？未知值必须保持未知。
4. 是否已有CLI、导出函数、API或MCP？优先复用最小接口，不要求先建公网服务。

建议提供“枚举变化”和“读取指定版本资料”两个本地能力，以及桥接端的同步账本。函数名和内部表结构由你们按项目情况决定；这些不是记忆中心已存在的工具。

## 首版范围与认证

现有记忆中心MCP地址：`https://qiuyiwu.com/api/memory/mcp`，传输为Streamable HTTP，认证使用`Authorization: Bearer <专用Token>`。这不是模型API Key，不使用网站登录密码。先通过MCP初始化及`tools/list`核查部署中的实际schema。

拟使用独立范围`agent:localvault-inbox`，**该范围和凭据尚未创建**。由记忆中心侧注册并发行，localvault不能凭填写scope获得权限。凭据仅授予该收件范围必要的read/write，不授予personal或Claude历史写入，也不授予正式记忆确认权限。若需读personal，另发只读凭据。

首版只处理用户选定的白名单目录/资料集，不默认扫描整台电脑或全部仓库。Token放本机密钥存储或环境配置，不进源码、原文、日志和导出包。本文没有任何真实凭据。

**权限缺口：当前read/write粒度不能独立禁止付费extract或reextract。** 显式传archive只能表达客户端策略，不能作为服务端安全保证。无人值守运行前，记忆中心侧需补充归档专用能力/校验，拒绝该凭据的extract与reextract，并用越权测试验证。补齐前只做合成测试和受控小批试点，不发行无人值守生产同步任务。

## 使用现有 memory_import 契约

下面是合成示例；source URI是约定定位符，不代表已经部署了可访问路由。scope也只是待注册名称。

```json
{
  "scope": "agent:localvault-inbox",
  "source_key": "localvault:synthetic-note-001:version-a",
  "source_type": "document",
  "processing_policy": "archive",
  "source_metadata": {
    "original_ref": "localvault://synthetic-note-001/version-a",
    "locator": "paragraph-1",
    "parser_version": "localvault-adapter-v1"
  },
  "messages": [
    {
      "id": "paragraph-1",
      "role": "external",
      "text": "合成示例：这里是一段作者尚未核实的文档正文。"
    }
  ]
}
```

角色规则：只有有依据的用户原话或本人原创正文使用user；Agent建议/生成稿用assistant；第三方或未核实作者用external。整段用户转贴的来信仍需标明其中引用的第三方，不能把包裹它的user角色当作全部正文归属。多人会议保留说话者标签和定位，不把多人发言标为本人。未核实speaker ID不自动匹配成人物身份。

类型规则：原始对话为conversation；文档或会议转录为document；任何二手摘要、AI整理结果为imported_summary，并关联原件。缺少原件的摘要可以归档，但不能冒充直接证据。不要为了导入而重新生成或翻译原文；中文展示可作为后续派生内容。

当前约束：每批1–100条消息，规范化messages JSON最多24,000字符，包含转义和结构，并非24k tokens。source_key为1–300字符；消息id为1–100字符且批内唯一。消息字段为id/role/text，可附source_title/created_at；正文非空。只填真实可用日期，未知日期省略，消息日期不等于事实有效时间。

source_metadata仅接受original_ref、original_date、author、locator、parser_version、parent_source_key，每项字符串最多1,000字符。不要传owner、trusted、verified、预算或额外自定义字段。更丰富的本地元信息放在localvault账本/原件中，不能静默丢弃；如果核心确需接收，先提字段扩展方案。

## 自动分段和增量版本

Python桥可复用仓库`pipeline/memory_center/import_adapter.py`的`prepare_imports`，它只准备现有memory_import参数，不是新MCP工具。其他语言实现等价适配并验证相同语义：优先完整消息/段落；超长单段连续拆分，保留父来源、角色、消息ID和位置；不截断、不摘要。

```python
from pipeline.memory_center.import_adapter import prepare_imports

parts = prepare_imports(
    "localvault:synthetic-note-001:version-a",
    [{"id": "paragraph-1", "role": "external", "text": "合成示例正文。"}],
    scope="agent:localvault-inbox", source_type="document",
    source_metadata={"original_ref": "localvault://synthetic-note-001/version-a"},
)
# 凭据/范围就绪后，逐个提交 memory_import，持久保存返回收据。
```

分段坐标采用Unicode码点，起点包含、终点不包含；JavaScript的UTF-16下标不能直接混用。跨分段的引用要能取得相邻片段。多个切块及同资料多版本不能算独立佐证。

建议版本标识包含稳定资料ID及规范化输入hash；hash覆盖正文、角色、作者/日期/定位及解析版本，不能只hash文件名。相同输入产生相同part key，变化产生新归档版本。接口不会自动将旧判断标为被取代，因此“新版本已入库”不等于“旧记忆已纠正”。

## 同步账本与失败处理

桥接账本建议按实例、资料ID、版本、分段记录：payload digest、目标scope、返回source_id/job_id、重试次数、最后错误及阶段状态。只有当前版本所有分段取得收据后，才能标记已归档；归档与索引状态分开，用memory_import_status检查。已归档不等于已提炼或已确认。

网络结果不明时重用完全相同的source_key和payload进行幂等核查/重试，不生成新ID。401/403停下解决权限，不换scope；验证错误记录原因等待修复；限流/短暂网络错误可有界退避。失败和排除资料都留元数据记录，不在日志泄露原文或凭据。增量游标不得越过未持久记录的失败项；可持久记录失败后继续其他项，但必须能补偿回放。

源资料删除时先记tombstone/撤回请求，不能悄悄丢掉同步状态。目前memory_import没有删除/撤回协议，首版不声称自动传播删除。自动化之前，需共同补齐撤回范围、旧引用与派生记忆失效策略；普通文件消失不应被擅自解释为用户要求永久删除记忆。

## 交付与验收顺序

第一阶段交付能力核查、字段映射、仅生成payload的dry-run、同步账本和合成测试。dry-run只展示数量、hash及错误，不打印完整私有正文。

第二阶段由记忆中心准备隔离范围、归档专用权限和测试凭据。先导入少量明确授权资料，验证MCP实际连接、归档/索引收据和出处回查。不要修改全局模型预算或已有批任务。

必须验证：长中文/emoji/转义文本重组完全一致；多作者不混归属；相同版本重复/未知结果重试不重复入库；重启补偿未完成分段；新版本不覆盖旧件；撤权/跨范围/付费提炼/正式确认被拒绝；删除事件明确显示待处理而非假装已撤回。

第三阶段在提炼质量独立验收通过后，记忆中心另行调度小批提炼。localvault只报告资料已经送达，不宣称成为“可信个人记忆”。扩大到持续自动同步需服务端能力边界与撤回策略都完成。

请回复四项产物：现有能力与缺口、建议字段映射、最小改动文件/模块清单、合成验收结果。先不要部署生产同步、申请全范围Token或运行LLM全量提炼。

## 参考

- [上游导入契约](UPSTREAM-IMPORT-CONTRACT.md)
- [精确字段及分段规则](../skills/memory-capture/references/import.md)
- [写入Skill](../skills/memory-capture/SKILL.md)
- [Agent凭据管理](AGENT-CREDENTIAL-MANAGEMENT.md)
- [本轮执行结果和待办](UNIFIED-CORE-EXECUTION-2026-10-02.md)
