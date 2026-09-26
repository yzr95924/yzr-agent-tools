# mcp-plugin-mgr

管理 Claude Code / OpenCode / Qoder CLI 的自定义 MCP 服务（以 **Outline wiki** 为起点）。把你在本地注册的
MCP 服务翻译成各 agent 自己的协议写进各自配置，重启 agent 即生效。

和 [`model-switch`](../model_switch/README.md) 同构：**一个工具，多个 agent**，每个 agent 一个
driver 负责把统一的「服务定义」渲染成该 agent 的字段与位置。

## 它解决什么

- Claude Code 的 MCP 服务在 `~/.claude.json` 的 `mcpServers`;OpenCode 的在
  `~/.config/opencode/opencode.json` 的 `mcp.servers`(V2 原生位置；V1 直接挂 `mcp` 下的
  旧条目在下次对该服务做操作时按名自动回收);Qoder CLI 的在 `~/.qoder/settings.json` 的
  `mcpServers`（与 Claude Code 同键名、不同文件）。**位置不同、字段名不同、type 词表不同**
  (Claude Code: `http`/`stdio`;OpenCode: `remote`/`local`，且 `command` 是 cmd+args 合并的
  数组，env 字段叫 `environment`;Qoder CLI: 接近 Claude Code，但 stdio **不写 `type` 字段**、
  空 env 省略 `env` 键——对齐 `qodercli mcp add` 的产出）。
- 手改三个文件、三套写法、还要保留下沉在同一个文件里的其它字段（Claude Code 的 onboarding /
  projects、OpenCode 的 provider/model、Qoder CLI 的 model/ui/permissions)——容易出错。
- 本工具：你只维护一份 `~/.config/mcp-plugin-mgr/servers.toml`,driver 负责翻译并**只改自己那一段，
  其余字段原样保留**。

## 安装

随仓库一起装（见根 [`README`](../../README.md)）:

```bash
bash scripts/mcp-plugin-mgr.sh install
source ~/.bashrc
```

无第三方运行时依赖；Python 3.7+（< 3.11 自备 `tomli>=1.1`）。

## 快速上手(Outline)

Outline 走 Streamable HTTP，每个部署有独立 URL + API token。内置 `outline` preset 知道怎么把
token 拼成 `Authorization: Bearer <token>` 头：

```bash
# 交互式（有 TTY）：回车应用到全部 agent，然后逐项填 url / token
mcp-plugin-mgr add outline

# 非交互式 / 脚本：一次给齐，--all-drivers 写进全部 agent
mcp-plugin-mgr add outline \
  --url https://your-outline.example.com/mcp \
  --token ol_api_xxxxxxxxxxxx \
  --all-drivers
# 加 --auto-allow：一并把 outline 的工具写进 Claude Code permissions.allow,
# 避免之后写大文档（≥3000 字符）被 auto-mode 误拦
mcp-plugin-mgr add outline --url ... --token ... --all-drivers --auto-allow
```

写入结果：

- Claude Code `~/.claude.json` → `mcpServers.outline = {"type":"http","url":...,"headers":{"Authorization":"Bearer ..."}}`
- OpenCode `~/.config/opencode/opencode.json` → `mcp.servers.outline = {"type":"remote","url":...,"disabled":false,"headers":{...}}`
- Qoder CLI `~/.qoder/settings.json` → `mcpServers.outline = {"url":...,"type":"http","headers":{...}}`

重启 agent 即加载：

- Claude Code:Ctrl+D 退出后重新 `claude`
- OpenCode：重启 CLI
- Qoder CLI：重启 `qodercli`

> 同一个 `opencode.json` 里的 `provider`/`model` 归 `model-switch` 管；本工具只动 `mcp` 那一段，
> 两者**字段不重叠**，可并存。`~/.claude.json` 与 `~/.claude/settings.json` 是两个不同的文件
> （后者归 model-switch），互不干扰。

## 命令一览

```bash
mcp-plugin-mgr init                      # 初始化 ~/.config/mcp-plugin-mgr/
mcp-plugin-mgr add <name> [opts]         # 加服务(preset 名或显式 flag)
mcp-plugin-mgr list                      # 列出已注册服务(+ 每个 agent 是否已写入)
mcp-plugin-mgr remove <name> [opts]      # 从注册表与 agent 配置移除
mcp-plugin-mgr disable <name> [opts]     # 停用:保留凭据,agent 侧关掉连接
mcp-plugin-mgr enable <name> [opts]      # 重新启用:从注册表还原,无需重配
mcp-plugin-mgr test <name> | --url URL   # 探活:真的发 initialize 握手,诊断连不通的根因
mcp-plugin-mgr presets                   # 列出内置 preset
mcp-plugin-mgr status                    # 路径 / 计数概览
```

`add` / `remove` 选 agent 的方式与 model-switch 的 `model use` 一致：

- `--driver <name>` 只写一个 agent
- `--all-drivers` 写全部（跳过交互）
- 省略 + 有 TTY：交互式，回车=全部
- 省略 + 无 TTY（CI / 脚本）：回退默认 `claude-code`，避免脚本意外改多个 agent

