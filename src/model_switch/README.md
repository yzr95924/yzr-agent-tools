# model-switch

快速切换 Claude Code 使用的模型——无需手动编辑 `~/.claude/settings.json`。

`model-switch` 是一个轻量 CLI：把 Anthropic 兼容的上游模型定义存在自己的配置目录里，
然后在你执行 `model-switch model use <name>` 时，把当前选中的模型写入 Claude Code
的 `settings.json` 的 `env` 块。重启 Claude Code，它就在跟新模型对话了。

## 安装

```bash
# 在本仓库下,运行该工具的自包含安装脚本(写 wrapper + 装补全 + 加 PATH 块)
bash scripts/model-switch.sh install
source ~/.bashrc   # 或 ~/.zshrc

# 验证
model-switch --help

# 卸载
bash scripts/model-switch.sh uninstall
```

需要 Python 3.7+。安装脚本很薄:写一个 `bin/model-switch`（4 行 bash wrapper,
用 `PYTHONPATH=$REPO/src` 跑 `python3 -m model_switch`）并往 shell rc 里加一段幂等的
PATH 块。不创建虚拟环境,不调 `pip install`。

### 运行时 / 开发依赖(自行安装)

安装脚本**不会**安装任何 Python 包。运行 `model-switch` 之前请确保:

| 用途 | Python < 3.11 | Python ≥ 3.11 |
| --- | --- | --- |
| 运行 CLI | `pip install --user 'tomli>=1.1'` | (仅标准库) |
| 跑测试 | `pip install --user pytest pytest-cov` | 同上 |

如果在 Python < 3.11 上缺 `tomli`,第一次跑 `model-switch` 会在 `import tomli` 处
抛 `ImportError`——装上再重试。

### Shell 补全(bash + zsh + fish)

`model-switch.sh install` 还会装好 tab 补全:

- **bash** — 软链到 `~/.local/share/bash-completion/completions/`(macOS + Homebrew
  时为 brew prefix 下的 bash-completion 目录),**并且** 在 `~/.bashrc`
  的 PATH 块里 source 一份,所以即使没装 bash-completion 包也能用。
- **zsh** — 软链到 `~/.zfunc/_model-switch`,`~/.zshrc` 的 PATH 块里把 `~/.zfunc`
  加进 `fpath` 并跑 `compinit`(macOS 默认 shell 即 zsh,开箱即用)。
- **fish** — 软链到 `~/.config/fish/completions/`(自动加载)。

补全覆盖子命令、flag、`--driver` 取值,以及 `model use/show/remove` 的模型名。
动态候选项直接由 CLI 自身产出(隐藏的 `model-switch _complete models|drivers` 管道
命令),所以始终和你 `models.toml` 里的内容一致。`model-switch.sh uninstall` 会清理这些软链和
rc 块。脚本本体在 `completions/`,想自己接也可以。

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
  ANTHROPIC_BASE_URL              = https://open.bigmodel.cn/api/anthropic
  ANTHROPIC_AUTH_TOKEN            = sk-...
  ANTHROPIC_MODEL                 = glm-4-plus
  ANTHROPIC_DEFAULT_SONNET_MODEL  = glm-4-plus
  ANTHROPIC_DEFAULT_OPUS_MODEL    = glm-4-plus
  ANTHROPIC_DEFAULT_HAIKU_MODEL   = glm-4-plus
  ANTHROPIC_SMALL_FAST_MODEL      = glm-4-plus
```

## 命令一览

```
model-switch init                              # 创建 ~/.config/model-switch/

model-switch model add <name> \
     --base-url <url> \
     --api-key <KEY> \
     [--model-name <id>] \
     [--description <text>] \
     [--context-window <tokens>] \
     [--provider <group-name>] \
     [--catalog-provider <id>] [--no-catalog]

model-switch model list                        # 列出所有模型 + 激活标记
model-switch model show <name>
model-switch model remove <name>
model-switch model align [<name>] [--catalog-provider <id>]   # 无 name = 全部;按 OpenCode catalog 对齐

model-switch model use <name> [--driver NAME] [--all-drivers]   # 交互式默认 = 全部 driver;非 TTY / CI = 仅 claude-code

