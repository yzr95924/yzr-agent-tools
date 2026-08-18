# AGENTS.md

> **关键**：本文件里凡 `@path/to/file` 形式的引用（如 `@MEMORY/MEMORY.md`），都用 Read 工具按需
> 读取——它们与你**当前任务**直接相关。不自动展开 `@import` 的 agent 尤须手动执行，否则漏上下文。

## 项目定位

`yzr-agent-tools` 是一个围绕 AI coding agent 的本地运维/配置工具集合——收录：

- **`model-switch`**：切换 AI coding agent(V1 主目标 Claude Code)使用的 Anthropic 兼容模型。
  直接改写 agent 的全局配置文件(Claude Code 的 `~/.claude/settings.json` 等)实现——无 daemon、
  无代理、无协议转换。用户跑 `model-switch model use <name>` 然后重启 agent 即生效。
- **`mcp-plugin-mgr`**：CLI,管理 Claude Code / OpenCode 的自定义 MCP 服务(起点 Outline wiki)。维护
  一份 `~/.config/mcp-plugin-mgr/servers.toml` 作为规范真源,driver 把它翻译进 Claude Code 的
  `~/.claude.json` 的 `mcpServers` 与 OpenCode 的 `opencode.json` 的 `mcp`(位置/字段/type 词表各异),
  只改自己那一段、其余原样保留。与 model-switch 同构(模型 vs MCP 服务)。详见 `docs/mcp-plugin-mgr-design.md`。
- **`yzr-agent-style`**：脚本,把仓内模板 `src/yzr_agent_style/templates/AGENTS.md` 以 marker 块
  形式安装/卸载到各 agent 的全局规则文件(Claude Code `~/.claude/CLAUDE.md`、OpenCode
  `~/.config/opencode/AGENTS.md`、Qoder CLI `~/.qoder/AGENTS.md`)。块外用户手写内容原样保留,
  重跑幂等;`scripts/yzr-agent-style.sh` 是薄壳(仅 `python3 -m yzr_agent_style`)。

后续按需添加新工具。每个工具独立成 CLI(或 daemon),共享同一套仓库规约(测试隔离、原子写、
未知字段透传等)。

> **文档分层**:本文件承载 agent 工作上下文(规约 / 命令 / 架构);**用户文档**(安装 /
> 快速上手 / 命令一览 / 局限性)见 `src/model_switch/README.md` 与
> `src/mcp_plugin_mgr/README.md`,根 `README.md` 仅作索引(工具表格 + 共用规约)。**设计文档**
> (`docs/<slug>-design.md` + `docs/<slug>-tasks.md`)在仓库根,新工具按此约定产出。

## 仓库规约

- **测试绝不能触碰真实的 agent 全局配置**（如 `~/.claude/settings.json`、`~/.claude.json`）。当前 Claude Code session
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
# 安装 — 每工具一个自包含脚本（wrapper + 补全 + PATH 块），不创建 venv，不调用 pip。
# 需要 Python 3.7+；Python < 3.11 时请自备 tomli（pip install --user 'tomli>=1.1'）。
# bash/fish 补全：symlink 到 XDG 补全目录 + ~/.bashrc marker block 内 source 行。
bash scripts/model-switch.sh install        # mcp-plugin-mgr 同理：scripts/mcp-plugin-mgr.sh install
# 卸载（删 wrapper + 剥该工具的 PATH marker + 删补全 symlink；不动 ~/.config/<tool>/ 下的数据）
bash scripts/model-switch.sh uninstall
# yzr-agent-style 是薄壳（无 wrapper/PATH/补全），直接跑：
bash scripts/yzr-agent-style.sh install      # 写模板到三个 agent 全局规则文件；uninstall 反向

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

