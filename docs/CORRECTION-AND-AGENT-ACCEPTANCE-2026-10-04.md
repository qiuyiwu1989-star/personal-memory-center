# 人工纠正与多 Agent 读取闭环验收 · 2026-10-04

本轮完成的是合成数据下的真实本机 HTTP/MCP 验收，以及外部客户端可运行的只读探针。没有改生产数据、申请真实凭据、确认 personal 记忆、调用 LLM，也没有把 ArkClaw 或 LocalVault 标为已接入。

## 已完成

新增 `tests/test_memory_correction_http.py` 在随机 loopback 端口启动真实 uvicorn 服务，使用 HTTP 请求穿过 REST 和 MCP 鉴权边界。临时 SQLite、合成身份及四份合成凭据在结束后清理，后台 worker 关闭，模型入口一旦调用即失败。

实际跑过以下顺序：

1. 两个独立 reader 读取空 personal，返回合法空结果。
2. 合成人类通过人工维护接口明确核实一条陈述，两个 reader 都读到该记录及原件定位。
3. 人工修改正文，旧版成为 superseded，新版仍为 candidate；两个 reader 当前上下文均为空，context_revision 变化。
4. 人工核实新版，两 reader 均取得新正文和版本；旧版仅在本人历史列表中保留。
5. 人工撤回新版，两个 reader 当前上下文再次为空，不回退到旧版。
6. reader 不能编辑或审核；独立 inbox writer 不能创建 personal 记忆或读取 personal；无 source_read 的 reader 不能展开原文。
7. inbox writer 通过 MCP 归档 assistant 材料，同 source_key 重试返回 duplicate。原件角色仍 assistant、trusted_user 为 false，未创建任何记忆事实。
8. HTTP 返回 no-store，临时服务退出。

这证明服务端的当前读取规则和纠正路径成立，不证明外部 Agent 会主动刷新其已有缓存；客户端仍需按任务重新读取并比较 context_revision。

本轮助手资料采用 archive，不启动提炼。已有角色/治理单元测试覆盖抽取候选；此 HTTP 验收不将「原件成功归档」说成「候选质量通过」。

## 后台已有能力与限制

代码检查发现 `assets/memory-center.js` 的人工维护表单已明确显示：保存为待核实候选，核实归属和有效时间后再确认；成功提示为「候选已保存」。审核表单区分 candidate / verified / historical / rejected，列表也区分本人纠正性质与已核实状态。

本轮没有完成生产浏览器登录/点击验收，不能把源码检查当作线上人工体验验收。上线后最小操作为：新增一条合成测试陈述 → 编辑 → 确认显示待核实 → 核实 → 撤回 → 检查历史。生产测试资料应使用独立验收范围，不向 personal 填入合成陈述。

## 外部运行侧只读自测包

新增 `scripts/check_agent_memory_read.py`。在拥有两份已分配独立只读凭据的客户端运行环境中，私下设置以下环境变量，再运行：

```sh
.venv/bin/python scripts/check_agent_memory_read.py
```

变量为 `MEMORY_MCP_URL`、`MEMORY_READER_TOKEN_A`、`MEMORY_READER_TOKEN_B`，可选 `MEMORY_READ_SCOPE`（默认 personal）。不要把 Token 写进仓库、URL、命令行或提交日志。

探针对两份凭据分别进行 initialize 和 notifications/initialized，保留协商的 MCP-Protocol-Version 与可选 Mcp-Session-Id，然后仅调用 memory_context，按 A/B/A/B 四次读取比较规范化响应哈希，并检查来源和版本字段。输出只含条数、context_revision、协议版本、哈希与结果，不打印正文或凭据。空 personal 合法，但不代表已有个性化记忆。仅支持 JSON 响应的 Streamable HTTP；遇到 SSE 明确失败，不冒充通用 MCP 客户端。响应按块读取，在累计解码字节超过 200,000 前停止，不先完整拉取再检查。只接受 HTTPS 或本机 loopback HTTP，不跟随跳转，不用环境代理；需要平台代理的运行环境需单独评估网络配置。

状态码：0 为四次读取一致；1 为请求或契约失败；2 为读取不一致（并发变化或可见性差异，需复核）。哈希一致只证明该次受字符预算限制的结果一致，不证明覆盖了所有记忆，也不证明语义质量。

`tests/test_memory_agent_read_probe.py` 验证不安全 URL、相同凭据拒绝、错误输出脱敏、独立会话握手、SSE 明确拒绝及超限流式停止。

此脚本适合运行侧网络/鉴权初验。ArkClaw 的实际 MCP 客户端还应验证自己的 SDK 握手、工具发现、Skill 安装及按需加载；脚本成功不能代替那些验收。

## 下一步最小外部验收

- 先完成配置版本的正式发布与生产浏览器验收；核对生产提供的 context_revision 契约。
- 由实际 ArkClaw / LocalVault 运行方在其环境执行只读探针，提供脱敏结果、客户端版本和执行时间。无需发送 Token。
- 使用客户端实际 MCP 调用确认 personal 合法空结果或已有可信上下文；缓存不得忽略 context_revision / 授权变更。
- 后续为单独 inbox writer 验证 assistant 原件提交、稳定键重试与回执查询。写入不得携带 verified，也不得直接写 personal。
- 首批真实 personal 准入仍依赖真实来源质量和人工核实规则，本轮合成 HTTP 通过不会自动放行。

## 复现

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_memory_correction_http.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_memory_agent_read_probe.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_memory_cross_agent_correction.py' -v
.venv/bin/python scripts/check_public_tree.py
```
