# mcp-plugin-mgr 设计

> 状态:V2(增删查 + 启停 + test 探活)。配套任务书 `docs/mcp-plugin-mgr-tasks.md`(如需)可后续补;本文档与代码同源。

## 1. 定位

`mcp-plugin-mgr` 是 `yzr-agent-tools` 的第三个工具,与 `model-switch` 同构:**一个统一概念
(MCP 服务),多个 agent(Claude Code / OpenCode),每个 agent 一个 driver 负责把规范定义翻译成
该 agent 的字段、位置与词表**。model-switch 管的是「模型」,本工具管的是「MCP 服务」,起点是
Outline wiki。

要解决的具体不一致:

| | Claude Code | OpenCode | Qoder CLI |
| --- | --- | --- | --- |
| 文件 | `~/.claude.json` | `$XDG/opencode/opencode.json` | `~/.qoder/settings.json` |
| 键 | `mcpServers` | `mcp` | `mcpServers` |
| http type | `http` | `remote` | `http` |
| stdio type | `stdio` | `local` | (不写) |
| stdio 命令 | `command`(str) + `args`(list) 分开 | `command`(list,cmd+args 合并) | `command` + `args` 分开 |
| env 字段 | `env` | `environment` | `env` |
| 启停 | 无原生 flag:在/不在 map 里 | 显式 `enabled` 字段 | 显式 `disabled` 字段 |

且这两个文件都还承载别的关键状态(Claude Code 的 onboarding/projects/telemetry;OpenCode 的
`provider`/`model`/`$schema`),driver 必须**只改自己那一段,其余原样保留**。

## 2. 架构

```
src/mcp_plugin_mgr/
├── cli.py               argparse(init/add/list/remove/enable/disable/test/presets/status + --auto-allow/_complete),lazy 注册 driver
├── __main__.py          python -m 入口
├── paths.py             XDG: config_dir / servers_file / claude_json_file / opencode_config_file
├── _compat.py           TOML loader(tomllib/tomli)+ 手写 dumper(自包含副本)
├── store.py             ServerEntry + ServerRegistry;servers.toml I/O + 未知字段透传 + 校验
├── presets/             内置 preset(每 plugin 一文件:_types.py + outline.py + memos.py + agent_html_drop.py;__init__ 聚合 PRESETS)
├── probe.py             test 命令:MCP initialize 握手探活 + 故障分类(http middlebox / stdio)
├── allow.py             --auto-allow:写 Claude Code permissions.allow(只动 permissions 键,保留 env/model)
├── drivers/
│   ├── base.py          McpDriver Protocol + BaseMcpDriver(通用 read/list/add/remove/set_enabled)+ DriverRegistry
│   ├── _atomic.py       atomic_write_json(自包含副本)
│   ├── claude_code.py   ~/.claude.json -> mcpServers(无原生 flag,disable=删条目)
│   ├── opencode.py      opencode.json -> mcp(native_disable: enabled 原地翻)
│   └── qoder_cli.py     ~/.qoder/settings.json -> mcpServers(native_disable: disabled 原地加/删)
└── README.md            用户文档
```

**翻译表**(driver 的核心职责,代码即此表的真源):

| 规范(ServerEntry) | Claude Code `mcpServers` | OpenCode `mcp` | Qoder CLI `mcpServers` |
| --- | --- | --- | --- |
| `transport=http`, url, headers | `{type:http, url, headers?}` | `{type:remote, url, enabled:true, headers?}` | `{url, type:http, headers?}` |
| `transport=stdio`, command, args[], env{} | `{type:stdio, command, args, env}` | `{type:local, command:[cmd]+args, enabled:true, environment?}` | `{command, args, env?}`(无 `type`) |
| `enabled=false` | 删掉该键(无原生 flag) | `enabled:false` 原地翻 | `disabled:true` 原地加 |
| `enabled=true` | 用 registry 重渲染写回 | `enabled:true` 原地翻 | `disabled` 键删掉 |

启停的**控制流在 base**(`set_enabled`:先查 `native_disable`,再摆 `flagged`/`absent`/`written`
三态;`_update_server` 只在 flag 真变时落盘),**词表在 driver**(`_flag_mutation` 返回 mutate 闭包:
OpenCode 翻 `enabled`,Qoder CLI 加/删 `disabled`——后者 1.1.21 实测对齐 `qodercli mcp disable/enable`
的产出)。Claude Code 无原生 flag(其 `/mcp` 面板的停用是按项目写 `disabledMcpServers`),故删条目;
只有它需要在写前做 drift 比对(`_drift_report`:列出 `+ 仅 agent 侧有` / `~ 值不同`,容器值不打印
以免回显 token,非阻断)。

