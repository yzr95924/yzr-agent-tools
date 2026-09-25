# AGENTS.md

> **关键**：本文件里凡 `@path/to/file` 形式的引用（如 `@MEMORY/MEMORY.md`），都用 Read 工具按需
> 读取——它们与你**当前任务**直接相关。不自动展开 `@import` 的 agent 尤须手动执行，否则漏上下文。

## 项目定位

`yzr-agent-tools` 是一个围绕 AI coding agent 的本地运维/配置工具集合——收录：

- **`model-switch`**：切换 AI coding agent（V1 主目标 Claude Code）使用的 Anthropic 兼容模型。
  直接改写 agent 的全局配置文件（Claude Code 的 `~/.claude/settings.json` 等）实现——无 daemon、
  无代理、无协议转换。用户跑 `model-switch model use <name>` 然后重启 agent 即生效。
- **`mcp-plugin-mgr`**：CLI，管理 Claude Code / OpenCode 的自定义 MCP 服务（起点 Outline wiki）。维护
  一份 `~/.config/mcp-plugin-mgr/servers.toml` 作为规范真源，driver 把它翻译进 Claude Code 的
  `~/.claude.json` 的 `mcpServers` 与 OpenCode 的 `opencode.json` 的 `mcp`（位置/字段/type 词表各异），
  只改自己那一段、其余原样保留。与 model-switch 同构（模型 vs MCP 服务）。详见 `docs/mcp-plugin-mgr-design.md`。
- **`yzr-agent-style`**：脚本，把仓内模板 `src/yzr_agent_style/templates/AGENTS.md` 以 marker 块
  形式安装/卸载到各 agent 的全局规则文件（Claude Code `~/.claude/CLAUDE.md`、OpenCode
  `~/.config/opencode/AGENTS.md`、Qoder CLI `~/.qoder/AGENTS.md`）。块外用户手写内容原样保留，
  重跑幂等；`scripts/yzr-agent-style.sh` 是薄壳（仅 `python3 -m yzr_agent_style`）。
