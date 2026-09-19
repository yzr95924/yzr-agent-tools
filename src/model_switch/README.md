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
# 1. 注册一个模型 —— API key 以明文形式存在 models.toml 里。
#    不带参数就是向导:粘 base URL 和 key,再从 OpenCode 的 catalog 缓存里按 host
#    列成编号菜单选模型(参数和档位从选中的条目派生)。upstream id 由你确认 ——
#    同一个模型各家拼法不同,回车采纳目录里的拼法,你的端点要别的就输入。
model-switch model add
#   Upstream API base URL: https://api.z.ai/api/anthropic
#   API key: sk-...
#   catalog: ~/.cache/opencode/models.json (updated 2026-09-18 17:27) — 23 model(s) on api.z.ai
#   Search models (Enter = list, 'all <term>' = every provider, 'skip' = type the id by hand): glm
#     1) zai/glm-4.7  GLM-4.7  ctx 200K
#     2) zai/glm-5.3  GLM-5.3  ctx 1M  tiers[low,high,max]  text+image
#   Pick a number [1] ('b' = back): 2
#   Upstream model id your endpoint expects (the pick is zai's spelling) [glm-5.3]:
#   Local name [glm-5.3]:
#   Context window in tokens (press Enter to skip) [1000000]:
#   Description (optional):
#
#   About to add 'glm-5.3':
#     upstream id     glm-5.3
#     base URL        https://api.z.ai/api/anthropic
#     context window  1M
#     variants        low, high, max
#   Proceed? [Y/n]: y

# 也可以一行 flags 全给(脚本 / CI 用法,零交互):
model-switch model add glm-z1-plus \
     --base-url https://open.bigmodel.cn/api/anthropic \
     --api-key sk-... \
     --model-name glm-4-plus \
     --description "GLM-4 Plus" \
     --context-window 200000

# 2. 激活它(不带名字会弹已配置模型的编号列表)
model-switch model use glm-z1-plus

# 3. 重启 Claude Code(Ctrl+D,然后再 `claude`)
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

model-switch model add [<name>] [flags]        # 不带参数 = 向导;flag 预答对应提问
     [--base-url <url>] [--api-key <KEY>] [--model-name <id>] [--description <text>]
     [--context-window <tokens>] [--provider <group-name>]
     [--catalog-provider <id>] [--no-catalog] [--yes]

model-switch model list                        # 列出所有模型 + 激活标记
model-switch model show [<name>]               # 无 name = 编号选择
model-switch model remove [<name>] [--yes]     # 无 name = 编号选择;删除前确认 [y/N]
model-switch model align [<name>] [--catalog-provider <id>]   # 无 name = 全部;按 OpenCode catalog 对齐

model-switch model use [<name>] [--driver NAME] [--all-drivers]   # 无 name = 编号选择;交互式默认 = 全部 driver;非 TTY / CI = 仅 claude-code

model-switch status [--driver NAME] [--all-drivers]
```

### 交互与脚本行为

- **每个提问都有对应 flag**。任意 flag 给了就跳过那道题;全 flag 调用零交互、零确认,
  脚本 / CI 行为与旧版一致。
- **非 TTY 永不阻塞**:菜单直接报错并提示"pass it as an argument";缺必填值时报错提示
  用 flag 传;`model use` / `remove` / `show` 不带名字在非 TTY 下报错(要靠 flag 或名字)。
- **写盘前确认**(仅 TTY):`model add` 先打印将写入的完整字段再问 `Proceed? [Y/n]`;
  `model remove` 问 `Remove model 'x'? [y/N]`(默认 no)。答 no / Ctrl-C 时什么都不写。
  `--yes`(-y)跳过这两个确认。
- **重名不静默覆盖**:TTY 下问 `Overwrite it? [y/N]`(默认 no);答 no 会重新问本地名字
  (已粘的 URL / key 不重问)。非 TTY 且没给 `--yes` 时直接报错
  `already exists (use --yes to overwrite)`。覆盖 = 整条替换(含 `provider` / `variants` /
  `modalities` 等 extra 字段),旧的手写字段不保留——想找回字段用 `model align` 重新推导。
  被覆盖的模型恰是当前激活模型时只打印一行提示(去跑 `model use`),`model add` 从不改
  agent 配置。
- **catalog 选择器**(`model add` 向导):默认按 base_url 的 host 过滤 catalog 缓存,列出该
  上游的模型;搜索支持多关键词(全部命中才显示);`b` 返回重搜,`skip`(或缓存缺失)回落到
  手打 model id 的旧流程。菜单最多显示 20 行,超出时提示缩小搜索。base_url 里没有 host
  (例如漏写 `https://`)时直接不进入选择器——无 host 可限定,选择器会把整个 catalog 当成你
  的上游列出来,不如回落到手打。