`BaseMcpDriver` 实现通用的 read/list/has/add/remove/set_enabled(只动 `self._KEY` 那段,保留其它键);子类只
设 `name` / `_KEY` / 默认 `config_path`,并实现 `render(entry)`(有原生启停 flag 的再加
`native_disable = True` + `_flag_mutation` + `flag_state`)。与 model-switch 不同:model-switch
的 `apply()` 每个 driver 差异大,所以各自独立;这里的增删查与启停控制流对三个 agent 完全一致,
故抽出共享基类,只在词表(render / flag)上分叉。

## 3. 数据模型

规范形式存在 `~/.config/mcp-plugin-mgr/servers.toml`(单一真源):

```toml
[servers.<name>]
transport = "http" | "stdio"
enabled = false            # 仅停用时出现;缺省(true)不落盘
# http
url = "..."
[servers.<name>.headers]
Authorization = "Bearer ..."
# stdio
command = "..."
args = ["..."]
[servers.<name>.env]
KEY = "VALUE"
description = "..."
```

未知顶层键 → `ServerRegistry.extra_top`;未知每服务键 → `ServerEntry.extra`;落盘原样回写
(与 model-switch/store.py 同纪律)。`transport` / http 的 `url` / stdio 的 `command` 在 load 与
显式 `validate()` 时强校验。

**preset**:`presets/` 包,每 plugin 一个文件(`outline.py` / `memos.py` / `agent_html_drop.py`),`__init__` 聚合成 `PRESETS`(按 `preset.name`
作 key,键名与 name 不漂移)。每个是部分填充的模板:V1 有 `outline` + `memos` + `agent-html-drop`(均 http),各留 `url`+`token` 两个洞
(`--url`/`--token` 或 TTY 交互补齐),把 token 套进 `Authorization: Bearer {token}`;`--header` 叠加在 preset 头之上并
覆盖同名键。outline 自带 `allow_tools`(15 个工具名)、`agent-html-drop` 自带 `allow_tools`(6 个,含写大 HTML 的 `upload_html`),
供 `--auto-allow` 用。任意 http/stdio MCP 不在 preset 里也能用 flag 配。
加一个 preset = 新建一个 plugin 文件 + `__init__` 加一行 import。

## 4. 选 agent 的 UX

完全复用 model-switch `model use` 的 `_resolve_drivers`:`--all-drivers` → 全部;`--driver NAME`
→ 单个;有 TTY 省略 → 交互(回车=全部);无 TTY 省略 → 默认 `claude-code`(避免脚本意外改多 agent)。

## 5. 测试隔离(关键)

本 session 自己的 outline 等 MCP 就在真实 `~/.claude.json` 的 `mcpServers` 里——driver bug
会让 session 立刻失效。`tests/conftest.py` 的 autouse fixture 已扩展:

- 把真实 `~/.claude.json`、`~/.config/mcp-plugin-mgr/`、`~/.config/opencode/opencode.json` 一起
  纳入 mtime+sha256 快照,teardown 断言字节级一致。
- 把 `mcp_plugin_mgr.paths.*` 重定向到 tmp;并用 tmp 路径的 driver **预注册**进 registry,
  使 `cli._ensure_default_registered()` 的 lazy 注册变成 no-op(否则它会构造指向真实 `~/.claude.json`
  的 driver)。
- `opencode.json` 的 tmp 路径与 model-switch 共用:model-switch 写 `provider`/`model`,本工具写 `mcp`,
  键不冲突。

## 6. 范围 / 取舍