### `add` 选项

| 选项 | 说明 |
| --- | --- |
| `<name>` | 服务名。命中 preset（如 `outline`）时套用 preset 默认值 |
| `--url URL` | http 传输：服务 URL |
| `--token TOKEN` | http 传输：塞进 preset 鉴权头的 token（省略则在 TTY 下安全交互输入） |
| `--header KEY=VALUE` | http 传输：额外/裸头（可重复;覆盖 preset 同名头） |
| `--stdio` | 声明 stdio 传输（非 preset 服务） |
| `--command CMDLINE` | stdio 传输：完整命令行，按 shell 规则拆成可执行文件 + 参数，如 `'uvx --from git+https://... run'` |
| `--env KEY=VALUE` | stdio 传输：环境变量（可重复） |
| `--description TEXT` | 自由描述 |
| `--driver` / `--all-drivers` | 选 agent（见上） |
| `--no-apply` | 只写进 servers.toml，暂不写 agent 配置 |
| `--auto-allow` | 一并把该服务的工具加进 Claude Code `permissions.allow`（避免 auto-mode 拦大文档写入） |
| `--force` | 同名已存在时覆盖 |

### 非 preset 服务

```bash
# 手写 http（自带裸 Authorization 头）
mcp-plugin-mgr add myhttp --url https://srv/mcp --header "Authorization=Bearer xyz" --all-drivers

# 手写 stdio
mcp-plugin-mgr add mytool --stdio --command "uvx --from git+https://example/x run" --all-drivers
```

### 内置 preset

- `outline` — Outline wiki(Streamable HTTP)。需 `--url` + `--token`。
- `memos` — [Memos](https://usememos.com)(Streamable HTTP)。需 `--url`（实例地址,含 `/mcp`）+ `--token`（Memos 设置里的 personal access token）。
- `agent-html-drop` — 自托管 HTML drop(Streamable HTTP)。需 `--url`（HTTPS origin,含 `/mcp`）+ `--token`（server 端 Bearer token）。让本机 agent 把 `yzr-md-to-html` 等产出的自包含 HTML 推到远端 server，提供 6 个 tool(`upload_html` / `list_html` / `delete_html` / `get_public_url` / `list_annotations` / `delete_annotation`)。

> 任意 http/stdio MCP 都能用 flag 配（不限于 preset）；需要更多开箱 preset 时往
> `src/mcp_plugin_mgr/presets/` 下加一个模块即可。

加 Memos:

```bash
mcp-plugin-mgr add memos \
  --url https://your-memos.example.com/mcp \
  --token <personal-access-token> \
  --all-drivers
```

加 agent-html-drop(token 在 server 端取：`agent-html-drop token show` 或容器
`docker compose exec agent-html-drop agent-html-drop token show`):

```bash
mcp-plugin-mgr add agent-html-drop \
  --url https://notes.example.com/mcp \
  --token <server-side-bearer-token> \
  --all-drivers \
  --auto-allow   # upload_html 写大 HTML(默认上限 50MB),预批 6 个工具避免 auto-mode 误拦
```

## 启用 / 停用

`disable` 与 `remove` 的区别：**`disable` 不删注册表条目**——`servers.toml` 里只多一行
`enabled = false`,url / token / headers 全部保留，所以 `enable` 直接还原，**不需要重新配**。
暂时不用的服务（或某些 agent 里噪声大的服务）应该 `disable` 而不是 `remove`。

```bash
mcp-plugin-mgr disable memos --all-drivers    # 三个 agent 一起停
mcp-plugin-mgr enable memos --all-drivers     # 一键恢复(不用再给 --url/--token)
mcp-plugin-mgr disable memos --driver opencode
mcp-plugin-mgr disable memos --no-apply       # 只改 servers.toml,暂不动 agent 配置
```

停用方式按各 agent 的原生能力翻译（`list` 的 STATE 列显示 `enabled` / `DISABLED`）:

| agent | disable 落盘 | 说明 |
| --- | --- | --- |
| OpenCode | `mcp.servers.<name>.disabled: true`（原地翻） | 条目保留；你手加的 `timeout` / `oauth` 等键不动 |
| Qoder CLI | `mcpServers.<name>.disabled: true`（原地加） | 对齐 `qodercli mcp disable` 自己的产出，其余键不动 |
| Claude Code | 删掉 `mcpServers.<name>` | 它没有全局 disable flag（`/mcp` 面板的停用只按项目记进 `disabledMcpServers`） |

Claude Code 走"删条目 + enable 时重渲染"，所以 `disable` / `enable` 前会**比对 agent 侧现有配置与
注册表要渲染的内容**；若有不一致会打印 **drift 警告**(`+ 仅 agent 侧有`、`~ 值不同`),**警告不阻断**:
操作照常执行、退出码仍 0。注意注册表只承载 canonical 字段（transport/url/headers/command/args/env/
description)，所以 agent 侧独有的键（如手加的 `timeout`）无法从注册表还原——要长期保留就得让
driver 的 `render()` 支持该字段。OpenCode / Qoder CLI 因为是原地翻 flag，不存在这个问题。