model-switch status [--driver NAME] [--all-drivers]
```

## 写进 settings.json 的内容

`env` 块下,加一个顶层 `model`(对应现代的单模型形态):

- `ANTHROPIC_BASE_URL` — 上游 base URL
- `ANTHROPIC_AUTH_TOKEN` — `models.toml` 里这个模型对应的 `api_key`
- `ANTHROPIC_MODEL` — `<name>`,或当 `context_window >= 1_000_000` 时为 `<name>[1m]`
- `ANTHROPIC_DEFAULT_{SONNET,OPUS,HAIKU}_MODEL` + `ANTHROPIC_SMALL_FAST_MODEL` —
  把 Claude Code 的**每个模型档位**都钉到同一个 `<name>`(含 `[1m]` 后缀)。Claude Code
  的辅助调用(auto 模式的 Bash 安全分类器、标题/摘要生成等)经这些档位解析;不覆盖就会回落到
  内置 Claude id(如 `claude-sonnet-5[1m]`),自定义上游提供不了 → 表现为
  "auto mode temporarily unavailable"。钉死它们,这些调用才跟着走你的上游。
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
(`$XDG_CONFIG_HOME/opencode/opencode.json`)里写 `yzr-<上游slug>` 的 provider 块(带
`@ai-sdk/anthropic` adapter),并把解析出的 API key 直接写入 `apiKey`——密钥是落盘的,
请把文件权限收紧。模型定义(`models.toml`)在 Claude Code 和 OpenCode driver 之间共享,
所以切换 agent 不用重新注册模型。

**OpenCode 是 catalog 型 agent。** 与 Claude Code 的单槽不同,OpenCode 的模型 picker
里能看到所有已配置的 provider。所以 model-switch 把 `models.toml` 里的**全部模型**按
上游分组镜像进 `yzr-*` 命名空间——`baseURL`/`apiKey` 是 provider 级字段,共享一个块的
模型必须同上游同 key;每组一个 provider。**provider id 的确定方式是「声明优先,缺省派生」**:

- 模型条目里写 `provider = "<名字>"` → id 即 `yzr-<名字>`(名字只写 slug,`yzr-` 前缀
  由工具加;允许小写字母/数字/连字符,因为 id 会拼进 `yzr-<名字>/<模型>` 指针);
  同一名字下的所有模型必须共享 `base_url` 和 `api_key`——**key 轮换漏改一处会显式报错**,
  不会静默裂成两个 provider;
- 不写 `provider` → 按上游 host 派生(`api.z.ai`→`yzr-zai`、`api.kimi.com`→`yzr-kimi`、
  `dashscope.aliyuncs.com`→`yzr-dashscope`),不同组撞名时按排序加 `-2`/`-3` 后缀
  (渲染结果稳定;已声明的名字优先占用,派生 slug 让位)。

**写 `provider` 的价值是 id 稳定**:以后换 `base_url`(换网关/换区域),id 不变,
外部引用(脚本里的 `opencode run -m yzr-<名字>/...`、项目级 opencode.json、文档)不会断;
不写则 host 一变 id 就变。声明成与派生值相同的名字,渲染结果**逐字节不变**——旧文件可以
逐步加声明,零风险。同组内的模型名必须唯一(它是 `models` 映射的键)。`config["model"]`
只作为默认指针指向激活的模型,形如 `yzr-zai/glm-5.3`。你在 OpenCode 里用 `/models`
随时切,不必回 CLI:

- `model use <name>` — 全量 reconcile + 把默认指针指到该模型;
- `model add` / `model remove` / `model import` — 同样触发 reconcile:新增的模型立刻进
  picker;删除的模型其 provider 连同明文 key 一起从文件里消失,不会残留。
- `config["model"]` 默认指针:指向的模型还在就保持;被删了则落到剩余模型的第一个;一个都不
  剩就删掉该键。**默认指针只会被 `model use` 改动**——add/remove/import 的 reconcile 从不
  碰你手动设的外来默认模型。
- `yzr-*` 命名空间归 model-switch 管:任何 `yzr-*` 前缀(含旧版单槽的裸 `yzr` 和旧版
  每模型一个的 `yzr-<model_id>`)都会被 reconcile 回收,请别在这个前缀下自建 provider。
  `yzr-*` 之外的一切原样保留。
- 镜像只作用于已存在的 `opencode.json`:`model add` 不会凭空创建一个你没用过的全局配置文件,
  只有 `model use --driver opencode`(或 interactive all)才创建它。

### Effort 档位(variants)

OpenCode 的模型可以带若干「档位」(variant),用 `ctrl+t`(`variant_cycle`)循环切换——
比如 high/max。model-switch 不认识任何具体模型或上游:它把 `models.toml` 里声明的东西
**原样透传**进 `opencode.json` 的 model 块,所以档位是纯数据,加模型/换上游都只改 toml。

这些字段(都写在 `[[models]]` 条目里,都可选):

| 字段 | 作用 |
| --- | --- |
| `provider = "<名字>"` | 钉住 provider 分组名,id 即 `yzr-<名字>`(缺省按 base_url host 派生;同名字下所有模型必须同 base_url + api_key) |
| `reasoning = true` | 声明该模型支持推理(OpenCode 的一些行为以此为闸门,如内置档位规则与 picker 上的标注) |
| `variants_preset = "<名字>"` | 引用顶层 `[variants_presets.<名字>]` 定义的档位表(推荐) |
| `variants = { ... }` | 直接内联档位表(逃生舱;与 preset 同时存在时,逐字段覆盖 preset) |

档位形状写一次、所有模型引用:

```toml
[variants_presets.z-effort]
high = { effort = "high" }
max  = { effort = "max" }

