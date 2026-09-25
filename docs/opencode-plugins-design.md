# opencode-plugins 设计说明

> 2026-09-24。小型工具，单档记录需求裁定与关键证据，不走 full 模板。

## 需求

AGENTS.md 生态里 `@path` 行（`@MEMORY/MEMORY.md`、`@scripts/SCRIPTS.md`）是
wiki 记忆 / 脚本索引的入口。Claude Code / Qoder 原生展开；OpenCode V1 靠
`opencode.json` 的 `instructions` 字段加载。**OpenCode V2 两条都没了**——
V2 升级后本组 wiki 的记忆索引在 opencode 会话里静默丢失（2026-09-16 的
agent-tools/MEMORY/opencode-instruction-loading.md 记录了 V1 双通道机制）。

要求：不改 AGENTS.md 格式（保持工具中立）、注入确定性（不依赖模型自觉去
Read）、个人可维护。

## 关键裁定

| 决策 | 选择 | 理由 |
| --- | --- | --- |
| 注入通道 | V2 插件 `context` hook 改 `event.system` | 官方文档 "Modify assembled system instructions ... immediately before model dispatch"；V2 下唯一确定性通道（instructions 字段失效、`{file:}` 够不到 ambient、TUI composer `@` 是交互附件） |
| 插件形态 | `export default { id, setup }` 纯对象，零 import | 实测 2.0.15：loader 接受纯对象；`import "@opencode/plugin"` 会 "Cannot find package"（V2 server 无该包别名注入，只有 `/tui` 有）——零依赖消除整类加载失败 |
| 安装位置 | `~/.config/opencode/plugins/at-import/` + 全局 `plugins` 数组登记 `"./plugins/at-import"` | 显式登记是确定路径（相对配置文件目录解析，二进制源码确认）；全局一份覆盖所有项目 |
| 发现链 | 复刻 V2 原生：全局 AGENTS.md + location 向上至 home（出 home 则至 project 根） | wiki/workspace 两层 AGENTS.md 的 `@` 行都要展开；相对各文件自身目录解析 |
| 安全边界 | 只允许引用文件目录子树内的相对路径 | clone 仓的 AGENTS.md 不得借 `@` 把任意文件（如 `~/.ssh/id_rsa`）读进上下文；对应 Claude Code external-import 审批的静态化 |
| 失败模式 | hook 内全 try/catch，坏一步注入一步；canary 行提供可观测 | 插件绝不拖垮 agent loop；加载失败静默（实测确认），`[at-import] injected: ...` 首行可一句话验尸 |
| 新鲜度 | 每次 hook 从盘重读（不缓存） | 被注入的都是 KB 级小文件；MEMORY.md 编辑即时生效，省去 watcher |
| 状态存储 | 无注册表，文件系统 + opencode.json 推导 | 少一个漂移源；verify 直接复算 |

## 验证记录（2026-09-24，opencode v2.0.15 本机实测）

1. 纯对象插件被加载（`opencode plugin list` 可见；import `@opencode/plugin`
   则 WARN failed to load，日志 `ResolveMessage: Cannot find package`）。
2. `context` hook 在首次模型调用前触发；`event.system.push` 的文本真实到达
   模型（探针 CANARY 被回显；测试会话让模型逐字抄 canary 行成功）。
3. 端到端：agent-tools wiki 目录下 `opencode run` 注入 3 文件——
   wiki `MEMORY/MEMORY.md`、`scripts/SCRIPTS.md`、workspace `MEMORY/MEMORY.md`，
   路径相对各自 AGENTS.md 解析正确。
4. 负例：围栏代码块内 `@FENCE-NOT-INJECTED.md` 不注入；
   `@../../etc/hostname` 逃逸被拒（模型确认内容不在指令中）。
5. 配置变更热载：`opencode-plugins install` 改全局 opencode.json 后，下一次
   `opencode run` 无需重启即生效。

## 风险与维护

- **V2 plugin API 演进**：`context` hook 未标 experimental、有文档示例背书，
  属稳定面；升版本后跑 `opencode-plugins verify --deep`（心跳双条件判定抓
  升级漂移）+ canary 抽查兜底。
- **静默失败防护（三层）**：运行时心跳（`deep.py` 注释 + README"验证"节）；
  审计 `verify --deep`；人工 canary。设计时有意砍掉的：bun 语法闸（与
  deep 检查重复、给 stdlib-only 工具引入外部可执行依赖）、按 location 的
  心跳 map（last-write-wins 单条足够）、cron 守护（仓库无 daemon 哲学）、
  verify 内模型 echo 探针（小模型实测会读花 canary，概率性探测器比没有
  更糟）。
- **原生 @import 若回归**：会双注入（无害、费 token）；`uninstall` 即退路。
- **模型注意力**：本工具保证的是"内容在场"（与 CC `@import`、V1
  `instructions` 同级），遵守程度仍是模型问题。
- V2 只认 `AGENTS.md`（不再 fallback `CLAUDE.md`）——与仓内 yzr-agent-style
  往 `~/.config/opencode/AGENTS.md` 装规则的行为对齐，无冲突。
