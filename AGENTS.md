# AGENTS.md

> **关键**：本文件里凡 `@path/to/file` 形式的引用（如 `@MEMORY/MEMORY.md`），都用 Read 工具按需
> 读取——它们与你**当前任务**直接相关。不自动展开 `@import` 的 agent 尤须手动执行，否则漏上下文。

## 项目定位

`yzr-agent-tools` 是一个 CLI：切换 AI coding agent（V1 主目标 Claude Code）使用的 Anthropic 兼容模型。
通过直接改写 agent 的全局配置文件（Claude Code 的 `~/.claude/settings.json` 等）实现——无 daemon、
无代理、无协议转换。用户跑 `yzr model use <name>` 然后重启 agent 即生效。

## 仓库规约

- **测试绝不能触碰真实的 agent 全局配置**（如 `~/.claude/settings.json`）。当前 Claude Code session
  用的就是真配置；任何 driver bug 都会让 session 立刻 API error 报。`tests/conftest.py` 的 autouse fixture
  强制：snapshot 真实配置的 mtime + sha256，重定向 `paths.*` 到 tmp，替换 registry driver 指向 tmp，
  测试结束后断言真配置字节完全一致。详细 [[test-isolation-invariants]]。
- **Python 3.7+ 兼容**。pyproject 固定 `typer>=0.9,<0.11`、`click<8.2`、`pydantic>=1.10,<2`。
  禁 `dict[str, str]` 语法、walrus、`match`；用 `from typing import Dict, List, Optional`。
- **driver 必须保留未知字段**。`ClaudeCodeDriver.apply()` 读全 JSON、只改 `env` 块、回写——用户的
  theme、plugins、自定义 env 都不能丢。
- **原子写文件**。YAML（config.py）和 JSON（claude_code driver）都先写 `.tmp` 再 `os.replace()`，
  永远不出现半写状态。
- **API key 不落盘**。`model add` 只存 env var 名（`api_key_env`），`apply()` 运行时从 `os.environ` 解析。
- **不要在 import 时副作用注册 driver**。会让 module import 那一刻创建指向 `Path.home() / ...` 的实例，
  成为测试隔离漏洞。改成 lazy：在 cli.py 第一次需要 driver 时再 `registry.register(...)`。

## 常用命令

```bash
# 安装（editable + dev extras）
pip install -e ".[dev]"

# 测试
pytest
pytest tests/test_cli.py -v                   # 单文件
pytest tests/test_cli.py::test_model_use_*    # 单测匹配
pytest --cov=yzr_agent_tools                  # 带覆盖率

# CLI 自身
yzr model list
yzr model add glm-z1 --base-url ... --api-key-env GLM_API_KEY --model-name glm-4
yzr model use glm-z1
yzr status
```

## 高层结构

```
cli.py                  Typer 命令（仅做编排）
   │
   ├─→ paths.py            XDG 路径解析
   ├─→ config.py           Pydantic 模型 + 原子 YAML I/O
   │     Model / ModelsConfig / State
   │
   └─→ drivers/             各 agent 配置适配器
         base.py         AgentDriver Protocol + DriverRegistry 单例
         claude_code.py  读写 Claude Code 的 ~/.claude/settings.json
```

**Driver 抽象是核心**：每个 agent 一个 driver 类，实现 `read() / apply(main, small, api_key) / current()`。
加新 agent = 写一个 driver + 注册。V2 加 OpenCode 时需切到 `~/.opencode.json` provider-centric 格式、
用 `{env:VAR}` 替 API key——格式不同但 Protocol 相同。

**两个模型槽而非一个**：`model use` 同时激活 main + small。Driver 写
`ANTHROPIC_DEFAULT_OPUS_MODEL` + `ANTHROPIC_DEFAULT_SONNET_MODEL`（← main）和
`ANTHROPIC_DEFAULT_HAIKU_MODEL`（← small）。省略 `--small` 时 small 跟随 main。
`small-model use` / `small-model clear` 只改 small。

## 跨会话记忆（索引）

@MEMORY/MEMORY.md

## 注意事项

- V1 **不做协议转换**——只支持 Anthropic 兼容上游。OpenAI 兼容（原生 OpenAI、DeepSeek、Ollama）需
  翻译层，V1 不计划。
- API key 必须以 env var 形式存在；yzr 不会自己存。
