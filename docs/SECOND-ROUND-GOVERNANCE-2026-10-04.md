# 第二轮：治理守卫与实际客户端验收准备 · 2026-10-04

本轮只进行本地合成协议验收和代码修复，不修改生产、不申请新凭据、不调用模型、不替本人确认真实记忆。

## 已完成的实质修复

发现直接调用 REST 可以提交 `change_kind=withdrawal` 且 `state=verified`：前端原有约束不会保护直接 API，007 会留下撤回审计，但陈述仍可用于可信上下文。现在服务端在同一事务中拒绝这种不一致组合；撤回必须由调用者明确传 `rejected`，不能自动改状态。语义审核、修订、新建共享该事务守卫，不改变普通候选或默认旧流程。

只读核对稳定版本 `7362fb0e41acbbd698b938ee2baa8f220996f68e` 的 `temporal.py`，其中也没有该守卫。此判断是源码证据，不证明线上已有异常数据；未扫描或修复生产记录。可单独回移该小改动到稳定后端，不能把实验提炼方法一并发布。

新增三项真实本地 REST + MCP 路径的合成测试：

- 显式 007 撤回后，两个独立只读主体取得相同空可信上下文与新版本标识；审计保留操作者和版本，不推断事实失效日期。
- `withdrawal + verified` 审核/修订返回 400；过期治理版本修订返回 409；均不增加原文、记录、审计或投影代数，原可信上下文不变。
- 明确解释纠正后，两端先看不到待审核新版本，审核后均只读到新版本；旧版和审计谱系保留。

这是服务端协议测试，不代表两台实际 Agent 或线上已登录浏览器验收。客户端已加载的旧文本不会由服务端主动清除，必须在纠正边界重新读取 `context_revision`。

## 可直接执行的离线准备

以下命令从仓库根目录执行；所有数据明确为合成。第一项只是准备摘要，不提交 fixture；第二项只用临时库和进程内协议。不得将合成 scope 当作已经发行的真实权限。

```sh
.venv/bin/python -c 'import json; from pathlib import Path; from scripts.check_memory_integration import inspect_input; print(json.dumps(inspect_input(json.loads(Path("tests/fixtures/integration_readonly_synthetic.json").read_text())["input"])))' 
.venv/bin/python scripts/check_memory_integration.py --self-test
.venv/bin/python -m unittest discover -s tests -p 'test_memory_cross_agent_correction.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_memory_temporal.py' -v
```

离线准备保留三个角色、条件和更正；报告仅输出计数及哈希。已有自测覆盖归档、角色、重试、来源版本和撤权等能力，但不证明真实 LocalVault 适配器已经实现。

## ArkClaw：实际实例只读联调步骤

在实例侧配置已有 Streamable HTTP 地址 `https://qiuyiwu.com/api/memory/mcp`，通过私有凭据管理填写现有只读 Token。不要在对话、URL、截图或收据里粘贴凭据。实例需支持远程 MCP 和公网出口；未知时先报告功能缺口，不把服务改成匿名。

1. 初始化并取得 `tools/list`，将无凭据的 schema 导出到私有文件。运行 `scripts/check_memory_integration.py --check-tools <私有tools-list.json>`；核对名称和参数，不能仅凭工具数量判定兼容。
2. 用已授予 `personal` 的凭据调用 `memory_context`，参数 `{"scope":"personal","query":"协作方式","max_chars":1600}`。若为空，应明确说“暂无已核实上下文”，不能调用历史候选填成个人事实。
3. 如 schema 存在，用 `memory_candidate_search` 调用 `{"scope":"personal","query":"协作方式","max_chars":1600,"offset":0,"window_limit":10}`。标明候选性质；工具缺失时缩小 query 用兼容读取，不编造分页参数或扩大 scope。
4. 有 source_read 权限时，用 `memory_archive_search` 的实际 schema 搜索当前获准范围。无结果即记录空结果；仅当结果返回真实 locator，才用 `memory_archive_source_get` 展开该 locator，`offset=0,max_chars=4000`。下一页沿用返回坐标，不自行拼造 locator。
5. 在明确未授权的 scope 做一次纯读取，记录被拒绝与不泄露正文。只读阶段不为了测拒绝而向生产发送写入请求；写权限负测在隔离合成服务已经覆盖。

收据只保留实例/客户端版本、传输、工具 schema 摘要、scope、调用类型、结果计数、版本标识、字符数、时间和错误类别；私有原文和凭据不进入公开仓库。准确引用和不确定性需在 ArkClaw 实际回答中人工核查。当前 personal 为空，无法验证有用个性化背景或真实更正传播；不能用归档条数充当通过。

## LocalVault：最小准备与随后小批试点

本轮只复核既有对接文档，未取得 LocalVault 代码或运行实例。先由对方提供现有枚举/读取能力、稳定版本、角色/位置字段映射，使用上面的 fixture 做 payload-only dry-run，记录所有分段的 hash、长度、父来源和错误。现有 `--check-input` 不替代真实适配器的账本及重启恢复实现。

随后使用已注册的独立 inbox 与归档专用凭据，在明确授权小批内提交；必须保存 source/job 收据，逐段完成才推进资料版本，重试同 key+同 payload，索引成功与归档分开。此步骤需要尚未发行的 LocalVault 收件范围和凭据，本轮不执行。删除传播尚无完整闭环，不启动无人值守同步，也不把文件消失等同用户授权永久删除。

## 后台与客户端验收清单

| 事项 | 当前证据 | 下一步 |
|---|---|---|
| 人工新增、修改、审核、拒绝、历史回查 | 第一轮本地真实浏览器合成验收 | 在已登录线上后台补验收，不能绕过登录 |
| 007 明确撤回、冲突原子性 | 本轮真实本地 REST + 双 MCP 合成测试 | 发布稳定回移后，在获准隔离数据上验收 |
| 两端纠正一致性 | 两个独立本地只读主体一致 | 两个实际客户端重新读取；检查旧缓存处理 |
| ArkClaw 实例连接 | 服务端探针历史证据；非实例验收 | 实例内执行上述步骤并保存脱敏收据 |
| LocalVault 实际归档续传 | 本地协议自测；非实际适配器 | 对方能力映射、独立凭据、小批账本联调 |

模型质量、scope 条件判断和版本漂移属于其他并行工作，本报告不宣称它们已完成。真实客户端接入所需的实例能力、认证和资料授权不是代码测试可以替代的。

本轮定向验证：双客户端纠正测试 6 项、007 时间审计 7 项通过；归档离线自测通过 16 个检查，model_calls=0、remote_network_calls=0。公开树扫描通过。
