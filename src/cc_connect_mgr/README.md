# cc-connect-mgr

首装 / 配置 / 升级 / 卸载 [cc-connect llmw fork](https://github.com/yzr95924/llmw-cc-connect)
daemon 的本机 CLI。生产模型：daemon 跑 **npm 发布制品**（`@yzr95924/llmw-connect`）
+ **systemd 看门狗**（`Restart=always`）；rc 开发构建在 systemd 之外手动裸跑，不归本工具管。

## 安装

```bash
bash scripts/cc-connect-mgr.sh install    # bin wrapper + 补全 + PATH 块
```

## 命令

```bash
cc-connect-mgr install
# 依赖检查(tmux/opencode/npm/systemctl) → cc-connect 不在 PATH 则自动
#   npm i -g @yzr95924/llmw-connect@latest → 凭据收集(见下) →
#   systemd 单元(ExecStart=实测二进制路径, EnvironmentFile=~/.cc-connect/env,
#   **PATH=systemd 默认 + 探测到的 llmw/opencode/tmux 所在目录**——
#   否则 daemon 报 `llmw: executable file not found in $PATH`) →
#   enable --now → 轮询 journald 验证 "connected"。幂等可重跑;
#   单元内容有变时自动 restart 让新单元生效。
#   非 root:打印单元内容 + 手动步骤,不静默失败。

cc-connect-mgr config
# 凭据管理(可单独重跑,改 token 免重装):
#   Telegram bot token → ~/.cc-connect/env (0600, 原子写, 保留未知键)
#   钉钉(可选 --dingtalk): client_id/client_secret → env 文件
#   config.toml 不存在 → 从模板生成(secrets 全走 ${ENV} 占位符,
#     config.toml 零密钥);已存在且缺 dingtalk 块 → **自动插入**
#     (锚定在 [[projects]] 内首个顶级 [表] 之前,原文件备份 .bak;
#     无 [[projects]] 表时退回打印待粘贴块)
#   收尾做一致性检查:凭据在 env 但 config 无对应平台块(或反之)都会
#     打 warning——半配置状态不再静默(平台直接不启动)
# 变化即生效:有实际变更(env 写入/config 生成/块插入)且 daemon 在跑时
#   自动 systemctl restart + 验证 connected(换错 token 立刻红,不静默
#   崩溃循环);daemon 未跑/无权限 → 打印手动命令提示;--no-restart 跳过
# 漂移对齐:即使本次无变更,也会比对运行中 daemon 的环境(/proc/<pid>/
#   environ)与 env 文件——手动编辑过 env(如换 token)后忘了重启,
#   下次跑 config 自动发现并对齐(systemd 不热加载 EnvironmentFile)
# 非交互: --telegram-token / --dingtalk-id / --dingtalk-secret / --yes
#   (非交互且缺凭据 → 干净报错退出,不会卡在提示符;env 已有凭据则免传)
# --telegram-allow-from: 生成 config 时的 allow_from;默认 "*" = 任何人都能
#   驱动这台机的 opencode——多机分发强烈建议锁自己的 TG user id

cc-connect-mgr upgrade
# 先 `npm view` 查 registry 最新版:已最新 → 直接退出(不装包、不重启 daemon);
# 有新版或 registry 不可达(离线兜底) → npm i -g @latest → systemctl restart
# → 验证 connected。本地二进制缺失/非 llmw fork → 报错并指回 install。

cc-connect-mgr uninstall            # 数据默认保留
cc-connect-mgr uninstall --purge    # 连 ~/.cc-connect 一起删(不可逆)
cc-connect-mgr uninstall --remove-npm  # 顺带 npm uninstall -g
```

## 凭据与安全

- **一机一 bot**：两个 daemon 轮询同一 `TELEGRAM_BOT_TOKEN` 会互踢丢消息
  （Telegram getUpdates 冲突）——多机并存每机找 BotFather 建独立 bot
- 钉钉凭据在 config.toml 用 `${DINGTALK_CLIENT_ID}` / `${DINGTALK_CLIENT_SECRET}`
  占位符引用（cc-connect 启动时 `os.ExpandEnv` 解析），真实值只在 0600 的 env 文件
- env 文件被 systemd 单元以 `EnvironmentFile=` 加载；手动裸跑时
  `set -a; . ~/.cc-connect/env; set +a`

## 进程拉起分层

- **崩溃自动拉起**：systemd 单元自带（`Restart=always`, 3s）——工具负责把单元装对，
  拉起本身是 systemd 的职责，不依赖任何 Python 进程活着
- **升级/手动重启**：`upgrade` 子命令（restart + 验证）
- **假死探测**（进程活着但卡死）：不做，观察到真案例再补

## 已知边界

- **二进制来源校验**：`install`/`upgrade` 会跑 `cc-connect --version` 确认是 llmw
  fork（上游 npm 包的 bin 同名 `cc-connect`，装错了会静默跑无 llmw agent 的上游
  daemon）——校验不过会 npm 强装 fork 包重试，仍不过则报错退出
- 升级 cc-connect 后菜单可能多出上游新增内建命令——config.toml 模板里的
  `disabled_commands` 黑名单需对照 fork README 的验收清单复查
- `install` 需 root 才能写 `/etc/systemd/system`（非 root 自动降级为打印手动步骤）
- **勿手删 config.toml**：单元显式 `-config` 指向的文件不存在时，上游 cc-connect 会
  自动 bootstrap 一份含 claudecode 默认模板的配置到该路径（agent 类型示例是
  claudecode，非本 fork 使用的 llmw/opencode）——删错了用 `cc-connect-mgr config`
  重新生成，别让 daemon 自愈
