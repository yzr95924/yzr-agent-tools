# AGENTS.md

> **关键**：本文件里凡 `@path/to/file` 形式的引用（如 `@MEMORY/MEMORY.md`），都用 Read 工具按需
> 读取——它们与你**当前任务**直接相关。不自动展开 `@import` 的 agent 尤须手动执行，否则漏上下文。

## 项目定位

`model-switch` 是一个 CLI：切换 AI coding agent（V1 主目标 Claude Code）使用的 Anthropic 兼容模型。
通过直接改写 agent 的全局配置文件（Claude Code 的 `~/.claude/settings.json` 等）实现——无 daemon、
无代理、无协议转换。用户跑 `model-switch model use <name>` 然后重启 agent 即生效。

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
```

## 高层结构

```
cli.py                  argparse CLI（仅做编排）
   │
   ├─→ paths.py            XDG 路径解析
   ├─→ store.py            TOML I/O + 透传未知字段
   │     ModelEntry / Registry / State
   │
   └─→ drivers/             各 agent 配置适配器
         base.py         AgentDriver Protocol + DriverRegistry 单例
         claude_code.py  读写 Claude Code 的 ~/.claude/settings.json
```

**Driver 抽象是核心**：每个 agent 一个 driver 类，实现 `read() / apply(model, api_key) / current()`。
加新 agent = 写一个 driver + 注册。当前内置 `claude-code` 与 `opencode`：
- `claude-code` 写 `~/.claude/settings.json` 的 `env` 块（`ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL`）+ 顶层 `model` 字段。
- `opencode` 写 OpenCode 全局配置 `$XDG_CONFIG_HOME/opencode/opencode.json`（默认 `~/.config/opencode/opencode.json`，**不是** `~/.opencode.json`）的 `provider.yzr` 块：`npm: @ai-sdk/anthropic`（Anthropic 兼容上游必需的 adapter，否则 OpenCode 报 "Provider not found" 退回默认模型）+ `options.baseURL`（**driver 自动补 `/v1`**：`@ai-sdk/anthropic` 只在 baseURL 后追加 `/messages`，而 store 里 `base_url` 不带 /v1——那正是 claude-code driver 要的形式（Claude Code 自己补 /v1）；语义差异封装在各自 driver，同一 `base_url` 服务两个 agent。不补会让 opencode 打到 `.../anthropic/messages`，上游回 404 包在 HTTP 200，ai-sdk 静默丢包 → 空响应、零 token、无 error）+ `options.apiKey` **直接写解析后的明文 key**（同 claude-code driver，**不用** `{env:VAR}` 占位符；密钥落盘，注意文件权限）+ 顶层 `model: yzr/<name>`。**故意不写 `limit`**：OpenCode schema 要求 `limit` 存在时必须有 `limit.output`，而我们只追踪 `context_window`，写半截 `{limit:{context}}` 会让整份配置校验失败、模型不可用。
通过 `--driver <name>` 选单个、`--all-drivers` 选全部;省略时——交互式(TTY)默认应用到全部已注册 driver(回车即 claude-code 与 opencode 都切,符合「切模型就该到处生效」),非交互(CI/脚本,无 TTY)回退到默认 `claude-code`,避免脚本意外写多个 agent 配置。
新 agent = 实现一个 driver 并在 `cli._ensure_default_registered()` 注册。

**单模型槽**：`model use <name>` 写一个模型到所选 agent 配置。driver 负责把 model 渲染成对应 agent 协议的字段。

## 跨会话记忆（索引）

@MEMORY/MEMORY.md

## 注意事项

- V1 **不做协议转换**——只支持 Anthropic 兼容上游。OpenAI 兼容（原生 OpenAI、DeepSeek、Ollama）需
  翻译层，V1 不计划。
