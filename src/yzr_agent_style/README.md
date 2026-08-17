# yzr-agent-style

把一份全局指令模板安装到各 AI coding agent 的全局规则文件里——用 marker 块托管，
**不覆盖**你手写的内容。

## 它做什么

三个 agent 各有自己的全局指令文件,但内容往往想共享同一份"个人工作习惯":

| Agent | 全局规则文件 |
|---|---|
| Claude Code | `~/.claude/CLAUDE.md` |
| OpenCode | `~/.config/opencode/AGENTS.md` |
| Qoder CLI | `~/.qoder/AGENTS.md` |

`yzr-agent-style` 在**每个**文件里维护一段由 HTML 注释标记的块:

```markdown
<!-- yzr-agent-style begin -->
# yzr-agent-style
<!-- yzr-agent-style end -->
```

块内内容来自仓库里的模板真源 `src/yzr_agent_style/templates/AGENTS.md`;
块外的内容(你自己写的)一行不动。`install` 可重复执行——模板改了,重跑一次就同步到所有文件。

## 安装

```bash
# 安装/同步模板到三个全局文件(已存在且无块 → 末尾追加;有块 → 替换块内)
bash scripts/yzr-agent-style.sh install

# 卸载(剥掉块;文件只剩块则删除;无块的文件不动)
bash scripts/yzr-agent-style.sh uninstall
```

需要 Python 3.7+(仅标准库,无第三方依赖)。脚本很薄:一行 `PYTHONPATH` 设置 +
`python3 -m yzr_agent_style`,不写 wrapper、不动 PATH、不装补全。

## 使用约定

- 模板真源是 `templates/AGENTS.md`——要改全局规则,改它,然后重跑 `install`。
- 目标文件里 `<!-- yzr-agent-style begin/end -->` 之间的内容**不要手改**,
  下次 `install` 会整块覆盖;手写内容请放在块外。
- `install` 遇到目标 agent 的配置目录不存在时跳过该目标(不主动创建目录)。

## 跑测试

```bash
pytest tests/test_yzr_agent_style.py -v
```

`tests/conftest.py` 的 autouse fixture 会把三个目标路径重定向到 tmp,并断言测试
绝不触碰你的真实全局文件。