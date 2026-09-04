# yzr-agent-tools

`yzr-agent-tools` 是一个围绕 AI coding agent(Claude Code、OpenCode、Qoder CLI、……)的本地运维 /
配置工具集合。每个工具独立成 CLI 或常驻服务,共享同一套仓库规约(测试隔离、原子写、
未知字段透传)。

## 本仓库目前包含的工具

| 工具             | 简介                                                                            | 状态     |
| ---------------- | ------------------------------------------------------------------------------- | -------- |
| [`model-switch`](src/model_switch/README.md) | CLI;切换 AI coding agent 使用的 Anthropic 兼容模型 | 已发布   |
| [`mcp-plugin-mgr`](src/mcp_plugin_mgr/README.md) | CLI;管理 Claude Code / OpenCode / Qoder CLI 的自定义 MCP 服务(起点:Outline wiki),一份注册表翻译到各 agent | 已发布 |
| [`yzr-agent-style`](src/yzr_agent_style/README.md) | 脚本;把一份全局指令模板以 marker 块形式安装/卸载到 Claude Code / OpenCode / Qoder CLI 的全局规则文件,不覆盖用户手写内容 | 新增 |
|  [`llmw-connect-mgr`](src/llmw_connect_mgr/README.md) | CLI;llmw-connect daemon（cc-connect llmw fork） 的首装/配置/升级/卸载(npm 制品 + systemd 看门狗,secrets 走 env 文件) | 新增 |

> 新工具按需添加;同一份仓库规约对所有工具生效。完整仓库规约、目录结构、跨工具注意事项
> 见 [`AGENTS.md`](AGENTS.md)。

## 一句话简介

- **`model-switch`** — 把 Anthropic 兼容模型(任何与 `ANTHROPIC_*` 协议兼容的上游,
  包括 yzr / GLM / 各种代理网关)注册到本地仓库,然后一行 `model use <name>` 写进
  Claude Code / OpenCode 的全局配置,重启 agent 即生效。
- **`mcp-plugin-mgr`** — 一份 `servers.toml` 注册表管你的自定义 MCP 服务(以 Outline wiki 为
  起点),`add <name>` 翻译成 Claude Code(`~/.claude.json` 的 `mcpServers`)、OpenCode
  (`opencode.json` 的 `mcp`)与 Qoder CLI(`~/.qoder/settings.json` 的 `mcpServers`)各自的
  位置/字段/type 词表,只改自己那一段、其余原样保留,重启即生效。
- **`yzr-agent-style`** — 把仓内一份指令模板以 marker 块的形式安装/卸载到各 agent 的全局
  规则文件(Claude Code `~/.claude/CLAUDE.md`、OpenCode `~/.config/opencode/AGENTS.md`、
  Qoder CLI `~/.qoder/AGENTS.md`),块外手写内容原样保留、重跑幂等同步。

## 仓库共用规约

- **测试隔离** — `tests/conftest.py` 的 autouse fixture 快照真实用户级配置
  (`~/.claude/settings.json`、`~/.claude.json`)的 mtime + sha256,把工具相关路径
  重定向到 tmp,替换 driver / handler 指向 tmp,teardown 时断言真实配置字节级一致。
  任何 driver / storage / handler bug 都不会污染你的真实配置。
- **原子写** — TOML(JSON)写流程都是先 `.tmp` + `os.replace()`;绝不出现半写状态。
- **未知字段透传** — 读配置时把未知键收进 `extra` 桶,落盘时原样回写;用户的
  theme、plugins、自定义 env、第三方字段都不会丢。
- **stdlib-only(运行时)** — 无第三方依赖;Python 3.7+;< 3.11 时自备 `tomli>=1.1`。
- **lazy 注册 driver / handler** — import 时不创建指向 `Path.home() / ...` 的实例;
  首次需要时再 `registry.register(...)`,避免测试隔离漏洞。

## 常用命令

```bash
# 安装 — 每工具一个自包含脚本:写 wrapper + 装补全 + 加 PATH 块。无 venv,无 pip。
bash scripts/model-switch.sh install
bash scripts/mcp-plugin-mgr.sh install
bash scripts/llmw-connect-mgr.sh install
source ~/.bashrc   # 或 ~/.zshrc

# 卸载 — 删 wrapper + 剥该工具的 PATH marker + 删补全 symlink;不动 ~/.config/<tool>/ 下的数据
bash scripts/model-switch.sh uninstall
bash scripts/mcp-plugin-mgr.sh uninstall
bash scripts/llmw-connect-mgr.sh uninstall

# 测试 — pyproject.toml 已含 src/ 到 pythonpath,不需要 `pip install -e .`
pytest
pytest --cov=model_switch
pytest --cov=mcp_plugin_mgr

# 各 CLI
model-switch model list
model-switch model use glm-z1-plus
mcp-plugin-mgr add outline --url https://your-outline/mcp --token ol_api_xxx --all-drivers
mcp-plugin-mgr list
```

## 许可证

MIT.