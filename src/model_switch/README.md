# model-switch

快速切换 Claude Code 使用的模型——无需手动编辑 `~/.claude/settings.json`。

`model-switch` 是一个轻量 CLI：把 Anthropic 兼容的上游模型定义存在自己的配置目录里，
然后在你执行 `model-switch model use <name>` 时，把当前选中的模型写入 Claude Code
的 `settings.json` 的 `env` 块。重启 Claude Code，它就在跟新模型对话了。

## 安装

```bash
# 在本仓库下,使用自带的安装脚本
bash scripts/install.sh
source ~/.bashrc   # 或 ~/.zshrc

# 验证
model-switch --help

# 卸载
bash scripts/uninstall.sh
```

需要 Python 3.7+。安装脚本很薄:写一个 `bin/model-switch`（4 行 bash wrapper,
用 `PYTHONPATH=$REPO/src` 跑 `python3 -m model_switch`）并往 shell rc 里加一段幂等的
PATH 块。不创建虚拟环境,不调 `pip install`。

### 运行时 / 开发依赖(自行安装)

安装脚本**不会**安装任何 Python 包。运行 `model-switch` 之前请确保:

| 用途         | Python < 3.11                     | Python ≥ 3.11 |
| ------------ | --------------------------------- | ------------- |
| 运行 CLI     | `pip install --user 'tomli>=1.1'` | (仅标准库)    |
| 跑测试       | `pip install --user pytest pytest-cov` | 同上         |

如果在 Python < 3.11 上缺 `tomli`,第一次跑 `model-switch` 会在 `import tomli` 处
抛 `ImportError`——装上再重试。

### Shell 补全(bash + fish)

`install.sh` 还会装好 tab 补全:

- **bash** — 软链到 `~/.local/share/bash-completion/completions/`,**并且** 在 `~/.bashrc`
  的 PATH 块里 source 一份,所以即使没装 bash-completion 包也能用。
- **fish** — 软链到 `~/.config/fish/completions/`(自动加载)。

补全覆盖子命令、flag、`--driver` 取值,以及 `model use/show/remove` 的模型名。
动态候选项直接由 CLI 自身产出(隐藏的 `model-switch _complete models|drivers` 管道
命令),所以始终和你 `models.toml` 里的内容一致。`uninstall.sh` 会清理这些软链和
source 行。脚本本体在 `completions/`,想自己接也可以。

## 快速上手

```bash
# 1. 注册一个模型 —— API key 以明文形式存在 models.toml 里
model-switch model add glm-z1-plus \
     --base-url https://open.bigmodel.cn/api/anthropic \
     --api-key sk-... \
     --model-name glm-4-plus \
     --description "GLM-4 Plus" \
     --context-window 200000

# 3. 激活它
model-switch model use glm-z1-plus

# 4. 重启 Claude Code(Ctrl+D,然后再 `claude`)
```

`model-switch status` 显示当前激活的模型,以及 Claude Code 会看到的 env 键:

```
model-switch status
----------------------
active main:  glm-z1-plus (name: glm-4-plus)

Agent (claude-code) effective env in /root/.claude/settings.json:
  ANTHROPIC_BASE_URL    = https://open.bigmodel.cn/api/anthropic
  ANTHROPIC_AUTH_TOKEN  = sk-...
  ANTHROPIC_MODEL       = glm-4-plus
```

## 命令一览

```
model-switch init                              # 创建 ~/.config/model-switch/

model-switch model add <name> \
     --base-url <url> \
     --api-key <KEY> \
     --model-name <id> \
     [--description <text>] \
     [--context-window <tokens>]

model-switch model list                        # 列出所有模型 + 激活标记
model-switch model show <name>
model-switch model remove <name>

model-switch model use <name> [--driver NAME] [--all-drivers]   # 交互式默认 = 全部 driver;非 TTY / CI = 仅 claude-code

model-switch status [--driver NAME] [--all-drivers]
```

