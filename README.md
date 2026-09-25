# yzr-agent-tools

`yzr-agent-tools` 是一个围绕 AI coding agent(Claude Code、OpenCode、Qoder CLI、……)的本地运维 /
配置工具集合。每个工具独立成 CLI 或常驻服务，共享同一套仓库规约（测试隔离、原子写、
未知字段透传）。

## 本仓库目前包含的工具

| 工具 | 简介 |
| --- | --- |
| [`model-switch`](src/model_switch/README.md) | CLI；切换 AI coding agent 使用的 Anthropic 兼容模型 |
| [`mcp-plugin-mgr`](src/mcp_plugin_mgr/README.md) | CLI；管理 Claude Code / OpenCode / Qoder CLI 的自定义 MCP 服务（起点：Outline wiki），一份注册表翻译到各 agent |
| [`yzr-agent-style`](src/yzr_agent_style/README.md) | 脚本；把一份全局指令模板以 marker 块形式安装/卸载到 Claude Code / OpenCode / Qoder CLI 的全局规则文件，不覆盖用户手写内容 |
| [`llmw-connect-mgr`](src/llmw_connect_mgr/README.md) | CLI;llmw-connect daemon(cc-connect llmw fork) 的首装/配置/升级/卸载（npm 制品 + systemd 看门狗，secrets 走 env 文件） |
| [`opencode-plugins`](src/opencode_plugins/README.md) | CLI；把仓内维护的个人 OpenCode 插件装到 OpenCode 全局插件位置并登记/摘除（首个插件 `at-import`：让 AGENTS.md 的 `@path` 行在 OpenCode V2 下自动展开注入） |

> 新工具按需添加；同一份仓库规约对所有工具生效。完整仓库规约、目录结构、跨工具注意事项
> 见 [`AGENTS.md`](AGENTS.md)。各工具的安装 / 快速上手 / 命令一览 / 局限性见其
> `src/<tool>/README.md`。

## 仓库共用规约

- **测试隔离** — `tests/conftest.py` 的 autouse fixture 快照真实用户级配置
  (`~/.claude/settings.json`、`~/.claude.json`)的 mtime + sha256，把工具相关路径
  重定向到 tmp，替换 driver / handler 指向 tmp,teardown 时断言真实配置字节级一致。
  任何 driver / storage / handler bug 都不会污染你的真实配置。
- **原子写** — TOML(JSON)写流程都是先 `.tmp` + `os.replace()`；绝不出现半写状态。
- **未知字段透传** — 读配置时把未知键收进 `extra` 桶，落盘时原样回写；用户的
  theme、plugins、自定义 env、第三方字段都不会丢。
- **stdlib-only（运行时）** — 无第三方依赖；Python 3.7+;< 3.11 时自备 `tomli>=1.1`。
- **lazy 注册 driver / handler** — import 时不创建指向 `Path.home() / ...` 的实例；
  首次需要时再 `registry.register(...)`，避免测试隔离漏洞。

## 常用命令

```bash
# 安装 — 每工具一个自包含脚本：写 wrapper + 装补全(bash/zsh/fish) + 加 PATH 块。无 venv，无 pip。
bash scripts/model-switch.sh install
bash scripts/mcp-plugin-mgr.sh install
bash scripts/llmw-connect-mgr.sh install
bash scripts/opencode-plugins.sh install
bash scripts/yzr-agent-style.sh install   # 薄壳:只跑 install/uninstall,无 wrapper/PATH/补全
source ~/.bashrc   # 或 ~/.zshrc
# opencode-plugins 还有一步：把仓内 bundled 插件装进 OpenCode
opencode-plugins install

# 卸载 — 删 wrapper + 剥该工具的 PATH marker + 删补全 symlink；不动 ~/.config/<tool>/ 下的数据
bash scripts/model-switch.sh uninstall
bash scripts/mcp-plugin-mgr.sh uninstall
bash scripts/llmw-connect-mgr.sh uninstall
bash scripts/opencode-plugins.sh uninstall
bash scripts/yzr-agent-style.sh uninstall

# 测试 — pyproject.toml 已含 src/ 到 pythonpath，不需要 `pip install -e .`
pytest
pytest --cov=model_switch
pytest --cov=mcp_plugin_mgr

# 各 CLI
model-switch model list
model-switch model use glm-z1-plus
mcp-plugin-mgr add outline --url https://your-outline/mcp --token ol_api_xxx --all-drivers
mcp-plugin-mgr list
mcp-plugin-mgr disable outline --all-drivers   # 停用但保留凭据;enable 一键恢复,无需重配
```

## 许可证

MIT.