- **增删查 + 启停 + test 探活**:`init/add/list/remove/enable/disable/presets/status/test`。
  V1 曾回避 enable/disable(各 agent 语义不对称),V2 统一为「registry 记 `enabled`(缺省 true,
  false 才落盘)+ driver 翻译」:
  - OpenCode:`enabled` 原地翻(实测 `opencode mcp` 无 enable/disable 子命令,只能改配置);
  - Qoder CLI:`disabled` 原地加/删(1.1.21 实测 `qodercli mcp disable/enable` 的落盘形式,逐字节对齐);
  - Claude Code:无全局 flag(`/mcp` 面板的停用是按项目写 `disabledMcpServers`),故删条目;
    registry 留全量 → `enable` 无需重配。启用前做 **drift 比对**(live vs `render(entry)`),
    列出 `+仅 agent 侧有` / `~值不同` 并**警告但不阻断**(退出码仍 0)——agent 侧手加字段无法从
    registry 还原,这点在警告里明说。
  - 不做 per-project 停用(`--scope project` 之类)与 `sync` 全量重投影;`add` 语义固定为
    「显式启用」(`--force` 覆盖时 `enabled` 复位 true)。
- **明文 token**:同 model-switch 本地信任模型;注意 `servers.toml` 与 agent 配置文件权限。
- **install/uninstall**:`TOOLS` 数组各加一行;wrapper / 补全 symlink 逻辑通用,无需改。

## 7. 探活(`test` / `probe.py`)

`add` 只保证配置写盘,不保证端点能用。`test` 真发一次 MCP `initialize` 握手并分类结果——
**每种传输一套基本流程**(`probe_http` / `probe_stdio`),可注入 `poster`/`spawner` 离线测全部分类。

- **http**(`probe_http`):POST JSON-RPC `initialize`,按状态/响应体分类:
  `ok` / `auth`(401/403)/ `waf_blocked`(403 且响应体带边缘 WAF 特征,如 Cloudflare
  Error 1010 —— 与鉴权无关,别误导用户换 token)/ `notfound`(404)/ `method`(405)/ `conn`(DNS/拒绝/超时/TLS)/
  `not_mcp`(200 但非 JSON-RPC)/ `mcp_error`(端点会 MCP 但返 error)。
- **stdio**(`probe_stdio`):`Popen` + `communicate(initialize, timeout)`,分类
  `ok` / `no_command` / `no_response`(超时)/ `not_mcp` / `spawn_error`。
- **ddnsto middlebox 诊断**:`http://` 端点返 `200` 空响应(`Content-Length: 0`,所有路径都返占位)
  → 判为 `middlebox_empty`,**自动再探 HTTPS 变体**:`https` 通 → `middlebox_https_works` + 给出
  「改成 https://…」修复;`https` 也不通 → `middlebox_empty` + 反代排查建议。已是 https 却空响应则
  指向上游(MCP 未启用 / 路径错)。覆盖 `yzr-outline-wiki-setup` 踩过的 `*.ddnsto.com` 场景。
- 只读、不写 agent 配置;退出码 0/1,可脚本化。
- **per-plugin 诊断覆盖层**:协议握手共享,但根因解读 per-plugin——每个 preset 可选声明 `diagnose(result)`
  钩子,`test` 在通用 probe 返回后调用它,为该服务叠专属根因/修复(outline→Settings→AI / ddnsto 反代;
  memos→Access Tokens / v0.27+ / `/mcp` 路径;agent-html-drop→`token show` / daemon 存活 / nginx 转发 `/mcp`)。非 preset / ad-hoc `--url` 无覆盖层,只用通用结论。

## 8. 权限预批(`--auto-allow` / `allow.py`)

Claude Code auto-mode classifier 对「已批准 + 新内容改写」保守,outline 这类高写 + 大内容(≥3000 字符)
会偶发 false-positive 拦截。`add <name> --auto-allow` 在写完 MCP 配置后,把该服务的工具名合并进
`~/.claude/settings.json#permissions.allow`,分类器即跳过二次判断。`remove <name> --auto-allow` 反向清理。

- 条目来源:preset 自带 `allow_tools`(outline 实测的 15 个;agent-html-drop 6 个,含写大 HTML 的 `upload_html`)→ 否则回退 server 级通配 `mcp__<name>`。
- 写入用 `allow.py`:`add_allowed_tools` / `remove_allowed_tools`,**只动 `permissions` 键**,保留 `env`/`model`/`theme`
  (model-switch 的键)——同 opencode.json 那样按 key 分权共享 `settings.json`。原子写 + 合并去重。
- 与 model-switch 共享 `~/.claude/settings.json`:两者各管不同键、保留其余,顺序执行不丢字段(单用户 CLI 无并发)。
- opt-in(默认关);`--no-apply` 时跳过(不碰 registry 以外的任何东西)。Claude Code 权限层专属,OpenCode 无此机制。
