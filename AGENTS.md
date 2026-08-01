# AGENTS.md

> **关键**：本文件里凡 `@path/to/file` 形式的引用（如 `@MEMORY/MEMORY.md`），都用 Read 工具按需
> 读取——它们与你**当前任务**直接相关。不自动展开 `@import` 的 agent 尤须手动执行，否则漏上下文。

## 项目定位

`yzr-agent-tools` 是一个围绕 AI coding agent 的本地运维/配置工具集合——收录：

- **`model-switch`**：切换 AI coding agent(V1 主目标 Claude Code)使用的 Anthropic 兼容模型。
  直接改写 agent 的全局配置文件(Claude Code 的 `~/.claude/settings.json` 等)实现——无 daemon、
  无代理、无协议转换。用户跑 `model-switch model use <name>` 然后重启 agent 即生效。
- **`html-mcp`**：常驻 HTTP daemon,让 agent(本机 Claude Code / OpenCode)通过 MCP(Streamable HTTP)
  把 `yzr-md-to-html` 等产出的自包含 HTML 推到远端 nginx server,同时提供一个浏览器管理页
  (列表 / 预览 / 删除 / 复制公开 URL)。详见 `docs/html-mcp-design.md`。

后续按需添加新工具。每个工具独立成 CLI(或 daemon),共享同一套仓库规约(测试隔离、原子写、
未知字段透传等)。

> **文档分层**:本文件承载 agent 工作上下文(规约 / 命令 / 架构);**用户文档**(安装 /
> 快速上手 / 命令一览 / 局限性)见 `src/model_switch/README.md` 与
> `src/html_mcp/README.md`,根 `README.md` 仅作索引(工具表格 + 共用规约)。**设计文档**
> (`docs/<slug>-design.md` + `docs/<slug>-tasks.md`)在仓库根,新工具按此约定产出。

## 仓库规约

- **测试绝不能触碰真实的 agent 全局配置**（如 `~/.claude/settings.json`）。当前 Claude Code session
  用的就是真配置；任何 driver bug 都会让 session 立刻 API error 报。`tests/conftest.py` 的 autouse fixture
  强制：snapshot 真实配置的 mtime + sha256，重定向 `paths.*` 到 tmp，替换 registry driver 指向 tmp，
  测试结束后断言真配置字节完全一致。详细 [[test-isolation-invariants]]。
- **Python 3.7+ 兼容**。pyproject 固定 `tomli>=1.1`（<3.11 时）。CLI 用 stdlib `argparse`，
  无第三方运行时依赖。禁 `dict[str, str]` 语法、walrus、`match`；用 `from typing import Dict, List, Optional`。
- **driver 必须保留未知字段**。`ClaudeCodeDriver.apply()` 读全 JSON、只改 `env` 块、回写——用户的
  theme、plugins、自定义 env 都不能丢。
- **原子写文件**。TOML（`store.py`）和 JSON（driver）都先写 `.tmp` 再 `os.replace()`，
  永远不出现半写状态。
- **API key 明文存 `models.toml` 的 `api_key` 字段**（同 `workspace_models.toml` 设计，本地信任模型）。**不引入环境变量**——`_resolve_api_key` 直接读 `m.api_key`，没有 env 查询。`model add` 用 `--api-key`（或省略时 getpass 安全交互输入）。
- **不要在 import 时副作用注册 driver**。会让 module import 那一刻创建指向 `Path.home() / ...` 的实例，
  成为测试隔离漏洞。改成 lazy：在 cli.py 第一次需要 driver 时再 `registry.register(...)`。

## 常用命令

```bash
# 安装 — 走 shell wrapper + PYTHONPATH 路线（不创建 venv，不调用 pip）。
# 需要 Python 3.7+；Python < 3.11 时请自备 tomli（pip install --user 'tomli>=1.1'）。
# 同时安装 bash/fish 补全：symlink 到 XDG 补全目录 + ~/.bashrc marker block 内 source 行。
bash scripts/install.sh
# 卸载（删 wrapper + 剥 PATH marker + 删补全 symlink；不动 ~/.config/model-switch/ 下的数据）
bash scripts/uninstall.sh

# 测试 — 需要 pytest + pytest-cov 自装（pip install --user pytest pytest-cov）。
# pyproject.toml 的 [tool.pytest.ini_options].pythonpath 已含 src/，
# 不需要 `pip install -e .` 也能 import model_switch。
pytest
pytest tests/test_cli.py -v                   # 单文件
pytest tests/test_cli.py::test_model_use_*    # 单测匹配
pytest --cov=model_switch                     # 带覆盖率

# CLI 自身
model-switch model list
model-switch model add glm-z1 --base-url ... --api-key <KEY> --model-name glm-4
model-switch model use glm-z1            # 交互式默认切全部 agent;加 --driver <name> 只切单个
model-switch status

# html-mcp —— 常驻 daemon (远端 nginx server 跑)
html-mcp init                            # 初始化 ~/.config/html-mcp/,生成 bearer token
html-mcp serve                           # 前台启动 (Ctrl+C 停);生产建议 tmux / systemd 用户单元
html-mcp token show                      # 打印 token,配到 agent MCP config
html-mcp nginx-config                    # 打印 nginx server block 到 stdout
html-mcp nginx-config --write            # 写到 ~/.config/html-mcp/nginx.conf.example
html-mcp status                          # config / token / docroot 状态
```

## 高层结构

