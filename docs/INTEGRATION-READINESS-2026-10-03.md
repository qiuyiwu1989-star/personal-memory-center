# LocalVault / ArkClaw：可执行联调准备

本轮补齐确定性的接口自检。没有修改权限、颁发 Token、创建生产收件范围，也没有调用提炼模型。这里验证的是记忆中心当前代码的合成 MCP 行为，不能据此宣称两个客户端已经接通。

## 已交付的自检

在仓库根目录运行：

```sh
.venv/bin/python scripts/check_memory_integration.py --self-test
```

这条命令使用临时 Store 和进程内 Streamable HTTP MCP，不监听端口、不访问远程服务器。合成凭据只存在于临时测试代码中。输出为检查名称、数量和边界标记，不输出来源正文或凭据。

覆盖：工具发现；长 Unicode / 转义文本无损分段；user / assistant / external 角色保留；完全相同 payload 重试取得同一来源和任务收据；新版本归档保留旧版本；归档状态与索引状态区分；1600 字符预算原文读取；跨 scope 拒绝；归档专用凭据的 extract / reextract 拒绝；第三方纠正和核实拒绝；无可信记忆时 context 不以候选填充；撤销 source_read 后原文拒绝；只读凭据拒绝写入；凭据撤销在下一请求生效。测试中候选和正式记忆均为 0，模型调用为 0。

测试包含 source_read 是为了验证原文展开及撤权。它不是为生产写入凭据增加该权限的提议，实际授予仍按各客户端用途最小化。

只想校验上游解析结果，可使用：

```sh
.venv/bin/python scripts/check_memory_integration.py --check-input /path/to/private-input.json
```

输入严格接受 source_key、scope、source_type、source_metadata、messages，结构沿用[导入契约](UPSTREAM-IMPORT-CONTRACT.md)。必须显式指定 scope，不接受 processing_policy、owner、trusted_user 等额外字段；准备结果固定 archive。输出仅为角色计数、批次计数、序列化大小与 payload SHA256，不输出 source_key、scope、作者、标题或正文。输入应保存在私有目录，不纳入公共代码仓库。

失败只输出错误类型并退出 1，不打印包含正文或路径的异常详情。此模式不提交资料、不创建收据，不代表有生产权限或模型质量已通过。SHA256 用于客户端辨认同一准备结果，不是服务器认可的身份或可信等级。

## 上游与下游的最小约定

| 动作 | 上游客户端保存什么 | 服务端结果意味着什么 |
| --- | --- | --- |
| 同版本分段归档 | 原资料 ID、版本、分段 key、payload hash、每段 source/job 收据 | 原文已收件；索引状态需单独检查 |
| 结果不明后重试 | 完全相同 payload 和 key，不重新生成随机 ID | 同一来源/任务；不得把传输重试变成新证据 |
| 资料更新 | 新版本；旧版本及其收据继续保留 | 新原件已入库；不自动取代旧判断 |
| Agent 提出修正 | 新的 assistant 素材及旧来源定位；明确“建议” | 仍是待治理证据；第三方不能调用本人纠正/核实 |
| 再次提炼 | 由记忆中心另行授权和预算调度；新 request_key 对应一个新运行 | 比较结果，不自动覆盖旧记忆或确认质量 |
| Agent 读取 | 先小预算 context，缺可信背景时保持未知；按需检索候选和出处 | 分清正式背景、待审候选、原文；读取不调用模型 |

来源元信息还支持 visibility=unknown / visible_only / complete_visible，属于可见内容覆盖声明。遗漏附件或作者未核实不能写成完整证据；日期不等于事实成立时间。上游不可通过角色、visibility 或导入参数提升信任。

新版本、重提炼、本人修改正文是三个不同动作。本人修改后仍需明确审核才能进入可信上下文；Agent 的修正意见只能走收件证据。不要把“同原件重新抽取”称为“事实已更正”。

## 实例侧还需完成的联调

本轮本机没有可核查的 localvault checkout，因此没有臆测其数据库、导出接口或增量能力。仍须由 LocalVault 开发方提供稳定版本 ID、消息角色、原文位置、解析版本以及持久同步账本。[现有对接说明](LOCALVAULT-UPSTREAM-INTEGRATION.md)继续适用。

ArkClaw 实例的远程 Streamable HTTP 支持、公网出口、Authorization Header 配置和工具实际调用仍需在实例中验证。服务端合成通过不证明 ArkClaw 的工具装配、引用表达或上下文预算实际正确。[现有 ArkClaw 说明](ARKCLAW-MCP-ONBOARDING.md)继续适用。

真实试点验收顺序：先工具发现和只读拒绝测试，再验证 2–3 个已有原文回查与引用；隔离收件范围和归档凭据就绪后，仅导入明确授权的小批资料；检查所有分段收据、索引和原文回查；最后验证客户端崩溃恢复、未完成分段补偿及未知结果重试。当前自检没有实现持久同步账本，不能声称客户端重启恢复已通过。

删除/撤回传播仍没有完整闭环；文件消失先记 tombstone / 待处理，不能宣称服务器及其派生记忆已删除。全量无人值守同步应在撤回协议和实例补偿验收之后安排。当前提炼质量门禁、全量暂停和预算均未更改。

## 验证命令

```sh
.venv/bin/python -m unittest discover -s tests -p test_memory_integration_readiness.py -v
.venv/bin/python -m unittest discover -s tests -p test_memory_import_adapter.py -v
python scripts/check_public_tree.py
```

新增 4 项测试验证进程内 MCP 链路、私有字段不进入摘要、scope / 身份 / 模型策略不能通过检查输入覆盖，以及 CLI 错误输出不泄露路径与正文。既有适配器的 5 项测试继续验证分段边界、原定位与真实 Store 幂等。此次仅交付本地接口验证与联调准备，不声称真实客户端接入完成。
