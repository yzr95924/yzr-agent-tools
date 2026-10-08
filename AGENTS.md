# AGENTS.md — yzr-agent-tools 仓库规约

围绕 AI coding agent（Claude Code / OpenCode / Qoder CLI）的本地运维工具集合。
README 的总览表 + 各 `src/<tool>/README.md` 是工具级权威文档；本文件只写**跨工具的
仓库规约**，即 agent 不看多个文件就推断不出来的那些。

## 结构

```
src/<tool>/        每工具一个自包含 Python 包（cli.py 入口、paths.py 路径解析、
                   drivers/ agent 适配、各工具各自的 _compat.py / drivers/_atomic.py）
scripts/<tool>.sh  自包含 install/uninstall 脚本（写 wrapper + shell 补全 + rc PATH 块；
                   无 venv、无 pip）
bin/<tool>         install 生成的 4 行 bash wrapper，gitignored——fresh clone 后不存在
completions/       bash/zsh/fish 补全源
docs/              设计文档（mcp-plugin-mgr、opencode-plugins）
tests/             pytest；conftest.py 是全仓测试隔离的枢纽
```

- **工具间刻意重复代码**：`_compat.py`（TOML 读写）、`drivers/_atomic.py` 每个工具各留
  一份拷贝保持独立，**不要跨工具抽公共包 / DRY 化**，除非用户明确要求。
- `src/yzr_agent_style/templates/AGENTS.md` 是安装到三个 agent 全局规则文件的指令
  模板真源，改它等于改所有用户会话的行为。

## 命令

```bash
pytest                                    # 无需 venv / pip install -e .（pyproject 已配
                                          # pythonpath = ["src", "tests"]）
pytest tests/test_cli.py::test_name       # 单测直接跑
bash scripts/<tool>.sh install|uninstall  # 每工具的安装/卸载
```

- **fresh clone 后跑 pytest 之前，先执行 `bash scripts/model-switch.sh install` 和
  `bash scripts/mcp-plugin-mgr.sh install`**：`bin/<tool>` 是 gitignored 产物，而
  `tests/test_install.py`、补全内容测试会直接读 `bin/model-switch`。CI（.github/
  workflows/tests.yml）在 pytest 前就是这么做的。
- Python 下限 3.7、运行时仅标准库：<3.11 需 `tomli>=1.1`（测试依赖 `pytest
  pytest-cov`）。CI 矩阵 3.7/3.8/3.11/3.12——**不要用 3.8+ 语法**；`typing.Protocol`
  必须放在 try/except 兜底 shim 里，`tests/test_py37_compat.py` 用 AST 守卫 shim 结构。

## 测试隔离（最高优先级规约）

`tests/conftest.py` 的 autouse fixture 对每个测试：把所有工具的 paths 函数重定向到
tmp、用 tmp 路径替换 registry 里的 driver 单例、teardown 时用 mtime+sha256 断言真实
用户配置（`~/.claude/settings.json`、`~/.claude.json`、`~/.config/opencode/opencode.json`、
`~/.qoder/settings.json`、三个全局指令文件、`~/.config/opencode/plugins/` 等）字节未变。

- **新增工具或新增用户级写入路径：必须同步进 conftest 的重定向 + `REAL_*` 快照清单**，
  否则测试会写真实配置，把用户正在运行的 agent 会话搞坏。
- 确实要测真实路径解析才标 `@pytest.mark.no_isolation`（先例：test_paths.py、
  test_mcp_plugin_mgr_paths.py）。
- 补全脚本测试需要本机 zsh/fish，缺失时自动 skip（CI 会 apt 安装）。
- llmw_connect_mgr 不进 conftest：走自己的 env 测试缝 `LLMW_CONNECT_MGR_HOME /
  _SYSTEMD_DIR / _UNIT / _LOG`（src/llmw_connect_mgr/paths.py）。

## Driver 与写盘约定

- **driver 一律 lazy 注册**：import 时不得实例化指向 `Path.home()/...` 的 driver，
  首次使用时由 `cli._ensure_default_registered` 之类调 `registry.register(...)`。
  import 即注册会绕过 conftest 重定向、漏隔离。
- 原子写：`.tmp` + `os.replace()`；读配置把未知键收进 `extra` 桶、落盘原样回写
  （theme/plugins/自定义 env 不许丢）。
- TOML dumper 是手写的（stdlib 无写 API，tomllib 只读），改存储格式要保证 round-trip
  无损，并跑 `pytest --cov=model_switch` / `--cov=mcp_plugin_mgr` 对应工具。
- OpenCode 侧按 **V2 原生形状**：MCP 写 `mcp.servers`、stdio 的环境变量键是
  `environment` 不是 `env`；V1 兼容路径已删除，不要加回去。
- model-switch 的 opencode driver 从 OpenCode 的 sqlite catalog
  （`$XDG_DATA_HOME/opencode/opencode.db`，表 `kv`、键 `models-dev:catalog`）派生模型
  字段：**只读、不发网络请求**。

## 跨会话记忆（索引）

<!-- 下方 @引用若未被自动展开（看不到正文），用 Read 工具读取 -->
@MEMORY/MEMORY.md

## 其它

- Markdown 校验用仓库根 `.markdownlint.jsonc`（MD013/MD041/MD040 已放宽）；文档正文
  中文，代码与 commit message 英文。
