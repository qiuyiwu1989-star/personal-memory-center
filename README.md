# Personal Memory Center · 个人记忆中枢

Source-backed, attributable, time-aware, correctable context for humans and agents.

**让你和 Agent 在需要时，取得有出处、知道是谁的观点、仍然有效的上下文，并且能纠正它。**

本仓库独立维护记忆模块的代码、方法和测试。公开的是通用实现和虚构示例；对话导出、个人记忆、运行库、凭据、生产配置和备份均留在私有部署中。

## 设计取舍

完整治理、增量实现、轻量调用：

- 原文归档 → 提出候选 → 核实归属与证据 → 判断长期价值和有效时间 → 按任务与权限提供 → 纠正与版本演变。
- Skill 规定调用策略，MCP 提供共享读写接口，后台提供资料、任务、来源与纠正管理。
- 数据库保留记录与版本；Markdown 是可读投影；大原件保存在私有文件存储/对象存储。
- 读取不调用记忆侧 LLM；选择性提炼才消耗模型 tokens。
- 原子内容库、任务系统和项目记忆各自保留真源，通过引用集成。

方法与实施边界见 [治理设计](docs/governance.md)、[旧数据处理](docs/legacy-data.md) 和 [接入与部署](docs/integration.md)。

## 当前能力与缺口

当前是从既有工作台抽离的 **0.1 首版**，没有携带原仓库历史或运行数据。

| 已实现 | 仍需实现与评测 |
|---|---|
| SQLite 本地库、PostgreSQL 适配器、来源与幂等队列 | 主张者/实体/有效时间的结构化治理字段与回填 |
| 模型适配、逐字引文校验、角色状态区分 | 语义支持检查、长期价值评测与冲突治理 |
| 明确纠正、旧版留存、主题 MD 投影 | 可审阅的重跑差异与独立治理状态 |
| 5 个限范围 Bearer MCP 工具、REST 与本地管理界面 | 短任务上下文工具、主题正文分页与精确 token 预算 |
| Claude 归档/分段/预算队列、只读结构审计 | 多 Agent 纠正一致性与完整模型成本评测 |

`active` 表示旧实现中可检索，**不等于当前有效或语义已核实**。搜索可能返回候选；主题读取目前可能返回整篇大文档。集成时须保留状态、日期和来源，客户端显式设置短搜索预算，不默认读取全部主题。

## 本地运行

需要 Python 3.11+；测试使用 Python 3.12。在仓库根目录运行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pipeline.memory_center
```

打开 http://127.0.0.1:5077 。本机管理入口不需要输入专用凭据，仅允许 loopback；Agent 使用独立限范围授权。不要将本机入口通过代理直接暴露公网。

默认私有数据目录是 `~/.local/share/personal-memory-center/`，位于仓库外。可通过 `QIU_MEMORY_DATA_DIR` 指定另一个私有目录。环境变量保留原兼容命名；不自动加载网站环境或本仓库的 `.env`。

模型提炼需自行设置三个变量：

- `QIU_MEMORY_LLM_BASE`：OpenAI 兼容 HTTPS API 根地址。
- `QIU_MEMORY_LLM_KEY`：私有模型密钥。
- `QIU_MEMORY_LLM_MODEL`：模型标识。

也可使用私有目录的 `model.json`，权限必须为 0600。未配置模型时仍可保存资料，提炼任务显示失败；配置并重启后手动重试。默认无自动失败重试，防止无上限消耗。

## MCP 与 Skill

```sh
QIU_MEMORY_DATA_DIR=/path/to/private-runtime \
QIU_MEMORY_ORIGIN=http://127.0.0.1:5078 \
.venv/bin/uvicorn pipeline.memory_center.service:app_factory \
  --factory --host 127.0.0.1 --port 5078 --no-access-log
```

需要私有目录中的 `grants.json`，独立创建随机 Agent token，仅把 SHA-256 摘要写入 grant。初次本地运行会生成本人管理凭据，**不要把本人凭据交给其他 Agent**。MCP 本地地址为 `http://127.0.0.1:5078/mcp/`；客户端通过 Authorization Bearer 发送自己的 token。生产接入须配置 HTTPS 反向代理与对应 Origin。

| 工具 | 用途 |
|---|---|
| `memory_search` | 限范围短检索，建议显式传 `max_chars=1600` |
| `memory_document_get` | 主题目录或正文；当前正文无分页，谨慎显式调用 |
| `memory_source_get` | 单消息原文；需额外 `source_read` |
| `memory_import` | 小批资料入队；提炼会使用模型 tokens |
| `memory_import_status` | 任务状态；入队不等于处理完成 |

客户端工作流见 [Skill](skills/personal-memory-center/SKILL.md)。尚无 OAuth 自动发现，亦不自动同步 ChatGPT 内置记忆。

## 只读审计

先审计旧数据，再决定是否重跑。审计只返回聚合信号，不调用模型、不初始化 Store、不改库：

```sh
.venv/bin/python -m pipeline.memory_center.audit \
  --sqlite /path/to/private-runtime/memory.sqlite3 \
  --owner demo-owner --scope personal
```

PostgreSQL 使用 `--postgres-env QIU_MEMORY_DSN`，DSN 由私有环境提供，避免出现在命令参数中。可加 `--sample-out /path/to/private-review/sample.json` 保存分层抽样的记录 ID 和检查信号；文件必须在仓库外，0600，且不覆盖已有文件。抽样需要人工/模型核对原话；结构信号不是质量分数，也不会自动晋升或删除记录。

## 验证

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_memory*.py' -v
node --test tests/memory-files.test.cjs
node --check assets/memory-center.js
.venv/bin/python scripts/check_public_tree.py
```

所有测试内容均为虚构；FakeModel/MeteredModel 验证业务与预算机制，不证明真实模型提炼质量。SQLite 和 MCP 协议通过本地测试；PostgreSQL 适配器本轮尚未在独立数据库重新验收。源码检查不能替代人工审阅。

独立仓库的 CI 只做验证，**不自动部署到既有个人网站，也不续跑历史提炼**。迁移方案与质量基线达标后，网站按固定版本接入。