两个工具并存,各自独立成模块(`__pycache__` / `.egg-info` 等已省略):

```
src/
├── model_switch/                # CLI;无 daemon
│   ├── cli.py                   argparse (仅做编排)
│   ├── __main__.py              python -m model_switch 入口
│   ├── paths.py                 XDG 路径解析
│   ├── store.py                 TOML I/O + 透传未知字段 (ModelEntry / Registry / State)
│   ├── importer.py              llmw workspace_models.toml → models.toml 纯转换(无 I/O)
│   ├── _compat.py               TOML loader (tomllib/tomli)
│   ├── drivers/
│   │   ├── base.py              AgentDriver Protocol + Registry
│   │   ├── _atomic.py           atomic JSON write (driver 共享)
│   │   ├── claude_code.py       ~/.claude/settings.json 适配器
│   │   └── opencode.py          ~/.config/opencode/opencode.json 适配器
│   └── README.md                详细用户文档
│
└── html_mcp/                    # 常驻 daemon
    ├── cli.py                   argparse (init / serve / token / config / nginx-config / status)
    ├── __main__.py              python -m html_mcp 入口
    ├── _version.py              VERSION 字符串 (/api/health + CLI --version)
    ├── paths.py                 XDG 路径解析
    ├── config.py                TOML I/O + 透传未知字段 + validate_for_serve
    ├── auth.py                  Bearer token 常量时间比较 + redact_token
    ├── storage.py               docroot 文件 CRUD (atomic write / 命名 regex / 路径穿越防护)
    ├── server.py                http.server.ThreadingHTTPServer + 路由 + body 限流
    ├── mcp_handler.py           JSON-RPC Streamable HTTP + 4 个 tool
    ├── api.py                   /api/files /api/nginx-config /api/health
    ├── nginx_config.py          assets/nginx.conf.template 渲染
    ├── ui.py                    ui/{index.html,style.css,app.js} 静态路由
    ├── _compat.py               TOML loader (tomllib/tomli)
    ├── assets/
    │   └── nginx.conf.template  nginx server block 模板
    ├── ui/                      管理页静态资源 (vanilla JS)
    │   ├── index.html
    │   ├── style.css
    │   └── app.js
    └── README.md                详细用户文档
```

### `model_switch` 的 driver 抽象

每个 agent 一个 driver 类,实现 `read() / apply(model, api_key) / current()`。当前内置 `claude-code`
与 `opencode`:
- `claude-code` 写 `~/.claude/settings.json` 的 `env` 块(`ANTHROPIC_AUTH_TOKEN` /
  `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL`)+ 顶层 `model` 字段。
- `opencode` 写 OpenCode 全局配置 `$XDG_CONFIG_HOME/opencode/opencode.json`(默认
  `~/.config/opencode/opencode.json`,**不是** `~/.opencode.json`)的 `provider.yzr` 块。
  关键细节:`npm: @ai-sdk/anthropic`(Anthropic 兼容上游必需的 adapter,否则 OpenCode 报
  "Provider not found" 退回默认模型);`options.baseURL` 由 driver 自动补 `/v1`
  (`@ai-sdk/anthropic` 只在 baseURL 后追加 `/messages`,而 store 里 `base_url` 不带 /v1——那正是
  claude-code driver 要的形式;语义差异封装在各自 driver);`options.apiKey` 直接写明文 key
  (**不用** `{env:VAR}` 占位符;密钥落盘,注意文件权限)。**故意不写 `limit`**:OpenCode schema
  要求 `limit` 存在时必须有 `limit.output`,而我们只追踪 `context_window`,写半截
  `{limit:{context}}` 会让整份配置校验失败、模型不可用。

通过 `--driver <name>` 选单个、`--all-drivers` 选全部;省略时——交互式(TTY)默认应用到全部
已注册 driver(回车即 claude-code 与 opencode 都切,符合「切模型就该到处生效」),非交互
(CI/脚本,无 TTY)回退到默认 `claude-code`,避免脚本意外写多个 agent 配置。
新 agent = 实现一个 driver 并在 `cli._ensure_default_registered()` 注册。

**单模型槽**:`model use <name>` 写一个模型到所选 agent 配置。driver 负责把 model 渲染成对应
agent 协议的字段。

### `html_mcp` 的形态

常驻 HTTP daemon(`html-mcp serve`),监听 `127.0.0.1:8765`(默认),由 nginx 在前面 HTTPS 反代
+ 终结 TLS。同一进程暴露 4 类入口:
- `POST /mcp` —— MCP Streamable HTTP(agent 走这里,`Authorization: Bearer <token>` 强制)
- `GET /` —— HTML 管理页(浏览器,粘贴 token 到 localStorage)
- `* /api/*` —— JSON API(管理页背后)
- `/files/*` —— nginx 直接从 docroot 读取(daemon 不参与)

工具表(`tools/call`)共 4 个:`upload_html` / `list_html` / `delete_html` / `get_public_url`。
MCP 协议自实现约 150 行 JSON-RPC,无第三方 SDK 依赖。

详见 `docs/html-mcp-design.md` / `docs/html-mcp-tasks.md`。

## 跨会话记忆（索引）

@MEMORY/MEMORY.md

## 注意事项

- V1 **不做协议转换**——只支持 Anthropic 兼容上游。OpenAI 兼容（原生 OpenAI、DeepSeek、Ollama）需
  翻译层，V1 不计划。
