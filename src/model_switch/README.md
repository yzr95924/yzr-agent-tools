# model-switch

为 OpenCode 维护一组 `yzr-*` 模型别名。每个别名通过 OpenCode 的 `canonical`
机制继承某个内置 provider 的模型定义，只替换名称和连接信息；模型本身的
runtime 包、capabilities、limits、variants 等全部跟随内置配置，不在本地复制。
不再支持 Claude Code，也不再维护厂商专用的请求补丁。

## 安装

```bash
bash scripts/model-switch.sh install
source ~/.bashrc   # 或 ~/.zshrc

model-switch --help
```

安装脚本写 `bin/model-switch` wrapper、装 bash/zsh/fish 补全、加 PATH 块；无 venv、无 pip。
运行时仅标准库，Python 3.7+；跑测试另需 `pytest`。

## 快速上手

```bash
# 新 yzr-* 组：内置来源唯一时自动确定；有歧义时用 --catalog-provider 钉选
model-switch model add yzr-dashscope/qwen3.8-flash --api-key sk-...

# z.ai 有 zai / zai-coding-plan 两个内置来源，必须明确钉选
model-switch model add yzr-zai/glm-5.3 \
  --api-key ... \
  --catalog-provider zai-coding-plan

# 已有 yzr-* 组上加模型：canonical 来源和 key 自动继承
model-switch model add yzr-zai/glm-5.3-flash --yes

# 激活并镜像进 opencode.json
model-switch model use yzr-dashscope/qwen3.8-flash
```

`model use` 只改 OpenCode 的默认模型指针；配置热加载，正在运行的会话保持原设置。
`status` 显示当前指针、注册表位置和 provider 清单：

```text
model-switch status
----------------------
active model:  yzr-dashscope/qwen3.8-flash
registry:      ~/.config/model-switch/models.toml (3 provider(s), 8 model(s))
opencode:      ~/.config/opencode/opencode.json
providers:     yzr-dashscope, yzr-kimi, yzr-zai
```

## 命令一览

| 命令 | 作用 |
| --- | --- |
| `model add [yzr-provider/model]` | 新增或替换模型别名；不带引用时进入向导 |
| `model list` | 按 `yzr-*` provider 列出别名和内置来源，标记当前激活项 |
| `model show [yzr-provider/model]` | 输出别名映射的 JSON |
| `model remove [yzr-provider/model]` | 删除模型别名 |
| `model use [yzr-provider/model]` | 激活别名并写默认指针 |
| `model align [yzr-provider/model]` | 校验内置来源与端点是否漂移 |
| `status` | 显示 OpenCode 当前状态 |

通用 flag：`model add` 支持 `--api-key`、`--catalog-provider`、`--yes`；
`model remove` 支持 `--yes`。非 TTY 下缺必填项直接报错，不会阻塞等待输入。

## models.toml

注册表位于 `~/.config/model-switch/models.toml`。每个模型一条 `[[models]]`
条目，只保存让别名成立的信息；`opencode.json` 是它的渲染产物，删掉 `yzr-*`
块后从这份文件重新渲染即可恢复。

```toml
schema_version = 2
active_model = "yzr-dashscope/qwen3.8-flash"

[[models]]
model_id = "qwen3.8-flash"
provider = "yzr-dashscope"
canonical_provider = "alibaba-cn"
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key = "sk-..."

[[models]]
model_id = "glm-5.3"
provider = "yzr-zai"
canonical_provider = "zai-coding-plan"
base_url = "https://api.z.ai/api/coding/paas/v4"
api_key = "..."
```

字段语义：

| 字段 | 作用 |
| --- | --- |
| `provider` | 最终的 OpenCode provider ID；必须以 `yzr-` 开头 |
| `canonical_provider` | 继承的内置 provider ID |
| `model_id` | 继承的内置模型 ID |
| `base_url` / `api_key` | 上游连接信息；同一 `provider` 下所有条目必须一致 |
| `active_model` | 激活别名（`yzr-provider/model_id`）；原样渲染成 OpenCode 默认指针 |

未知键（顶层与条目内）原样透传，load/save 不丢。模型级覆盖键
（`display_name`、`modalities`、窗口、`variants`、`compatibility`、`body`、
`package`）会被拒绝：它们存了也不会渲染，只会制造“看起来配置了”的假象。

## OpenCode 渲染规则

- model-switch 拥有 `opencode.json` 的 `yzr-*` provider 命名空间；`yzr-*` 之外的一切
  原样保留，包括其他 provider、`mcp`、`plugins`、`$schema`。
- 每组渲染成 `{ canonical, name, settings, models }`：`canonical` 指向内置
  provider，`settings` 只写 `baseURL` / `apiKey`，每个模型条目为空对象。
- 不渲染 `package` 或任何模型字段；OpenCode 通过 `canonical` 继承内置 runtime
  包和全部模型定义。写入本地字段反而会覆盖继承值。
- 默认模型指针是 `active_model` 的原样输出；没有 `active_model` 时移除指向
  `yzr-*` 的旧指针，外来指针不动。
- 每次 `add` / `remove` / `use` / `align` 都全量 reconcile：注册表里消失的
  `yzr-*` provider 连同 key 一起删除。
- `models.toml` 和 `opencode.json` 都含明文 key，写盘权限为 0600。

## catalog 解析

model-switch 只读 OpenCode 的本地 models.dev 快照
（`~/.local/share/opencode/opencode.db`，键 `models-dev:v2:catalog`），不联网。

- OpenCode 对 chat 模型使用第一个带 SDK 的 `api` 路由；model-switch 只接受
  默认路由就是 `chat-completions` 且带 `base_url` 的内置条目。
- `model add` 在新 `yzr-*` 组上按 `model_id` 找候选；多个候选一律视为歧义，
  必须用 `--catalog-provider` 钉选。两个内置 provider 即使 host 相同也不自动合并，
  因为 runtime 包可能不同。
- `model align` 不复制模型字段。它只检查 `canonical_provider/model_id` 是否仍存在、
  默认路由是否仍是 Chat Completions；端点漂移时更新 `base_url` 并重新渲染，
  其余情况报错退出。

## 旧配置

旧 `models.json` 与 `state.toml` 已删除。2026-10-31 起展开保存的模型字段和
GLM 本地补丁（`requireReasoning`、思考开关）也一并移除：别名完整继承内置定义，
不再本地复制。

## 跑测试

```bash
pytest tests/test_store.py tests/test_opencode_render.py tests/test_catalog.py
pytest tests/test_cli.py tests/test_cli_align.py tests/test_complete_cmd.py
```

## 局限

- 只支持 OpenCode 2.2+ 的 `canonical` provider 继承。
- 只接受默认路由为 Chat Completions 的内置模型；默认走 Messages / Responses
  的模型会被拒绝，不会静默换协议。
- 不支持本地模型覆盖；需要覆盖时应修改上游或内置 catalog，而不是在注册表里
  复制一份会漂移的字段。
- API key 必填，不支持无鉴权本地服务。