- **catalog 只供参数、档位与能力位,id 永远由你确认**:`catalog.derive` 只产出 context
  window / reasoning / 档位 / modalities / 两个能力位 / 显示名;upstream id、base_url、api_key
  是模型提供商的约定,同一个模型在不同 provider 下拼法不同(当前缓存里 `GLM-5.2` 有 21 种
  拼法,`Kimi K3` 有 15 种),无法从 catalog 推断。向导选中后把 id 预填成该行的拼法(回车采纳),
  你的端点要别的就输入,首尾空白会被去掉。id 会原样写进 `ANTHROPIC_MODEL` 与 OpenCode 的
  model 指针,填错的表现是每次请求都 model not found。脚本侧对应 `--model-name`(给了它就
  跳过选择器,参数靠 `--catalog-provider` / 缓存查找);`model align` 也只更新那几类参数,
  从不碰 id。
- **`all <关键词>` 放宽搜索范围**:在搜索提示处用 `all` 开头即对**全 catalog**搜索,不限
  host。宽搜结果里 host 匹配的行排在前(菜单只有 20 行,字典序会把你在配的上游挤掉),其
  余行标 `[other host]`;选中非本上游的行时打印一行 note,提示 context window 与
  modalities 是那个 provider 的声明、未必适用于你的上游,**id 的拼法同理**——下一问默认填
  的就是那一行的拼法,记得改成你端点认的。`all` 后面必须带关键词——全
  catalog 有几千条,列不完。默认 host 范围搜不到时,提示也会指向 `all <term>`。
  `skip` / `all` 都只匹配**首个 token**,所以 `skip-connections`、`allam-2-7b` 之类照常搜索。

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

向导(`model add`)会在**已存在同 `base_url` + 同 `api_key` 且声明了 provider 的模型**时
多问一行 `Provider group [...]`,回车即继承该组名——这正是同上游裂成 `yzr-<host>` +
`yzr-<host>-2` 两个块的来源,继承后两条合并进一个块。没有可加入的组时不问,手打流程不变;
`--provider` 照旧预答。**答 `-` 表示「不声明」**(`--provider -` 同义),这是交互/脚本里
去掉一个既有声明的唯一途径——否则继承没有退路,只能手改 `models.toml`;此时若同上游仍有
已声明组,会打印一行 note 说明该模型将另起一个 `yzr-<host>` 块。**非交互路径
(无 TTY / 脚本)不显示提示,但同样会继承**:同上游同 key 时组名由注册表现状决定,不再由
host 派生。两条路径都不会猜——同上游同 key 的两个 provider 块逐字节相同,合并没有歧义;
想强制另起一个组,先改 `api_key`。

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
比如 high/max。model-switch 不认识任何具体模型或上游:档位是纯数据,加模型/换上游都只改
toml。**声明了 `variants` 的模型,`ctrl+t` 给出的就只有你声明的这些档位(外加最后的未选档
Default 一站)**——OpenCode 自己也会给某些模型家族算一套内置档位,并与你的声明深合并;
driver 会在渲染时把其中你没声明的档位名静音掉(写 `disabled`,OpenCode 合并后立刻丢弃),
详见下面「四条要知道的语义」。

这些字段(都写在 `[[models]]` 条目里,都可选):