[[models]]
model_id = "glm-5_3-1m"
name = "glm-5.3"
# ...
reasoning = true
variants_preset = "z-effort"
```

`model use` 时 preset 在内存里展开成 `variants` 字典(模型自己内联的字段级覆盖 preset),
渲染进 model 块:

```json
"glm-5.3": {
  "reasoning": true,
  "variants": { "high": { "effort": "high" }, "max": { "effort": "max" } },
  "limit": { "context": 1000000, "output": 131072 }
}
```

**报错早于写配置**:`variants_preset` 引用了不存在的名字、preset 是空的、或某个档位的值不是
表(table;preset 与内联 `variants` 一视同仁)时,`model use`/`model add` 等直接报错退出,不写
任何 agent 配置——实测 OpenCode 遇到这类配置会整份拒载(`Expected object, got "high"
provider.<id>.models.<name>.variants.<tier>`)。档位**内容**不校验(原样透传,OpenCode 加载时
自己校验)。`model show <名字>` 只检查被查看的那个模型,所以别的模型写错也能单独查一个;
写入类命令则会检查整个 registry。

三条要知道的语义:

- **与 OpenCode 内置规则是叠加,不是接管。** OpenCode 自己也会给某些模型家族生成档位
  (按模型名匹配,随版本变化),你的声明与它 deep merge——同名档位你胜,你没声明的档位名
  仍可能出现。要静音某个档位,在它下面写 `disabled = true`。
- **匹配内置规则的永远是 `name`,不是 `model_id`**(`name` 是渲进 model 块的 key)。比如
  `name = "glm-5.2"` 才会命中 glm-5.2 的内置规则,`glm-5_2` 不行。
- **`[variants_presets.*]` 是顶层表**,模型条目里引用它;对 `models.toml` 的任何重写
  (`model add/remove/import`)会保留它,但 dumper 会把它排到文件末尾(合法,只是位置变化)。

排查「`ctrl+t` 没反应」:

1. 你选的模型可能来自 **project 级 `opencode.json`** 或其它 provider——model-switch 只写
   全局 `~/.config/opencode/opencode.json` 的 `yzr-*` 命名空间,请在 picker 里选
   `yzr-*` 的模型;
2. 该模型的档位表是空的(没写 preset/variants,或内置规则也没给它);
3. 想看当前模型有哪些档位,不必盲按 `ctrl+t`:OpenCode 的 `variant_list` 键位默认**没绑**,
   在 `opencode.json` 里给它绑一个键即可列出,例如
   `"keybinds": { "variant_list": "ctrl+v" }`。

`model show <name>` 会打印 `reasoning:` 与 `variants: preset '...' -> high, max`,便于
改完 toml 后确认最终会渲染什么;被 `disabled = true` 静音的档位不会混进列表,而是标注在
括号里(`-> high, max (disabled: low)`),与 OpenCode 实际给出的档位一致。

**Claude Code 是单槽 agent。** `model add/remove/import` 不碰它的配置;唯一例外——被删除的
模型正是当前 active 时,`remove`/`import replace` 会把 model-switch 自己管理的四个键
(`env.ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL / ANTHROPIC_MODEL` + 顶层 `model`)清掉,
避免已删除模型的 key 残留,同时清空 state.toml 的 active_main。非 active 模型的删除对
Claude Code 无影响(单槽天然无残留)。

### 输入模态(modalities)

OpenCode 发请求前会给消息里的**非文本部分**过一道闸门:按 model 块的
`capabilities.input[<模态>]` 判断该 part 能不能发。**没声明的模态会被替换成一条文本**
(`ERROR: Cannot read "x.png" (this model does not support image input). Inform the user.`)——
粘贴图片不报错,但模型看到的不是图;要真的能用图片/PDF,得显式声明:

```toml
[[models]]
model_id = "qwen3.8-max"
# ...
modalities = { input = ["text", "image", "pdf"], output = ["text"] }
```

渲染进 model 块:

```json
"qwen3.8-max": {
  "modalities": { "input": ["text", "image", "pdf"], "output": ["text"] }
}
```

取值限 OpenCode schema 的枚举:`text` / `audio` / `image` / `video` / `pdf`;`input`、`output`
两个键都可选,列表不可为空。非法值(未知键、未知模态、空列表)在 `model use` / `model add`
时就报错退出、不写任何配置——这类错会让 OpenCode 整份拒载。

声明必须**真实**:上游不接受的模态不会在这里报错,而是每次带该附件时请求直接 400;不声明
则只是静默降级成上面那句 ERROR 文本。所以先用真实附件请求验证过再写。

三个**不**透传的字段(都有具体原因,别当成缺口):

| 字段 | 为什么不用 |
| --- | --- |
| `attachment` | OpenCode 二进制里只出现在配置归一化/合并处,没有消费点;真正起门禁作用的是 `modalities` |
| `temperature` | 省略时 OpenCode 按"不支持"处理(不发 `temperature` 参数,用上游默认);只有要让 agent 的温度设置生效才需要声明 |
| `interleaved` | 它声明"从响应哪个字段取 reasoning 文本",是 OpenAI 兼容端点的形状(`reasoning_content`);我们走 Anthropic 协议、reasoning 是标准 thinking 块,照抄可能反而取不到 |

另外 `video` / `audio`:models.dev 条目里可能有,但 Anthropic messages 格式没有这两种 part,
声明只会让闸门放行、上游报错,所以不声明。

### 与 OpenCode 内置对齐（自动）

OpenCode 自己维护一份 models.dev 快照（`~/.cache/opencode/models.json`，约每小时刷新），
它也是 OpenCode 推导内置模型字段的同一份数据。model-switch **只读这份缓存、不联网**，
从中导出 context window、reasoning、档位（variants）和 modalities：

```bash
# 新增：只要本地名 + base_url + api_key;--model-name 默认 = 本地名
model-switch model add qwen3.8-max --base-url https://dashscope.aliyuncs.com/apps/anthropic --api-key <KEY>