- **`opencode-plugins`**：CLI，管理仓内维护的个人 OpenCode 插件（源码真源
  `src/opencode_plugins/plugins/<name>/index.ts`）。`install` 把插件目录拷到
  `~/.config/opencode/plugins/<name>/` 并在全局 `opencode.json` 的 `plugins` 数组登记
  `./plugins/<name>`（OpenCode 按配置文件所在目录解析相对路径）；`sync` 改后重拷、
  `verify` 校 hash + 登记、`uninstall` 反向。状态全部从文件系统 + 配置推导，无注册表文件。
  当前唯一插件 `at-import`：OpenCode V2 不展开 AGENTS.md 的 `@path` 且 `instructions`
  字段失效，插件用 `context` hook 在每次模型请求前把 `@` 目标文件推进 system(实测
  2.0.15；安全边界=只读引用文件目录子树内相对路径，canary 行供验尸）。详见
  `docs/opencode-plugins-design.md`。

后续按需添加新工具。每个工具独立成 CLI（或 daemon），共享同一套仓库规约（测试隔离、原子写、
未知字段透传等）。

> **文档分层**：本文件承载 agent 工作上下文（规约 / 命令 / 架构）；**用户文档**(安装 /
> 快速上手 / 命令一览 / 局限性）见 `src/model_switch/README.md` 与
> `src/mcp_plugin_mgr/README.md`，根 `README.md` 仅作索引（工具表格 + 共用规约）。**设计文档**
> (`docs/<slug>-design.md` + `docs/<slug>-tasks.md`)在仓库根，新工具按此约定产出。

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
  永远不出现半写状态；每个工具内这两条路径共用该工具 `store.atomic_write_text` 这一份实现
  （两个工具各持一份，属自包含约定）。
- **API key 明文存 `models.toml` 的 `api_key` 字段**（同 `workspace_models.toml` 设计，本地信任模型）。**不引入环境变量**——`_resolve_api_key` 直接读 `m.api_key`，没有 env 查询。`model add` 用 `--api-key`（或省略时 getpass 安全交互输入）。
- **不要在 import 时副作用注册 driver**。会让 module import 那一刻创建指向 `Path.home() / ...` 的实例，
  成为测试隔离漏洞。改成 lazy：在 cli.py 第一次需要 driver 时再 `registry.register(...)`。

## 常用命令

```bash
# 安装 — 每工具一个自包含脚本（wrapper + 补全 + PATH 块），不创建 venv，不调用 pip。
# 需要 Python 3.7+；Python < 3.11 时请自备 tomli（pip install --user 'tomli>=1.1'）。
# bash/zsh/fish 补全：bash 软链到补全目录（macOS+Homebrew 时为 brew prefix 下的
# bash-completion 目录，否则 XDG）+ ~/.bashrc marker block 内 source 行；zsh 软链到
# ~/.zfunc/_<tool> + ~/.zshrc marker 块内 fpath 行 + compinit（重跑 compinit 是有意的：
# oh-my-zsh 等框架的 compinit 在我们 fpath 行之前跑过）；fish 软链到 ~/.config/fish/completions/。
bash scripts/model-switch.sh install        # mcp-plugin-mgr 同理：scripts/mcp-plugin-mgr.sh install
bash scripts/opencode-plugins.sh install    # 个人 OpenCode 插件管理器同理
# 安装完工具本身后，把 bundled 插件装进 OpenCode:
opencode-plugins install
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

# mcp-plugin-mgr —— 管理 agent 的自定义 MCP 服务（Outline 起步）
mcp-plugin-mgr init                      # 初始化 ~/.config/mcp-plugin-mgr/
mcp-plugin-mgr add outline --url ... --token ol_api_... --all-drivers   # 加服务(preset 名或显式 flag)
mcp-plugin-mgr list                      # 列已注册服务(+ 每 agent 是否已写入)
mcp-plugin-mgr remove outline --all-drivers
mcp-plugin-mgr disable outline --all-drivers   # 停用(保留凭据;enable 从注册表还原,无需重配)
mcp-plugin-mgr enable outline --all-drivers    # 恢复;STATE/DISABLED 见 `list` 的 STATE 列
mcp-plugin-mgr presets                   # 列内置 preset(outline / memos / agent-html-drop)
mcp-plugin-mgr status
mcp-plugin-mgr test outline              # 探活:发 initialize 握手,诊断连不通根因(含 ddnsto middlebox)
# add/remove 还可加 --auto-allow：一并把该 MCP 的工具写进 Claude Code permissions.allow（避免 auto-mode 拦大文档）

# opencode-plugins —— 管理仓内个人 OpenCode 插件（当前：at-import）
opencode-plugins list                    # bundled 插件 + installed/drift/missing + 登记状态(orphan 另列)
opencode-plugins install                 # 拷到 ~/.config/opencode/plugins/ + 登记 plugins 数组(幂等)
opencode-plugins sync                    # 改完仓内 TS 源码后重拷
opencode-plugins verify                  # hash + 登记完整性;升级 OpenCode 后跑一次
opencode-plugins uninstall [name]        # 摘登记 + 删目录(可点名清 orphan)
```

## 高层结构

各工具独立成模块（`__pycache__` / `.egg-info` 等已省略）：

```
src/
├── model_switch/                # CLI;无 daemon
│   ├── cli.py                   argparse (仅做编排)
│   ├── __main__.py              python -m model_switch 入口
│   ├── paths.py                 XDG 路径解析
│   ├── store.py                 TOML I/O + 透传未知字段 (ModelEntry / Registry / State)
│   ├── importer.py              llmw workspace_models.toml → models.toml 纯转换(无 I/O)
│   ├── _compat.py               TOML loader (tomllib/tomli) + 手写 dumper
│   ├── drivers/
│   │   ├── base.py              AgentDriver Protocol + Registry
│   │   ├── _atomic.py           JSON tolerant read + atomic write (driver 共享)
│   │   ├── claude_code.py       ~/.claude/settings.json 适配器
│   │   └── opencode.py          ~/.config/opencode/opencode.json 适配器
│   └── README.md                详细用户文档
│
├── mcp_plugin_mgr/              # CLI;管理 agent 的自定义 MCP 服务
    ├── cli.py                   argparse (init/add/list/remove/enable/disable/presets/status)
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

├── yzr_agent_style/             # 脚本;全局指令模板安装/卸载(install/uninstall)
    ├── cli.py                   argparse (install/uninstall)
    ├── __main__.py              python -m yzr_agent_style 入口
    ├── paths.py                 三个 agent 全局规则文件路径 + 模板路径
    ├── markers.py               marker 块渲染/追加/替换/剥除 + 原子写
    ├── templates/AGENTS.md      指令模板真源
    └── README.md                详细用户文档

└── opencode_plugins/            # CLI;管理仓内个人 OpenCode 插件(list/install/uninstall/sync/verify)
    ├── cli.py                   argparse(含隐藏 _complete plugins 供补全)
    ├── __main__.py              python -m opencode_plugins 入口
    ├── paths.py                 全局 opencode.json / plugins 目标目录 + 包内源目录
    ├── jsonutil.py              JSON tolerant read + 原子写(自包含一份)
    ├── registry.py              bundled 发现 / sha256 状态推导 / plugins 数组登记(未知键透传)
    ├── plugins/at-import/       插件源真源;index.ts 纯对象默认导出、零依赖(勿 import
    │                            @opencode/plugin——V2 server 无别名注入,实测会加载失败)
    └── README.md                详细用户文档
```

### `model_switch` 的 driver 抽象

每个 agent 一个 driver 类，实现 `read() / apply(model, api_key) / current()`。当前内置 `claude-code`
与 `opencode`:

- `claude-code` 写 `~/.claude/settings.json` 的 `env` 块（`ANTHROPIC_AUTH_TOKEN` /
  `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL`)+ 顶层 `model` 字段。
- `opencode` 写 OpenCode 全局配置 `$XDG_CONFIG_HOME/opencode/opencode.json`(默认
  `~/.config/opencode/opencode.json`,**不是** `~/.opencode.json`）的 `providers.<yzr-*>` 块
  ——**V2 原生形状**。关键细节：`package: @opencode/ai/providers/anthropic`(Anthropic 兼容
  上游必需的 runtime，否则 OpenCode 报 "Provider not found" 退回默认模型);provider 级
  `settings.baseURL` 由 driver 自动补 `/v1`(该 package 只在 baseURL 后追加 `/messages`，而
  store 里 `base_url` 不带 /v1——那正是 claude-code driver 要的形式；语义差异封装在各自
  driver);`settings.apiKey` 直接写明文 key(**不用** `{env:VAR}` 占位符；密钥落盘，注意文件
  权限）。旧版 V1 的顶层 `provider` 键**只读不写**:reconcile 会把其中 `yzr-*` 的旧块剥掉
  （剥空则删键），外来条目原样保留。**`context_window` 已知时写 `limit` 块**：自定义 provider
  不在 models.dev,OpenCode 无从得知上下文限额，须显式声明 `limit.context`；但 OpenCode
  schema 要求 `limit` 存在时 `context` 与 `output` 成对（缺 `output` 拒载整份配置），我们只追踪
  `context_window`，故 `output` 配习惯级常量（`131_072`，对齐 models.dev MiniMax-M3）。`context_window`
  未知时整块 `limit` 省略（写半截 `{limit:{context}}` 会让配置校验失败、模型不可用）。V1 的
  `reasoning`/`attachment`/`temperature` model 字段 V2 已移除（加载时忽略并告警），driver 不再
  渲染。

通过 `--driver <name>` 选单个、`--all-drivers` 选全部；省略时——交互式(TTY)默认应用到全部
已注册 driver（回车即 claude-code 与 opencode 都切，符合「切模型就该到处生效」），非交互
（CI/脚本，无 TTY）回退到默认 `claude-code`，避免脚本意外写多个 agent 配置。
新 agent = 实现一个 driver 并在 `cli._ensure_default_registered()` 注册。

**Per-driver 语义——单槽 vs catalog**:`model use <name>` 把所选 driver 的配置写到
激活的模型。driver 语义由 `supports_catalog` 区分，可选方法（`validate` / `sync_catalog` /
`clear`）由 CLI 用 `getattr` 探测：

- `claude-code`（单槽，`supports_catalog=False`）：`apply(models, active)` 只渲染 `active`,
  写 `env` 块 + 顶层 `model`。无渲染期校验，故不实现 `validate`。
- `opencode`(catalog,`supports_catalog=True`):`apply` = 全量 reconcile——把 `models.toml`
  全部模型镜像成 `yzr-<model_id>` 的 provider(每模型一个，`baseURL`/`apiKey` 是 provider
  级字段、不同上游不能共用一个块),`config["model"]` 只作默认指针。`sync_catalog(registry)`
  在 add/remove/import 时触发，同样全量 reconcile 但保留有效默认指针（悬空则落剩余第一个 /
  无剩余删键);`create=False` 时不凭空创建不存在的 `opencode.json`。渲染拆成纯计算的
  `_compose`，写入前先跑 `validate(models, active=None)`;`model use` 对**所有** driver 先
  校验、全过才开写，所以一个 driver 的渲染错误不会留下「一半 agent 已切、state 未更新」。
  校验严格对应写入：`sync_catalog` 在「没有配置文件、无需写」时直接返回、不校验（否则
  `model add` 会对 OpenCode 根本看不到的条目报错）。model 块除 `limit` 外
  还渲染 `models.toml` 的 `variants`(OpenCode 的档位，形状由用户在
  `[variants_presets.<名>]` 定义、模型用 `variants_preset` 引用）与 `modalities`
  (→ V2 的 `capabilities`,`tools` 恒 true；未声明时显式写 text-only——OpenCode 对查不到的
  provider 的回退假设包含 image 输入）。

**variant preset 的分层**：展开在 CLI 层（`model_switch.variants.expand`/`expand_model`，仅内存、
不落盘，`save_models` 永远拿原始 Registry),driver 与 store 都不认识 preset——driver 只看到
`variants` 一个键。展开时顺带检查容器形状（preset 与内联的档位值必须是表；标量会渲染成坏条目），
payload 内容不校验。`variants.py` 与 `drivers/opencode.py`
的代码里不得出现模型/网关名（档位是数据不是特判；`test_variants.py` 有 AST 守卫）。

**档位渲染是 V2 数组**:`drivers/opencode.py` 把 `variants` 表转成
`[{"id": <档名>, "settings": <payload>}, ...]`,**声明顺序即数组顺序 = ctrl+t 循环顺序**;
payload 原样进 `settings`，由 OpenCode 的 provider package 翻进请求（实测：`settings.effort`
→ `output_config.effort`,`settings.thinking` → 请求 body 的 `thinking`）。OpenCode V2 对自建
provider **不计算家族内置档位**，所以声明即全集，没有静音/深合并机制（V1 时代的
`_INJECTABLE_TIER_NAMES` 与 `{disabled:true}` 静音已随迁移删除）；未声明 `variants` 的模型
渲染不出档位，`ctrl+t` 只有未选档 Default（走 provider 基线，kimi 基线即 `effort = "high"`）。
`model show` 的 variants 行列的就是声明的档位（顺序即循环顺序），未声明时打印 `<none declared>`。

**catalog 只供参数、档位与模态**:`model add` 向导与 `model align` 能从 catalog 推导的只有
`context_window` / `variants` / `modalities` / `display_name`（`catalog.derive` 的全部产出）。
档位推导跟 OpenCode 自己的规则一致：effort 值每值一档、`toggle` 不造档（OpenCode 的
`reasoningVariants` 在有 effort 时同样丢弃它）、`none` 翻成 `{thinking:{type:"disabled"}}`
（Anthropic 的 effort 枚举没有 `none`；该形状即 Kimi 文档对 `none` 的定义，实测有效）、
`minimal` 跳过。`display_name` 渲染成 model 块的 `name`(纯选择器标签，key 与上游 id 仍是
upstream id），与 id 相同则不写。`context_window` 按模型/套餐上限取 catalog 值（kimi `k3` = 1M，需
Pro/Allegretto+，超出套餐服务端 401）。
**一致性口径**：对齐对象是 models.dev 官方 provider 条目；有意/结构性差异：`none`/`minimal`
有意偏离、`interleaved` 不写（anthropic 路径由 `anthropic-beta` 头覆盖）、
`cost`/`family`/`release_date` 不写（纯显示）、`structured_output`
写不了（schema 无此字段）。
`name`(upstream id)、`base_url`、`api_key` 是模型提供商的约定，同一个模型在不同 provider
下拼法不同（缓存里 `GLM-5.2` 有 21 种拼法），**任何路径都不得从 catalog 推断 id**：向导选中后
把 id 预填成该行的拼法但显式问一次（`_prompt_upstream_id`，可改、首尾空白 strip），脚本侧
则是 `--model-name`。id 会原样进 `ANTHROPIC_MODEL` 与 OpenCode 的 model 指针，推断错的表现
是每次请求都 model not found。`model align` 只更新那几类参数、从不碰 id。

**Catalog 变更即同步**:`model add/remove/import` 也写 agent 配置（不只 `use`），保证
`models.toml` 变更后任何 agent 配置里都不存在已删除模型的 key——opencode 靠全量 reconcile
（删 `yzr-*` 命名空间里不在 registry 的 provider，含旧版裸 `yzr`，天然迁移），claude-code 靠
`remove`/`import replace` 删到 active 时 `clear()`(清四个自有键 + 顶层 `model`，同时清
`active_main`）。`yzr-*` 命名空间归 model-switch 管，用户别在之前缀自建 provider。

**Provider 分组规则单一真源**：分组键 `(声明名, base_url, api_key)` 由 `store.provider_group_key`
定义（`upstream_key` 给出其中 `(base_url, api_key)` 半边），OpenCode driver 渲染 `yzr-*` 块与 CLI
的 `model add` 继承组名都走它——改规则只改这一处，否则两边会漂移成「继承了一个不再合并的名字」。
`model add` 在**已存在同上游同 key 且声明了 provider 的模型**时提示继承（回车继承；`-` 表示不
声明，并在本地名确定后打印 note——排除掉本次要覆盖的条目，避免把即将消失的声明说成还在）。
非 TTY 同样继承（`_prompt` 非 TTY 取默认值），所以脚本路径不会裂出 `yzr-<host>-2`。

### `mcp_plugin_mgr` 的形态

CLI(`mcp-plugin-mgr`)，与 model-switch 同构：一份规范注册表(`~/.config/mcp-plugin-mgr/servers.toml`)+ 每 agent 一个 driver 负责翻译。三个 driver:

- `claude-code` 写 `~/.claude.json` 的 `mcpServers`(**不是** `~/.claude/settings.json`——后者归
  model-switch；两者是不同文件）。http→`{type:http,url,headers?}`,stdio→`{type:stdio,command,args,env}`。
- `opencode` 写 `opencode.json` 的 `mcp`。词表不同：http→`{type:remote,url,enabled:true,headers?}`,
  stdio→`{type:local,command:[cmd]+args,enabled:true,environment?}`(`command` 是 cmd+args 合并的数组，
  env 字段叫 `environment`）。
- `qodercli` 写 `~/.qoder/settings.json` 的 `mcpServers`(**与 Claude Code 同键名、不同文件**；同文件还
  有 model/ui/permissions/git/security，均不动）。词表接近 Claude Code 但有差异（对齐 `qodercli mcp add`
  实测产出):http→`{url,type:"http",headers?}`,stdio→`{command,args,env?}`——**stdio 不写 `type` 字段、空 env
  省略 `env` 键**（Claude Code 则恒写 `type:"stdio"` 与 `env` 对象）。Qoder CLI 的 MCP 功能是纯客户端配置（与
  [[qodercli-driver-not-feasible]] 记的 model-switch 云转发不可行是两回事——那个针对推理上游，这个针对 MCP 服务注册）。

`BaseMcpDriver` 实现通用 read/list/add/remove/set_enabled(只动 `self._KEY` 那段，保留文件里其它键——Claude Code 的
userID/onboarding、OpenCode 的 provider/model/$schema、Qoder CLI 的 model/ui/permissions）；子类只设 `_KEY` + `render(entry)`（有原生启停 flag 的再加 `native_disable=True` + `_flag_mutation` + `flag_state`）。V2 命令面
**增删查 + 启停 + test 探活**(init/add/list/remove/enable/disable/test/presets/status)。启停统一为「registry 记 `enabled`（缺省 true,false 才落盘）+ driver 翻译」:
OpenCode 翻 `enabled` 原地、Qoder CLI 加/删 `disabled` 原地（均 `native_disable=True`，外来键全保），Claude Code 无全局 flag
故**删条目**（registry 留全量 → `enable` 无需重配）；写前对无原生 flag 的 driver 做 drift 比对，列出 `+仅 agent 侧有`/`~值不同` 并**警告不阻断**。
`add` 固定为「显式启用」（`--force` 覆盖时 `enabled` 复位 true）。不做 per-project 停用与 sync 全量重投影。内置 preset:`outline` + `memos` + `agent-html-drop`（均 http，需 --url/--token）；
任意 http/stdio MCP 不在 preset 里也能用 flag 配。`test` 命令(`probe.py`)对**每种传输一套流程**:
http 发 `initialize` 握手按状态分类(ok/auth/404/conn/middlebox-empty),stdio spawn + 握手；专门诊断
`*.ddnsto.com` 那类反代盒（http 返空 200 → 自动探 https 变体并给修复）。**协议握手共享，根因解读 per-plugin**:
每个 preset 可选声明 `diagnose(result)` 覆盖层，`test` 在通用 probe 返回后调用它叠专属根因（outline→Settings→AI/ddnsto;
memos→Access Tokens/v0.27+/`/mcp`）。`~/.claude.json` 同时是当前 session 自己 MCP 服务所在地，测试隔离把它纳入
mtime+sha256 快照（见上「仓库规约」）。

详见 `docs/mcp-plugin-mgr-design.md`。

## 跨会话记忆（索引）

@MEMORY/MEMORY.md

## 注意事项

- V1 **不做协议转换**——只支持 Anthropic 兼容上游。OpenAI 兼容（原生 OpenAI、DeepSeek、Ollama）需
  翻译层，V1 不计划。