停用期间要改 URL / token，用 `add <name> --force` 重新给全参数（它会重新启用）;`disable` 本身
不动凭据，`enable` 也不看参数。

`disable` / `enable` **不联动** Claude Code 的 `permissions.allow`(`--auto-allow` 是 `add`/`remove`
的选项)：停用不会撤销已预批的工具名——服务缺席时这些条目无害；要清掉就 `remove --auto-allow`。

## 诊断：`test` 探活

`add` 只保证配置写进去了，不保证端点真能用。`test` 真的向 MCP server 发一次
`initialize` 握手，按**每种传输**给一套基本判定：

- **http / Streamable HTTP**（outline、memos、任意 https MCP）:POST JSON-RPC `initialize`,
  按 HTTP 状态 / 响应体分类。
- **stdio**（任意本地命令 MCP）:spawn 进程，stdin 喂 `initialize`，读 JSON-RPC 回包。

测注册表里的服务（按其传输自动选流程）:

```bash
mcp-plugin-mgr test outline           # 用 servers.toml 里存的 url + headers
mcp-plugin-mgr test my-stdio-tool     # stdio → spawn + 握手
```

或临时探一个端点（不必先 add）:

```bash
mcp-plugin-mgr test --url https://your-outline/mcp --token ol_api_xxx
```

能识别的典型故障：`✓` 正常（附 serverInfo / protocolVersion）、`401/403` 认证、`403` 但被
Cloudflare 等边缘 WAF 拦截（报 `waf_blocked` 而不是让你去换 token——探针自带具名 User-Agent,
否则 CF 会把默认的 `Python-urllib` UA 当成机器人返 Error 1010）、`404` 路径错、
`405` 不支持 POST、连不上 / DNS / 超时、`200 但非 JSON-RPC`。

**ddnsto / 内网穿透陷阱**（专门诊断）：若 `http://` 端点返 `200` 但响应体为空
(典型 `*.ddnsto.com` 反代盒的 HTTP 端口对所有路径返占位 200 + `Content-Length: 0`,
真 MCP 只在 HTTPS 443 才透到上游),`test` 会**自动再探一次 HTTPS 变体**并直接给出修复：

```
$ mcp-plugin-mgr test --url http://myoutline.ddnsto.com/mcp --token xxx
✗ HTTP 200 空响应(疑似 middlebox),但 HTTPS 变体正常!
  fix: 把 endpoint 改成 https://myoutline.ddnsto.com/mcp
```

退出码：正常 `0`，任何异常 `1`（可脚本化:`mcp-plugin-mgr test outline && echo ok`）。

## 注册表(servers.toml)

`~/.config/mcp-plugin-mgr/servers.toml` 是单一真源，传输中立的规范形式：

```toml
[servers.outline]
transport = "http"
url = "https://your-outline.example.com/mcp"
[servers.outline.headers]
Authorization = "Bearer ol_api_xxxx"

[servers.my-stdio-tool]    # 任意 stdio MCP(非 preset,用 flag 添加后落盘成这样)
transport = "stdio"
command = "uvx"
args = ["--from", "git+https://example/some-mcp", "run"]
```

未知顶层键与未知每服务键都**原样透传**（和 model-switch 的 `models.toml` 同纪律）。

## 设计要点 / 局限

- **命令面**:`add` / `list` / `remove` / `enable` / `disable` / `test` / `presets` / `status`。
  启停语义按各 agent 翻译（见上「启用 / 停用」）:OpenCode 与 Qoder CLI 有原生 flag 可原地翻，
  Claude Code 无全局 flag 只能删条目（注册表留底,`enable` 还原）。不做 per-project 停用
  （Claude Code 的 `/mcp` 面板 / 项目级 `.mcp.json` 场景）。
- **写 agent 配置 = 原子写 + 字段透传**：读全 JSON → 只改自己的那段(`mcpServers` / `mcp`)→
  写 `.tmp` 再 `os.replace`，绝不半写；文件里其它字段（userID、onboarding、provider/model、$schema、
  model/ui/permissions）一字不动。
- **停用的两个边界**:Claude Code 侧 agent 独有的手加字段不会从注册表还原（操作前有 drift 警告，
  见上「启用 / 停用」);OAuth 型 MCP 在 Claude Code 上被 `remove` 时其 OAuth token / client
  registration 会一并删除（官方行为），这类服务停用后再启用需要重新授权——本工具的三个 preset
  都是 Bearer 头，不受影响。
- **明文 token**:token 写进 `servers.toml` 与 agent 配置（同 model-switch 的本地信任模型，
  注意文件权限）。
- **测试隔离**:tests 绝不碰真实的 `~/.claude.json` / `opencode.json` / `~/.qoder/settings.json`;
  `tests/conftest.py` 把路径重定向到 tmp,teardown 断言真实配置字节级一致。
- **lazy 注册 driver**:import 时不创建指向 `Path.home()/...` 的实例，首次用时才注册，避免测试隔离漏洞。

设计详情见 [`docs/mcp-plugin-mgr-design.md`](../../docs/mcp-plugin-mgr-design.md)。