| 字段 | 作用 |
| --- | --- |
| `provider = "<名字>"` | 钉住 provider 分组名,id 即 `yzr-<名字>`(缺省按 base_url host 派生;同名字下所有模型必须同 base_url + api_key;删掉本字段或 `model add` 时答 `-` 即回到派生) |
| `reasoning = true` | 声明该模型支持推理(OpenCode 的一些行为以此为闸门:内置档位**只对 reasoning 模型**计算,picker 上也有标注) |
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
渲染进 model 块——声明之外的档位名下是自动补齐的静音键:

```json
"glm-5.3": {
  "reasoning": true,
  "variants": {
    "high": { "effort": "high" },
    "max": { "effort": "max" },
    "none": { "disabled": true }, "thinking": { "disabled": true },
    "low": { "disabled": true }, "medium": { "disabled": true },
    "xhigh": { "disabled": true }
  },
  "limit": { "context": 1000000, "output": 131072 }
}
```

**报错早于写配置**:`variants_preset` 引用了不存在的名字、preset 是空的、或某个档位的值不是
表(table;preset 与内联 `variants` 一视同仁)时,`model use`/`model add` 等直接报错退出,不写
任何 agent 配置——实测 OpenCode 遇到这类配置会整份拒载(`Expected object, got "high"
provider.<id>.models.<name>.variants.<tier>`)。档位**内容**不校验(原样透传,OpenCode 加载时
自己校验)。`model show <名字>` 只检查被查看的那个模型,所以别的模型写错也能单独查一个;
写入类命令则会检查整个 registry。

四条要知道的语义:

- **声明即全集:driver 把与内置规则的「叠加」变成了「接管」。** OpenCode 自己会给某些模型
  家族算一套档位(匹配面见下条,随版本变化)并与你声明的档位做深合并——同名档位你胜,但
  你没声明的档位名照样出现在 `ctrl+t` 里。所以 driver 渲染时会把**这套内置档位名中你未声明
  的那些**写成 `{ disabled = true }`:OpenCode 在合并之后立刻丢弃 disabled 档位,最终给出的
  正是你声明的集合。没声明 `variants` 的模型不受影响(内置档位照旧);档位名不在内置名单里
  的(比如 `off`)原样保留,不会被误伤。
- **内置规则按「渲进 model 块的 key / provider id / base_url」三面匹配。** key 就是本条的
  `name`(不是 `model_id`;`name = "glm-5.2"` 才命中 glm-5.2 的规则),provider id 是
  `yzr-<provider>`(未声明 `provider` 时由 host 派生),base_url 也参与——例如
  `api.kimi.com` / `api.moonshot.*` 与 provider id 含 `kimi`/`moonshot` 一样触发 kimi 的
  五档规则,所以「模型 key 里没有 kimi」并不等于不会命中。另有一批**抑制规则**按 key 匹配
  (qwen / glm / kimi / deepseek-v3 / minimax…,命中则干脆不给内置档位)。
  **别靠改 provider 组名来躲这些规则**:改名同时会丢掉 OpenCode 给该上游的请求基线(如
  kimi 默认带 `thinking: adaptive` + `effort: high`),而且 provider id 一变,旧会话里记的
  `providerID/modelID` 就指向不存在的 provider 了。
- **深合并是逐字段的:内置档位里你没覆盖的叶子键会留下,而且删不掉。** 同名档位中,你写的
  字段覆盖内置的同名字段,没写的保留(例如 kimi 内置的 `thinking.display = "summarized"` 会
  留在你的 `low`/`high`/`max` 里);想「减掉」某个内置叶子键没有办法,能整档丢弃的只有
  `disabled = true`。
- **`[variants_presets.*]` 是顶层表**,模型条目里引用它;对 `models.toml` 的任何重写
  (`model add/remove/import`)会保留它,但 dumper 会把它排到文件末尾(合法,只是位置变化)。

排查「`ctrl+t` 没反应」:

