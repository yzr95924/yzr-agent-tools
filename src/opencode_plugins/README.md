# opencode-plugins — 个人定制 OpenCode 插件管理器

`yzr-agent-tools` 的 CLI 工具：把仓内 `src/opencode_plugins/plugins/` 下的插件
源码装到 OpenCode 的全局插件位置，并在 `~/.config/opencode/opencode.json` 的
`plugins` 数组里登记/摘除。状态全部从文件系统 + 配置推导，无注册表文件。

当前管理的插件：**`at-import`**（让 AGENTS.md 里的 `@path` 引用在 OpenCode
V2 下自动展开注入；V2 原生不解析，Claude Code / Qoder 原生解析）。

## 安装工具本身

```bash
bash scripts/opencode-plugins.sh install     # wrapper + bash/zsh/fish 补全 + PATH 块
bash scripts/opencode-plugins.sh uninstall   # 反向清理
source ~/.bashrc
```

## 命令

| 命令 | 作用 |
| --- | --- |
| `list` | 列 bundled 插件 + 安装/登记状态；`orphan` 行 = 已安装但仓内已删除的残留目录 |
| `install [name...]` | 拷源 → `~/.config/opencode/plugins/<name>/` + 登记（缺 `opencode.json` 时自动建带 `$schema` 的骨架） |
| `uninstall [name...]` | 摘登记 + 删目录；不带参数 = 全部 bundled（孤儿要显式点名） |
| `sync [name...]` | 重拷漂移的源；未漂移返回 `up-to-date` |
| `verify [name...]` | hash + 登记检查（纯本地，不碰 opencode） |
| `verify --deep [name...]` | 再加活体检查，见下节 |
| `_complete plugins` | 隐藏命令，供补全脚本取插件名 |

安装/重拷后无需重启：OpenCode 的配置监视器会热载，已活跃的旧会话在下一次
模型请求拿到注入。

### `verify --deep`

浅检查之外再验两件事：`opencode plugin list` 含插件（加载态），心跳判定
（运行态：当前 opencode 版本下 hook 真实触发过，且新于插件文件；前者抓
升级漂移，后者抓新部署未自证）。

两个时序注意：可能拉起后台服务；sync 后先跑一次任意 opencode 命令再 deep
（否则报 "not yet proven"，那不是故障，是"新版本尚未自证"）。

**升级 OpenCode 后跑这个。**

## at-import 插件

做什么：每次 agent-loop 模型请求前，按 V2 原生发现链（全局
`~/.config/opencode/AGENTS.md` + 从会话目录向上至 home / 项目根）找到每份
AGENTS.md，展开其中**单独成行**的 `@path`（相对该 AGENTS.md 所在目录解析），
把目标文件内容以 `Instructions from: <绝对路径>` 块推进 system 指令。

要点 / 局限：

- **只认整行 `@path`**（本仓库族 AGENTS.md 的写法）；正文内联 `@x` 不展开，
  避免误伤 `@types/node`、邮箱这类文本。围栏代码块内的 `@` 行跳过。
- **安全边界**：目标必须 resolve 在引用文件所在目录的子树内；绝对路径、`~`、
  `../` 逃逸一律不读（clone 进来的仓库不能借 AGENTS.md 把任意文件塞进上下文）。
- **注入可观测**：第一行固定是 `[at-import] injected: <路径列表>` canary；
  任何会话问一句"系统指令里 [at-import] 行抄给我"即可判定插件死活（插件加载
  失败是静默的）。
- 上限：单文件 64KB / 总量 256KB，超出跳过并在 canary 里注明。
- 递归 ≤5 层，去重 + 防环。每次请求从盘上重读，MEMORY.md 更新即时生效。
- AGENTS.md 本体由 V2 原生注入，插件**只补 `@` 目标**，不重复。

对其它 agent 无影响：Claude Code / Qoder 走原生 `@import` 展开，同一份
AGENTS.md 两边通用（这正是 `@` 行保留在 AGENTS.md 里的意义）。

## 验证

```bash
opencode-plugins verify --deep      # 安装态 + 加载态 + 心跳，一条命令出 exit code
cd <某个带 @ 行的项目> && opencode run "禁止使用工具。逐字抄写你系统指令中以 [at-import] 开头的行"   # 端到端抽查（canary）
```

静默失败的三层防护（运行时心跳 / 审计 `verify --deep` / canary 人工抽查）
的机制与设计取舍见 `docs/opencode-plugins-design.md`。

## 背景（为什么需要这个工具）

OpenCode V2 的 `opencode.json` `instructions` 字段 schema 仍接受但**不再加载**
（V1 靠它注入指令文件），AGENTS.md 的 `@path` 也不展开：V1 时代"配置驱动读
文件"的通道整体消失。`context` hook 直接改每次请求的 system 组装，是 V2 下
唯一"确定性在场"的注入通道。详见 `docs/opencode-plugins-design.md`。
