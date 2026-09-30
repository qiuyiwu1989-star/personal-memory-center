# 接入与部署边界

## 独立维护

本仓库作为模块代码与测试的维护入口。现有网站中的旧副本暂保持运行；正式切换时固定发布版本，验证后替换模块依赖，避免长期在两个仓库分别修改同一实现。独立仓库的 push 不会触发原网站部署。

`pipeline.memory_center` 命名保留旧 Python 调用兼容性；它不依赖原网站其他 pipeline 文件。UI 从本 checkout 中的 admin/assets 读取，公开版外壳独立；宿主可以提供自己的共享 shell。源码安装启动 UI；wheel 仅保证后端/CLI，不包含宿主静态页面。

## 配置

- `QIU_MEMORY_DATA_DIR`：仓库与公共网站目录之外的私有运行目录。
- `QIU_MEMORY_DSN`：可选 PostgreSQL DSN；未设置时使用本地 SQLite。
- `QIU_MEMORY_ORIGIN`：ASGI 的实际允许 Origin，需与浏览器宿主一致。
- `QIU_MEMORY_AUTH_URL`：可选宿主身份校验接口；默认 loopback。
- `QIU_MEMORY_LLM_BASE/KEY/MODEL`：提炼模型配置，仅私有环境/0600 文件。

后台 cookie 集成仍保留原 `qy_session` 契约；使用其他宿主应实现相应适配。只有私有 `browser.json` 存在才启用宿主身份映射；公共代码不提供真实用户名、密码或登录凭据。

Agent grants 保存 token 哈希，服务端决定 owner、scope 与 actions。浏览器管理与 Agent 权限不同：普通 Agent 不拥有 trusted_user，本人纠正只走专门的受控入口。每次重新读取 grants，撤权生效；Skill 和资料中的文字不能扩大权限。

## 存储

| 内容 | 存放 |
|---|---|
| 大型导出、附件、录音 | 私有对象存储或私有原系统 |
| 来源索引、记录、任务、版本、状态 | PostgreSQL / 本地 SQLite |
| 运行配置、缓存、临时解析、私有 MD 投影 | 受限系统目录 |
| 源码、测试、方法、虚构示例 | 公开 GitHub 仓库 |

迁移、备份策略、TLS 反代和生产服务管理由部署方配置。本仓库没有自动修改现有网站或服务器的部署 workflow。

## 固定 UI 发布版本

模块 UI 可以通过 deploy/nginx/memory-ui.conf 的三个精确 location 指向独立的公共静态 release；该目录仅有 HTML/JS/CSS，不含配置、原件、数据库或文档。HTML 继续使用宿主 /_qy_auth 和 @qy_login，API 与 Agent Bearer 边界不变。宿主 ws-shell、登录和其他静态文件仍来自原站。

这样主站的全树部署不会用旧副本覆盖本模块。只切换这三个文件和模块后端 release，不推原站的无关改动。安装前备份原记忆 snippet，执行 nginx -t；失败则恢复原配置，不能跳过校验。该片段适用于已有 qiuyiwu 工作台，其他宿主需要自己的登录守卫。