## 写进 settings.json 的内容

`env` 块下,加一个顶层 `model`(对应现代的单模型形态):

- `ANTHROPIC_BASE_URL` — 上游 base URL
- `ANTHROPIC_AUTH_TOKEN` — `models.toml` 里这个模型对应的 `api_key`
- `ANTHROPIC_MODEL` — `<name>`,或当 `context_window >= 1_000_000` 时为 `<name>[1m]`
- 顶层 `model` — 与 `ANTHROPIC_MODEL` 同步

`settings.json` 里其它所有内容(主题、插件、`DISABLE_TELEMETRY` 之类的自定义 env)
一律原样保留。

API key 在你跑 `model use` 的那一刻从 shell 环境(或 `models.toml` 的 `api_key` 字段)
解析,然后写成 `ANTHROPIC_AUTH_TOKEN` 的值。model-switch 把 `models.toml` 当成本地
专属配置文件,信任模型与 `workspace_models.toml` 一致。

## 配置目录布局

```
~/.config/model-switch/
├── models.toml      # 你的模型定义(TOML)
└── state.toml       # 当前激活的是哪个
```

`models.toml` 故意做得与 `llmw` 产出的 `workspace_models.toml` 兼容:任何未知的顶层
或单模型键(如 `api_key`、`is_default`、`schema_version`、`created_at`、`updated_at`)
都会读进 `extra` 桶里,下次落盘时原样写回。把 `workspace_models.toml` 直接复制过去
再切模型,llmw 的字段也不会丢。

## 架构说明

- **Driver 抽象。** 每个 agent(目前是 Claude Code 与 OpenCode;后续会更多)
  是一个小 driver 类,知道自己配置文件的读写格式。加一个新 agent = 写一个 driver
  并注册。
- **无 daemon、无代理、无协议转换。** model-switch 只写配置文件。Anthropic 兼容
  上游说的就是 Claude Code 已经在说的协议。
- **需要重启。** 切模型是往 agent 启动时读的配置文件里写内容,要重启 agent 才会生效。

## 对接 OpenCode

除了默认的 Claude Code driver,`model-switch` 还内置了一个 OpenCode driver。
交互式跑 `model use`(不加 flag)直接回车,会**同时**写两个 agent;加 `--driver opencode`
就只动 OpenCode:

```bash
# 给 OpenCode 激活一个模型
model-switch model use glm-z1-plus --driver opencode

# 看 OpenCode 会看到什么
model-switch status --driver opencode
```

OpenCode driver 往 OpenCode 的全局配置 `~/.config/opencode/opencode.json`
(`$XDG_CONFIG_HOME/opencode/opencode.json`)里写一个 `provider.yzr` 块(带 `@ai-sdk/anthropic`
adapter),并把解析出的 API key 直接写入 `apiKey`——密钥是落盘的,请把文件权限收紧。
模型定义(`models.toml`)在 Claude Code 和 OpenCode driver 之间共享,所以切换 agent
不用重新注册模型。

## 跑测试

```bash
# pytest 必须能在 PATH 上找到(比如 `pip install --user pytest pytest-cov`)。
# pyproject.toml 的 [tool.pytest.ini_options].pythonpath 已含 src/,
# 所以不需要 `pip install -e .` 也能 import model_switch。
pytest
```

`tests/conftest.py` 里的 autouse fixture 保证测试永远不会写你的真实 `~/.claude/settings.json`
—— 它会把所有路径重定向到每个测试的 tmp 目录,并在 teardown 时断言真实配置字节级一致。

## 局限性

- 只支持 Anthropic 兼容上游。纯 OpenAI 提供商(原生 OpenAI、DeepSeek、Ollama)需要
  协议翻译层,V1 不做。
- 内置 driver 只覆盖 Claude Code 和 OpenCode。其它 agent(Aider、Cursor 等)
  需要自己写 driver。