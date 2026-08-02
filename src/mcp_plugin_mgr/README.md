# mcp-plugin-mgr

管理 Claude Code / OpenCode 的自定义 MCP 服务(以 **Outline wiki** 为起点)。把你在本地注册的
MCP 服务翻译成各 agent 自己的协议写进各自配置,重启 agent 即生效。

和 [`model-switch`](../model_switch/README.md) 同构:**一个工具,多个 agent**,每个 agent 一个
driver 负责把统一的「服务定义」渲染成该 agent 的字段与位置。

## 它解决什么

- Claude Code 的 MCP 服务在 `~/.claude.json` 的 `mcpServers`;OpenCode 的在
  `~/.config/opencode/opencode.json` 的 `mcp`。**位置不同、字段名不同、type 词表不同**
  (Claude Code: `http`/`stdio`;OpenCode: `remote`/`local`,且 `command` 是 cmd+args 合并的
  数组,env 字段叫 `environment`)。
- 手改两个文件、两套写法、还要保留下沉在同一个文件里的其它字段(Claude Code 的 onboarding /
  projects / OpenCode 的 provider/model)——容易出错。
- 本工具:你只维护一份 `~/.config/mcp-plugin-mgr/servers.toml`,driver 负责翻译并**只改自己那一段,
  其余字段原样保留**。

## 安装

随仓库一起装(见根 [`README`](../../README.md)):

```bash
bash scripts/mcp-plugin-mgr.sh install
source ~/.bashrc
```

无第三方运行时依赖;Python 3.7+(< 3.11 自备 `tomli>=1.1`)。

## 快速上手(Outline)

Outline 走 Streamable HTTP,每个部署有独立 URL + API token。内置 `outline` preset 知道怎么把
token 拼成 `Authorization: Bearer <token>` 头:

```bash
# 交互式(有 TTY):回车应用到全部 agent,然后逐项填 url / token
mcp-plugin-mgr add outline

# 非交互式 / 脚本:一次给齐,--all-drivers 写进全部 agent
mcp-plugin-mgr add outline \
  --url https://your-outline.example.com/mcp \
  --token ol_api_xxxxxxxxxxxx \
  --all-drivers
# 加 --auto-allow:一并把 outline 的工具写进 Claude Code permissions.allow,
# 避免之后写大文档(≥3000 字符)被 auto-mode 误拦
mcp-plugin-mgr add outline --url ... --token ... --all-drivers --auto-allow
```

写入结果:

- Claude Code `~/.claude.json` → `mcpServers.outline = {"type":"http","url":...,"headers":{"Authorization":"Bearer ..."}}`
- OpenCode `~/.config/opencode/opencode.json` → `mcp.outline = {"type":"remote","url":...,"enabled":true,"headers":{...}}`

重启 agent 即加载:

- Claude Code:Ctrl+D 退出后重新 `claude`
- OpenCode:重启 CLI

> 同一个 `opencode.json` 里的 `provider`/`model` 归 `model-switch` 管;本工具只动 `mcp` 那一段,
> 两者**字段不重叠**,可并存。`~/.claude.json` 与 `~/.claude/settings.json` 是两个不同的文件
> (后者归 model-switch),互不干扰。

## 命令一览

```bash
mcp-plugin-mgr init                      # 初始化 ~/.config/mcp-plugin-mgr/
mcp-plugin-mgr add <name> [opts]         # 加服务(preset 名或显式 flag)
mcp-plugin-mgr list                      # 列出已注册服务(+ 每个 agent 是否已写入)
mcp-plugin-mgr remove <name> [opts]      # 从注册表与 agent 配置移除
mcp-plugin-mgr test <name> | --url URL   # 探活:真的发 initialize 握手,诊断连不通的根因
mcp-plugin-mgr presets                   # 列出内置 preset
mcp-plugin-mgr status                    # 路径 / 计数概览
```

`add` / `remove` 选 agent 的方式与 model-switch 的 `model use` 一致:

- `--driver <name>` 只写一个 agent
- `--all-drivers` 写全部(跳过交互)
- 省略 + 有 TTY:交互式,回车=全部
- 省略 + 无 TTY(CI / 脚本):回退默认 `claude-code`,避免脚本意外改多个 agent

### `add` 选项

| 选项 | 说明 |
| --- | --- |
| `<name>` | 服务名。命中 preset(如 `outline`)时套用 preset 默认值 |
| `--url URL` | http 传输:服务 URL |
| `--token TOKEN` | http 传输:塞进 preset 鉴权头的 token(省略则在 TTY 下安全交互输入) |
| `--header KEY=VALUE` | http 传输:额外/裸头(可重复;覆盖 preset 同名头) |
| `--stdio` | 声明 stdio 传输(非 preset 服务) |
| `--command CMDLINE` | stdio 传输:完整命令行,按 shell 规则拆成可执行文件 + 参数,如 `'uvx --from git+https://... run'` |
| `--env KEY=VALUE` | stdio 传输:环境变量(可重复) |
| `--description TEXT` | 自由描述 |
| `--driver` / `--all-drivers` | 选 agent(见上) |
| `--no-apply` | 只写进 servers.toml,暂不写 agent 配置 |
| `--auto-allow` | 一并把该服务的工具加进 Claude Code `permissions.allow`(避免 auto-mode 拦大文档写入) |
| `--force` | 同名已存在时覆盖 |