# 已有模型重新对齐（无 name = 全部;幂等,已一致时零改动）
model-switch model align
```

导出规则（与 OpenCode 内置推导同源）：

| catalog 字段 | models.toml |
| --- | --- |
| `reasoning_options` 的 `toggle` | 一档 `off = { thinking = { type = "disabled" } }` |
| `reasoning_options` 的 `effort.values` | 每值一档 `<v> = { effort = "<v>", thinking = { type = "adaptive" } }`（跳过 `none`/`minimal`） |
| `limit.context` | `context_window` |
| `modalities.input` | `modalities`，剔掉 `video`/`audio`（Anthropic messages 无这两种 part） |
| 只有 `budget_tokens` 声明 | 不造档位（打印提示，需要就手写） |

选择哪条 catalog 条目的规则：先按 base_url 的 **host** 收敛（同名模型常挂在几十个
provider 下且声明互相冲突）；host 匹配剩多条时，只有**推导结果逐字相同**才取字典序第一，
否则**拒绝并列出候选**，要求用 `--catalog-provider <id>` 钉选——绝不自动猜（猜错会静默
配错档位）。看候选、手工核对时的原命令仍然可用：

```bash
jq -r 'to_entries[] | .value.models["qwen3.8-max"] as $m | select($m)
       | "\(.key)  api=\(.value.api)  reasoning=\($m.reasoning_options|tostring)  limit=\($m.limit|tostring)"' \
  ~/.cache/opencode/models.json
```

已知限制（设计如此）：catalog 描述的是各 provider **声明**的端点（通常是其 OpenAI 兼容
API），我们走 Anthropic 兼容路径——档位**名**是家族级的，wire 形状由 driver 翻译；接受 ≠
生效（上游可能静默 clamp）；缓存过期不自动刷新，`align` 会打印其 mtime。

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
