# 对 LocalVault 评审的回复与方案修订

2026-10-05。根据用户提供的评审整理。以下是中心侧建议及证据说明，不替本人批准本地 LLM、生产同步、预算或候选确认；未修改 LocalVault 仓库/真实安装/私有 claims。

## 结论

认可独立本地节点的产品定位；收敛首轮实现为证据节点。首轮复用索引、来源版本、现有 ledger 与处置判断，不立即新增本地候选治理引擎，也不调用 LLM。完整离线记忆能力保留为待本人决定的产品选项，不能把评审方的“不做”自行提升为用户永久决策。

新增 P0 出网闸门，适用于发送正文到中心、COS 原件和云端模型，不只适用于模型 API。闸门按目的、接收方、实际载荷和规则/授权版本检查；自动检测存在漏报边界，未知阻断或人工预览。只有脱敏件获准时原件留本地。先完成该前置，再安排真实资料小批，不把白名单/文件名过滤当成正文已脱敏。

## 逐项处理

| 评审意见 | 中心处理 |
| --- | --- |
| 本地独立记忆引擎过大 | 首轮删去该开发包；本地候选是后续选项，如实施先评审 claims.db 同库新增表，不改旧事件 |
| 原件上传排在脱敏之后不清楚 | 增加 P0-0，并明确正文同步也受出网闸门约束 |
| 首版只允许本地模型 | 不自动采纳为调用授权；首轮零 LLM，本地模型也是需本人决定的后续选项 |
| ledger 和 outbox 命名不同 | 按可靠交付行为验收，复用 ledger，不另造同功能模块 |
| claims 字段映射不严 | 写成拒绝规则：verdict 不映射 verified、ts 不映射 as_of、note 不直接映射长期 statement |
| 14 与 84 看似矛盾 | 明确不同测试仓库、运行方式、断言对象和复现命令，见下 |
| COOPERATION 文件本地找不到 | 改为明确中心仓库路径，并提供跨仓库固定链接 |
| P0-1 本地已具备 | 认可已有大量可靠交付行为，不重复建设；但原版真实 HTTP 缺陷修复及实际小批仍未完成验收 |

## 14 / 84 的证据归属与复现

84 是 LocalVault `mcp-server/test/upstream.js` 的假端点断言执行次数；不能与中心 HTTP 检查加总，也不能以它证明中心返回格式已兼容。

14 是中心仓库的兼容脚本，启动 OS 分配端口上的真实回环 MCP HTTP 服务、临时 SQLite 库、合成凭据/资料，加载 LocalVault 实际 client/bridge 代码。修复副本通过 14 项检查；模型调用 0，用户真实安装未验收。测试入口：

- [中心 Python 回环服务与执行器](https://github.com/qiuyiwu1989-star/personal-memory-center/blob/5479a2887e3315bb91e679396c9f1e90eb240087/scripts/check_localvault_compatibility.py)
- [中心 Node 客户端检查](https://github.com/qiuyiwu1989-star/personal-memory-center/blob/5479a2887e3315bb91e679396c9f1e90eb240087/scripts/localvault-compatibility.cjs)
- [针对 LocalVault 73be498 的兼容补丁](https://github.com/qiuyiwu1989-star/personal-memory-center/blob/5479a2887e3315bb91e679396c9f1e90eb240087/integrations/localvault/compatibility-73be498.patch)
- [中心侧复测说明](https://github.com/qiuyiwu1989-star/personal-memory-center/blob/5479a2887e3315bb91e679396c9f1e90eb240087/integrations/localvault/README.md)

在中心仓库、既有依赖环境中运行（不需要生产凭据）：

```sh
# 默认模式：复现原版的 22 项观察，包含预期缺陷，不是兼容通过。
.venv/bin/python scripts/check_localvault_compatibility.py /path/to/localvault-original

# 另建 73be4988553be167ea7073458b1f2bc70ab5a3af 的干净副本，在副本中应用补丁。
git -C /path/to/localvault-patched apply --check /path/to/personal-memory-center/integrations/localvault/compatibility-73be498.patch
git -C /path/to/localvault-patched apply /path/to/personal-memory-center/integrations/localvault/compatibility-73be498.patch
.venv/bin/python scripts/check_localvault_compatibility.py /path/to/localvault-patched --patched

# LocalVault 自身原有假端点回归。
node /path/to/localvault-patched/mcp-server/test/upstream.js
```

原版问题不是缺少 outbox 名称，而是 HTTP200 MCP isError 被当成收据、JSON TextContent 中 id/job_id 未保存、parent_source_key 层级不匹配，以及序列化长度边界。HTTP403 假端点测试不能替代 HTTP200 工具级拒绝测试。补丁后的缺回执/拒绝不会推进游标；真实已提交但响应丢失的同载荷重试也有检查。

所以 P0-1 应分三层报告：本地行为回归、中心真实 HTTP 合成兼容、实际实例小批对账。前两层已有可复现基础，第三层仍待出网闸门与实际配置。不得把任何一层叫成完整真实数据验收。

## 跨仓库文件入口

COOPERATION 确实已经创建，但在中心仓库：`personal-memory-center/integrations/localvault/COOPERATION-2026-10-05.md`。独立复制方案到 LocalVault 时相对链接会失效，此处修正为：

- [可靠归档合作说明固定版本](https://github.com/qiuyiwu1989-star/personal-memory-center/blob/3acc07a6032b851302846fe6cd30a288fa6ab80e/integrations/localvault/COOPERATION-2026-10-05.md)
- [初始记忆节点方案固定版本](https://github.com/qiuyiwu1989-star/personal-memory-center/blob/3383cf685e7ca4781baa83c9cfb794b6907eec63/integrations/localvault/MEMORY-NODE-PLAN-2026-10-05.md)
- [本仓库修订后的方案](MEMORY-NODE-PLAN-2026-10-05.md)。后续共享文档时连同此目录保留，或使用对应 commit 的完整 GitHub 链接。

## 下一次双方要对齐的交付

LocalVault 提供出网闸门草案、实际代码版本与非敏感运行入口、现有 ledger 状态图、claims 映射及 as_of 未知规则的 schema 草案。首轮不要求提供新本地模型引擎。

中心提供真实 HTTP 复现入口与补丁（已具备）、字段/权限映射、脱敏件与原件表示契约，并在闸门通过后准备独立收件配置和真实小批对账。后续候选包、下行日志、可信本人事件尚待开发，不使用现有 memory_import 冒充这些能力。

对方报告的私有库数量与本地历史约束未在中心侧独立复核；中心不发布具体私有记录，不据此回填个人事实。评审里列举的断言映射可用作讨论材料，最终兼容与质量仍按各自复现结果验收。