### 非 preset 服务

```bash
# 手写 http(自带裸 Authorization 头)
mcp-plugin-mgr add myhttp --url https://srv/mcp --header "Authorization=Bearer xyz" --all-drivers

# 手写 stdio
mcp-plugin-mgr add mytool --stdio --command "uvx --from git+https://example/x run" --all-drivers
```

### 内置 preset

- `outline` — Outline wiki(Streamable HTTP)。需 `--url` + `--token`。
- `memos` — [Memos](https://usememos.com)(Streamable HTTP)。需 `--url`(实例地址,含 `/mcp`)+ `--token`(Memos 设置里的 personal access token)。

> 任意 http/stdio MCP 都能用 flag 配(不限于 preset);需要更多开箱 preset 时往
> `src/mcp_plugin_mgr/presets.py` 加即可。

加 Memos:

```bash
mcp-plugin-mgr add memos \
  --url https://your-memos.example.com/mcp \
  --token <personal-access-token> \
  --all-drivers
```

## 诊断:`test` 探活

`add` 只保证配置写进去了,不保证端点真能用。`test` 真的向 MCP server 发一次
`initialize` 握手,按**每种传输**给一套基本判定:

- **http / Streamable HTTP**(outline、memos、任意 https MCP):POST JSON-RPC `initialize`,
  按 HTTP 状态 / 响应体分类。
- **stdio**(任意本地命令 MCP):spawn 进程,stdin 喂 `initialize`,读 JSON-RPC 回包。

测注册表里的服务(按其传输自动选流程):

```bash
mcp-plugin-mgr test outline           # 用 servers.toml 里存的 url + headers
mcp-plugin-mgr test my-stdio-tool     # stdio → spawn + 握手
```

或临时探一个端点(不必先 add):

```bash
mcp-plugin-mgr test --url https://your-outline/mcp --token ol_api_xxx
```

能识别的典型故障:`✓` 正常(附 serverInfo / protocolVersion)、`401/403` 认证、`404` 路径错、
`405` 不支持 POST、连不上 / DNS / 超时、`200 但非 JSON-RPC`。

**ddnsto / 内网穿透陷阱**(专门诊断):若 `http://` 端点返 `200` 但响应体为空
(典型 `*.ddnsto.com` 反代盒的 HTTP 端口对所有路径返占位 200 + `Content-Length: 0`,
真 MCP 只在 HTTPS 443 才透到上游),`test` 会**自动再探一次 HTTPS 变体**并直接给出修复:

```
$ mcp-plugin-mgr test --url http://myoutline.ddnsto.com/mcp --token xxx
✗ HTTP 200 空响应(疑似 middlebox),但 HTTPS 变体正常!
  fix: 把 endpoint 改成 https://myoutline.ddnsto.com/mcp
```

退出码:正常 `0`,任何异常 `1`(可脚本化:`mcp-plugin-mgr test outline && echo ok`)。

## 注册表(servers.toml)

`~/.config/mcp-plugin-mgr/servers.toml` 是单一真源,传输中立的规范形式:

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

未知顶层键与未知每服务键都**原样透传**(和 model-switch 的 `models.toml` 同纪律)。

## 设计要点 / 局限

- **只做增删查**(V1):`add` / `list` / `remove`,不做 enable/disable / 连通性探测。两个 agent 的
  enable 语义不对称(Claude Code 无原生 disable,OpenCode 有 `enabled` 字段),V1 暂不碰。
- **写 agent 配置 = 原子写 + 字段透传**:读全 JSON → 只改自己的那段(`mcpServers` / `mcp`)→
  写 `.tmp` 再 `os.replace`,绝不半写;文件里其它字段(userID、onboarding、provider/model、$schema)一字不动。
- **明文 token**:token 写进 `servers.toml` 与 agent 配置(同 model-switch 的本地信任模型,
  注意文件权限)。
- **测试隔离**:tests 绝不碰真实的 `~/.claude.json` / `opencode.json`;`tests/conftest.py` 把路径
  重定向到 tmp,teardown 断言真实配置字节级一致。
- **lazy 注册 driver**:import 时不创建指向 `Path.home()/...` 的实例,首次用时才注册,避免测试隔离漏洞。

设计详情见 [`docs/mcp-plugin-mgr-design.md`](../../docs/mcp-plugin-mgr-design.md)。