# mcp-plugin-mgr —— 管理 agent 的自定义 MCP 服务(Outline 起步)
mcp-plugin-mgr init                      # 初始化 ~/.config/mcp-plugin-mgr/
mcp-plugin-mgr add outline --url ... --token ol_api_... --all-drivers   # 加服务(preset 名或显式 flag)
mcp-plugin-mgr list                      # 列已注册服务(+ 每 agent 是否已写入)
mcp-plugin-mgr remove outline --all-drivers
mcp-plugin-mgr presets                   # 列内置 preset(outline / memos / agent-html-drop)
mcp-plugin-mgr status
mcp-plugin-mgr test outline              # 探活:发 initialize 握手,诊断连不通根因(含 ddnsto middlebox)
# add/remove 还可加 --auto-allow:一并把该 MCP 的工具写进 Claude Code permissions.allow(避免 auto-mode 拦大文档)
```

## 高层结构

各工具独立成模块(`__pycache__` / `.egg-info` 等已省略):

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
├── mcp_plugin_mgr/              # CLI;管理 agent 的自定义 MCP 服务
    ├── cli.py                   argparse (init/add/list/remove/presets/status)
    ├── __main__.py              python -m mcp_plugin_mgr 入口
    ├── paths.py                 XDG 路径(config_dir / servers_file / claude_json_file / opencode_config_file / qoder_settings_file)
    ├── _compat.py               TOML loader (tomllib/tomli) + 手写 dumper(自包含副本)
    ├── store.py                 servers.toml I/O + 透传未知字段 (ServerEntry / ServerRegistry)
    ├── presets/                 内置 preset 包(每 plugin 一文件:_types/outline/memos/agent_html_drop;__init__ 聚合)
    ├── probe.py                 test 命令:MCP initialize 握手探活 + 故障分类(http middlebox / stdio)
    ├── allow.py                 --auto-allow:写 Claude Code permissions.allow(保留 env/model)
    ├── drivers/
    │   ├── base.py              McpDriver Protocol + BaseMcpDriver(通用 JSON read/list/add/remove)+ Registry
    │   ├── _atomic.py           atomic JSON write(driver 共享)
    │   ├── claude_code.py       ~/.claude.json mcpServers 适配器(http/stdio)
    │   ├── opencode.py          opencode.json mcp 适配器(remote/local;command 合并数组;environment)
    │   └── qoder_cli.py         ~/.qoder/settings.json mcpServers 适配器(http 带 type / stdio 无 type)
    └── README.md                详细用户文档

└── yzr_agent_style/             # 脚本;全局指令模板安装/卸载(install/uninstall)
    ├── cli.py                   argparse (install/uninstall)
    ├── __main__.py              python -m yzr_agent_style 入口
    ├── paths.py                 三个 agent 全局规则文件路径 + 模板路径
    ├── markers.py               marker 块渲染/追加/替换/剥除 + 原子写
    ├── templates/AGENTS.md      指令模板真源
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
  (**不用** `{env:VAR}` 占位符;密钥落盘,注意文件权限)。**`context_window` 已知时写 `limit` 块**:
  自定义 provider 不在 models.dev,OpenCode 无从得知上下文限额,须显式声明 `limit.context`;但 OpenCode
  schema 要求 `limit` 存在时 `context` 与 `output` 成对(缺 `output` 拒载整份配置),我们只追踪
  `context_window`,故 `output` 配习惯级常量(`131_072`,对齐 models.dev MiniMax-M3)。`context_window`
  未知时整块 `limit` 省略(写半截 `{limit:{context}}` 会让配置校验失败、模型不可用)。

通过 `--driver <name>` 选单个、`--all-drivers` 选全部;省略时——交互式(TTY)默认应用到全部
已注册 driver(回车即 claude-code 与 opencode 都切,符合「切模型就该到处生效」),非交互
(CI/脚本,无 TTY)回退到默认 `claude-code`,避免脚本意外写多个 agent 配置。
新 agent = 实现一个 driver 并在 `cli._ensure_default_registered()` 注册。

**Per-driver 语义——单槽 vs catalog**:`model use <name>` 把所选 driver 的配置写到
激活的模型。driver 语义由 `supports_catalog` 区分:
- `claude-code`(单槽,`supports_catalog=False`):`apply(models, active)` 只渲染 `active`,
  写 `env` 块 + 顶层 `model`。
- `opencode`(catalog,`supports_catalog=True`):`apply` = 全量 reconcile——把 `models.toml`
  全部模型镜像成 `yzr-<model_id>` 的 provider(每模型一个,`baseURL`/`apiKey` 是 provider
  级字段、不同上游不能共用一个块),`config["model"]` 只作默认指针。`sync_catalog(models)`
  在 add/remove/import 时触发,同样全量 reconcile 但保留有效默认指针(悬空则落剩余第一个 /
  无剩余删键);`create=False` 时不凭空创建不存在的 `opencode.json`。

**Catalog 变更即同步**:`model add/remove/import` 也写 agent 配置(不只 `use`),保证
`models.toml` 变更后任何 agent 配置里都不存在已删除模型的 key——opencode 靠全量 reconcile
(删 `yzr-*` 命名空间里不在 registry 的 provider,含旧版裸 `yzr`,天然迁移),claude-code 靠
`remove`/`import replace` 删到 active 时 `clear()`(清四个自有键 + 顶层 `model`,同时清
`active_main`)。`yzr-*` 命名空间归 model-switch 管,用户别在之前缀自建 provider。

### `mcp_plugin_mgr` 的形态

CLI(`mcp-plugin-mgr`),与 model-switch 同构:一份规范注册表(`~/.config/mcp-plugin-mgr/servers.toml`)
+ 每 agent 一个 driver 负责翻译。三个 driver:
- `claude-code` 写 `~/.claude.json` 的 `mcpServers`(**不是** `~/.claude/settings.json`——后者归
  model-switch;两者是不同文件)。http→`{type:http,url,headers?}`,stdio→`{type:stdio,command,args,env}`。
- `opencode` 写 `opencode.json` 的 `mcp`。词表不同:http→`{type:remote,url,enabled:true,headers?}`,
  stdio→`{type:local,command:[cmd]+args,enabled:true,environment?}`(`command` 是 cmd+args 合并的数组,
  env 字段叫 `environment`)。
- `qodercli` 写 `~/.qoder/settings.json` 的 `mcpServers`(**与 Claude Code 同键名、不同文件**;同文件还
  有 model/ui/permissions/git/security,均不动)。词表接近 Claude Code 但有差异(对齐 `qodercli mcp add`
  实测产出):http→`{url,type:"http",headers?}`,stdio→`{command,args,env?}`——**stdio 不写 `type` 字段、空 env
  省略 `env` 键**(Claude Code 则恒写 `type:"stdio"` 与 `env` 对象)。Qoder CLI 的 MCP 功能是纯客户端配置(与
  [[qodercli-driver-not-feasible]] 记的 model-switch 云转发不可行是两回事——那个针对推理上游,这个针对 MCP 服务注册)。

`BaseMcpDriver` 实现通用 read/list/add/remove(只动 `self._KEY` 那段,保留文件里其它键——Claude Code 的
userID/onboarding、OpenCode 的 provider/model/$schema、Qoder CLI 的 model/ui/permissions);子类只设 `_KEY` + `render(entry)`。V1 命令面
**增删查 + test 探活**(add/list/remove/test/presets/status),不做 enable/disable:各 agent 的 enable 语义不对称
(Claude Code 无原生 disable;OpenCode 有 `enabled` 字段;Qoder CLI 有 `qodercli mcp enable/disable` 但落盘形式又不同),V1 回避。内置 preset:`outline` + `memos` + `agent-html-drop`(均 http,需 --url/--token);
任意 http/stdio MCP 不在 preset 里也能用 flag 配。`test` 命令(`probe.py`)对**每种传输一套流程**:
http 发 `initialize` 握手按状态分类(ok/auth/404/conn/middlebox-empty),stdio spawn + 握手;专门诊断
`*.ddnsto.com` 那类反代盒(http 返空 200 → 自动探 https 变体并给修复)。**协议握手共享,根因解读 per-plugin**:
每个 preset 可选声明 `diagnose(result)` 覆盖层,`test` 在通用 probe 返回后调用它叠专属根因(outline→Settings→AI/ddnsto;
memos→Access Tokens/v0.27+/`/mcp`)。`~/.claude.json` 同时是当前 session 自己 MCP 服务所在地,测试隔离把它纳入
mtime+sha256 快照(见上「仓库规约」)。

详见 `docs/mcp-plugin-mgr-design.md`。

## 跨会话记忆（索引）

@MEMORY/MEMORY.md

## 注意事项

- V1 **不做协议转换**——只支持 Anthropic 兼容上游。OpenAI 兼容（原生 OpenAI、DeepSeek、Ollama）需
  翻译层，V1 不计划。