1. 你选的模型可能来自 **project 级 `opencode.json`** 或其它 provider——model-switch 只写
   全局 `~/.config/opencode/opencode.json` 的 `yzr-*` 命名空间,请在 picker 里选
   `yzr-*` 的模型;
2. 该模型的档位表是空的(没写 preset/variants;注意内置档位只对 `reasoning = true` 的模型
   计算);
3. 想看当前模型有哪些档位,不必盲按 `ctrl+t`:OpenCode 的 `variant_list` 键位默认**没绑**,
   在 `opencode.json` 里给它绑一个键即可列出,例如
   `"keybinds": { "variant_list": "ctrl+v" }`。

`model show <name>` 会打印 `reasoning:` 与 `variants: preset '...' -> high, max`——这行列的是
**声明档位**(渲染时自动静音的内置档位不列出,它们的唯一作用就是被丢掉);你自己写的
`disabled = true` 档位也不会混进列表,而是标注在括号里(`-> high, max (disabled: low)`)。

`ctrl+t` 的站点比这行多一站:循环走到最后一档后回到**未选档(Default)**状态——不覆盖任何
档位,请求走 provider 基线(kimi 基线是 `effort = "high"`,即 K3 的默认档,与 Kimi 文档的
`Default → high` 一致)。所以站点数 = 声明档位数 + 1,Kimi 文档的
`Default / low / high / max` 就是这么来的。没声明档位的 reasoning 模型会打印
`<none declared> (OpenCode's built-in tiers apply)`——防止「没有输出」被读成「没有档位」。

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

另外 `video` / `audio`:models.dev 条目里可能有,但 Anthropic messages 格式没有这两种 part,
声明只会让闸门放行、上游报错,所以不声明。

### 能力位与显示名(`temperature` / `attachment` / `display_name`)

catalog 条目里还有两个能力位和一个人类可读名,`model align` 会一并导出(只有 catalog 明确
声明 `true` 才写——OpenCode 对省略的 flag 按 false 处理,写 `false` 等于没写):

| catalog 字段 | models.toml | 渲染 |
| --- | --- | --- |
| `temperature: true` | `temperature = true` | model 块 `"temperature": true`。声明前 OpenCode 把它当"不支持":**不发 `temperature` 参数**,agent 里配的温度也被忽略 |
| `attachment: true` | `attachment = true` | model 块 `"attachment": true`。model 对象的 `capabilities.attachment`;OpenCode 对查不到的 provider 默认 false |
| `name`(如 `"Kimi K3"`) | `display_name = "Kimi K3"` | model 块 `"name": "Kimi K3"`,只是选择器里的标签;与 upstream id 相同时不写(OpenCode 自己回退到 key) |

`display_name` 只是标签:model 块的 **key 与 `api.id` 始终是 upstream id**,改它不会动请求
里的模型名。这几个字段都由 `model align` 维护,不需要手改。

### 与 OpenCode 内置对齐（自动）

OpenCode 自己维护一份 models.dev 快照（`~/.cache/opencode/models.json`，约每小时刷新），
它也是 OpenCode 推导内置模型字段的同一份数据。model-switch **只读这份缓存、不联网**，
从中导出 context window、reasoning、档位（variants）、modalities 与上面三个字段：

```bash
# 新增：只要本地名 + base_url + api_key;TTY 下 model id 从 catalog 菜单里选,
# 非 TTY / 给了 --model-name 时不弹菜单(--model-name 默认 = 本地名)
model-switch model add qwen3.8-max --base-url https://dashscope.aliyuncs.com/apps/anthropic --api-key <KEY>

# 已有模型重新对齐（无 name = 全部;幂等,已一致时零改动）
model-switch model align
```

导出规则（与 OpenCode 内置推导同源）：

