---
name: qodercli-driver-not-feasible
description: Do NOT build a qodercli driver for arbitrary Anthropic upstreams — verified infeasible (cloud-relay-only architecture + server-side BYOK entitlement). Topic closed unless qoder ships direct-baseURL.
metadata:
  type: project
---

**结论（2026-07-31 实测，qodercli 1.0.43）：qodercli 不适配，不再讨论。** model-switch 的核心场景
（把 agent 指向任意 Anthropic 兼容上游）在 qodercli 上无法实现，不要再做调研或写 driver。

**Why（三层实证，均用 `--config-dir` 重定向到 tmp 验证，未碰真实配置）：**

1. **没有客户端直连路径**。所有推理请求（含 BYOK 自定义模型）都发到
   `https://api3.qoder.sh/algo/api/v2/service/pro/sse/agent_chat_generation`，由 qoder 云端
   "generate custom pool" 代为转发。settings 里配的 `baseURL` 客户端会解析但**上传前被丢弃**
   （run log 里 `model_config.url:""`；本地 mock 上游收到 0 请求）。与 claude-code
   （`ANTHROPIC_BASE_URL` 直连）/ opencode（`provider.options.baseURL` 直连）架构本质不同。
2. **BYOK 是服务端强制的账号级授权**。`allow_byok` feature switch 由服务器下发；实测完全合规的
   `modelConfigs.customModels` 配置、连 qoder 自家支持的 provider（deepseek）都被拒：
   `BAD_REQUEST - "Failed to generate custom pool"`。客户端侧 `QODER_FEATURE_ALLOW_BYOK=2`
   覆盖无效。
3. **配置文件层倒是通的**（这也是容易误判的地方）：写 `~/.qoder/settings.json` 的
   `modelConfigs.customModels`（必填 `provider`/`apiKey`/`model`，可选 `baseURL`/`key`/`format`
   等）会合并进模型目录，`--list-models` 可见、`-m <key>` 可选中、`model.name` 可持久化。
   即「目录内切换」可行，但那不是 model-switch 的定位。

**How to apply:**

- 收到「给 qodercli 写 driver」的提议时直接引用本记忆拒绝，不重复调研。
- 用户 models.toml 的四个上游（百炼/Kimi/MiniMax/智谱）恰好都在 qoder BYOK 六家名单内且用
  官方端点——若账号未来开通了 BYOK（服务端 entitlement），这些 key 可经 qoder 云转发使用；
  那时重新评估（语义仍是云转发，不是直连）。
- 重开本话题的触发条件：qodercli 新版本把 `baseURL` 真正接入直连（客户端已在解析该字段，
  可能只是未上线），或账号确认获得 BYOK 授权。查版本行为：`strings` 搜
  `/root/.qoder/bin/qodercli/qodercli-*` 里的 `customModels`；隔离实测用
  `qodercli --config-dir /tmp/xxx --list-models`（注意 `.auth/` 和 `installation_id` 需从
  真实 `~/.qoder` 复制才能过登录校验）。
