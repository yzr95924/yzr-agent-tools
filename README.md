# yzr-agent-tools

`yzr-agent-tools` 是一个围绕 AI coding agent(Claude Code、OpenCode、……)的本地运维 /
配置工具集合。每个工具独立成 CLI 或常驻服务,共享同一套仓库规约(测试隔离、原子写、
未知字段透传)。

## 本仓库目前包含的工具

| 工具             | 简介                                                                            | 状态     |
| ---------------- | ------------------------------------------------------------------------------- | -------- |
| [`model-switch`](src/model_switch/README.md) | CLI;切换 AI coding agent 使用的 Anthropic 兼容模型 | 已发布   |
| [`html-mcp`](src/html_mcp/README.md)         | 常驻 HTTP daemon;agent 通过 MCP 把自包含 HTML 推到 nginx server,带管理页 | 已发布 |

> 新工具按需添加;同一份仓库规约对所有工具生效。完整仓库规约、目录结构、跨工具注意事项
> 见 [`AGENTS.md`](AGENTS.md)。

## 一句话简介

- **`model-switch`** — 把 Anthropic 兼容模型(任何与 `ANTHROPIC_*` 协议兼容的上游,
  包括 yzr / GLM / 各种代理网关)注册到本地仓库,然后一行 `model use <name>` 写进
  Claude Code / OpenCode 的全局配置,重启 agent 即生效。
- **`html-mcp`** — 一个常驻 HTTP daemon,把 agent 产出的自包含 HTML(`yzr-md-to-html`
  之类工具的输出)推到远端 nginx 的 docroot,带 Bearer token 鉴权 + HTML 管理页;
  agent 侧通过标准 MCP Streamable HTTP 接。

## 仓库共用规约

- **测试隔离** — `tests/conftest.py` 的 autouse fixture 快照真实用户级配置
  (`~/.claude/settings.json`、`~/.config/html-mcp/`)的 mtime + sha256,把工具相关路径
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
# 安装 — shell wrapper + PYTHONPATH,无 venv,无 pip
bash scripts/install.sh
source ~/.bashrc

# 卸载 — 删 wrapper + 剥 PATH marker + 删补全 symlink;不动 ~/.config/<tool>/ 下的数据
bash scripts/uninstall.sh

# 测试 — pyproject.toml 已含 src/ 到 pythonpath,不需要 `pip install -e .`
pytest
pytest --cov=model_switch
pytest --cov=html_mcp

# 各 CLI
model-switch model list
model-switch model use glm-z1-plus
html-mcp status
html-mcp serve
```

## 许可证

MIT.