| catalog 字段 | models.toml |
| --- | --- |
| `reasoning_options` 的 `effort.values` | 每值一档 `<v> = { effort = "<v>", thinking = { type = "adaptive" } }`；`none` 翻成 `none = { thinking = { type = "disabled" } }`（Anthropic 的 effort 枚举没有 `none`，而这正是 Kimi 文档给 `none` 的定义），`minimal` 跳过（没有对应形状，硬翻会名不副实） |
| `reasoning_options` 的 `toggle` | 不造档位（OpenCode 自己的推导在有 effort 时也丢弃 toggle），想要关思考的档位就手写一档 `off = { thinking = { type = "disabled" } }` |
| `limit.context` | `context_window`（按模型/套餐的最大值，如 kimi `k3` 是 `1048576`——需要 Pro/Allegretto 及以上套餐，超出套餐的上下文服务端返回 401） |
| `modalities.input` | `modalities`，剔掉 `video`/`audio`（Anthropic messages 无这两种 part） |
| `temperature` / `attachment` | 同名（仅 `true` 才写，见上一节） |
| `name` | `display_name`（仅当与 upstream id 不同才写，见上一节） |
| 只有 `budget_tokens` 或只有 toggle 声明 | 不造档位（打印提示，需要就手写） |

选择哪条 catalog 条目的规则：先按 base_url 的 **host** 收敛（同名模型常挂在几十个
provider 下且声明互相冲突）；host 匹配剩多条时，只有**推导结果逐字相同**才取字典序第一，
否则**拒绝并列出候选**，要求用 `--catalog-provider <id>` 钉选——绝不自动猜（猜错会静默
配错档位）。向导里的 `all <关键词>` 是这条规则唯一的放宽口子，且由你**主动**输入：工具自己
从不挑一个 host 不匹配的 provider，宽搜选中时还会打印 note 提醒字段来源。看候选、手工核对
时的原命令仍然可用：

```bash
jq -r 'to_entries[] | .value.models["qwen3.8-max"] as $m | select($m)
       | "\(.key)  api=\(.value.api)  reasoning=\($m.reasoning_options|tostring)  limit=\($m.limit|tostring)"' \
  ~/.cache/opencode/models.json
```

对齐的口径：对齐的对象是 **models.dev 官方 provider 条目**——OpenCode 只对它认识的 provider
读那份条目；对我们自建的 `yzr-*`，它只跑按 model id / provider id / base URL 匹配的家族规则。
两者对 kimi 恰好一致（家族规则给 low/medium/high/xhigh/max，静音后剩条目声明的
low/high/max），对 qwen/glm 则是我们补了家族规则本来不给的档位。以下差异是**有意或结构性**的：

- **`none` / `minimal` 不照抄**：OpenCode 在 Anthropic 路径会原样发 `effort: "none"` /
  `"minimal"`，而 adapter 的 effort 枚举只有 low\|medium\|high\|xhigh\|max——它自己这条是坏的。
  我们翻成关思考档 / 跳过。
- **`interleaved` 不写**：条目里的值（`{field: "reasoning_content"}`）是 OpenAI 兼容端点取
  reasoning 文本用的字段；Anthropic 路径由 `anthropic-beta: interleaved-thinking-2025-05-14`
  头处理，OpenCode 对 `@ai-sdk/anthropic` 会自己加。
- **`cost` / `family` / `release_date` 不写**：纯显示/元数据（价格还会过期）；`structured_output`
  则是**写不了**——OpenCode 的 model 配置 schema 没有这个字段，adapter 按内置模型表判断，
  只认识 `claude-*`。
- 档位 body 与内置档位是**叶子级深合并**：同名内置档位里你没写的叶子会跟过来。kimi 上这补回
  `display: "summarized"`（与官方条目一致，好事）；走 anthropic 兜底档的模型（如
  `deepseek-v4.1-flash`）会带进 `budgetTokens`——我们的 adaptive 档会被 adapter 剥掉它（无
  影响）；但**手写 `thinking = { type = "enabled" }` 而不写 `budget_tokens` 会真的继承内置的
  16000/31999**，思考被封顶——要么写全，要么别用 `enabled`。
- 官方条目的 `limit.output` 不复刻，统一 `131072`：线上 `max_tokens = min(limit.output,
  32000)`，catalog 值再大也是 32000，请求实际一样。

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
