# html-mcp

常驻 HTTP daemon,让本机 agent(Claude Code / OpenCode)经 MCP 把自包含 HTML
(`yzr-md-to-html` 等工具的产物)推到远端 nginx server,同时提供一个 HTML 管理页供人浏览 /
预览 / 删除 / 复制公开 URL。

## 形态

```
┌──────────────────────┐                ┌──────────────────────────────────────┐
│  本机 agent           │   HTTPS        │  远端 nginx server                  │
│  (Claude Code /      │ ─────────────► │   ┌────────────────────────────┐    │
│   OpenCode)          │  /mcp + Bearer │   │ html-mcp daemon            │    │
│                      │                │   │  127.0.0.1:8765            │    │
│                      │                │   │  ├ POST /mcp    MCP server  │    │
│                      │                │   │  ├ GET  /       HTML 管理页 │    │
│                      │                │   │  └ /api/* + /files/         │    │
│                      │                │   └────────────┬───────────────┘    │
│  浏览器（人）         │ ──HTTPS──────► │       ┌────────▼────────────┐      │
│   https://notes...   │                │       │ nginx               │      │
│                      │                │       │  :443 → 反代 → :8765 │      │
│                      │                │       │  + 直 serve /files/* │      │
│                      │                │       └─────────┬────────────┘      │
│                      │                │           docroot/                  │
└──────────────────────┘                └──────────────────────────────────────┘
```

- **daemon 监听 `127.0.0.1` only**——由 nginx 在前面 HTTPS 反代 + 终结 TLS
- **单进程 stdlib `http.server.ThreadingHTTPServer`**——无第三方运行时依赖
- **MCP Streamable HTTP 自实现 ~150 行**——4 个 tool,无 MCP SDK

## 安装

跟 `model-switch` 同一套安装流程:

```bash
bash scripts/install.sh    # 装 wrapper + bash/fish 补全,扩展 PATH marker
source ~/.bashrc
html-mcp --help
```

> 跟 `model-switch` 一样的 stdlib-only 依赖——Python ≥ 3.7,<3.11 时自备 `tomli>=1.1`。

## 快速上手(在远端 nginx server 上)

```bash
# 1. 初始化
html-mcp init
# 输出一段 token,记下来(或 `html-mcp token show` 重看)

# 2. (可选) 编辑 ~/.config/html-mcp/config.toml:设 docroot / public_base_url / port

# 3. 创建 docroot(用户级 / sudo)
sudo mkdir -p /var/www/notes && sudo chown $USER /var/www/notes

# 4. 生成 nginx server block 示例
html-mcp nginx-config --write
# 默认写到 ~/.config/html-mcp/nginx.conf.example

# 5. 用户拷到 /etc/nginx/sites-available/notes.conf,改 server_name + 证书路径
sudo cp ~/.config/html-mcp/nginx.conf.example /etc/nginx/sites-available/notes.conf
sudo ln -s /etc/nginx/sites-available/notes.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 6. 启动 daemon(前台;生产建议 tmux / systemd 用户单元)
html-mcp serve &

# 7. 浏览器打开 https://notes.example.com/ → 直接看到(目前为空)列表
#    (管理页**不**接触 token:list 是公开元数据,删除/上传只能走 agent MCP)
```

在本机 agent 侧:

```json
// Claude Code MCP config: ~/.claude.json (或类似)
{
  "mcpServers": {
    "html-mcp": {
      "url": "https://notes.example.com/mcp",
      "headers": {
        "Authorization": "Bearer <html-mcp token show 输出>"
      }
    }
  }
}
```

agent 现在可以调 4 个 tool:`upload_html` / `list_html` / `delete_html` / `get_public_url`。
配合 `yzr-md-to-html` 使用流程:`md2html file.md → upload_html(name="file.html", content=...)`。

## 命令一览

```
html-mcp init [--force]                  # 创建 config + 生成 token
html-mcp serve [--config PATH]           # 前台启动 daemon
html-mcp token show                      # stdout 明文 token(CLI 路径,UI 不再使用)
html-mcp token rotate                    # 重生成(daemon 需重启才生效)
html-mcp config show                     # 打印 config (token 掩码)
html-mcp config path                     # 打印 config 路径
html-mcp config edit                     # $EDITOR 打开 config
html-mcp nginx-config                    # stdout 打印 server block
html-mcp nginx-config --write [PATH]     # 写到 ~/.config/html-mcp/nginx.conf.example
html-mcp status                          # 简报:config / token / docroot 状态
```

> 管理页只读:`GET /` 和 `GET /api/files` 都不鉴权;`DELETE /api/files/<name>` 与
> `GET /api/nginx-config` 仍要 Bearer(给运维 / 脚本用);`POST /mcp` 仍要 Bearer
> (agent 走)。**管理页里不再有 token 输入框,token 也不进 localStorage**——token
> 只在 server 端 `config.toml` 与本机 agent MCP config 之间手动同步。

## 文件命名 / 大小 / 覆盖规则

- **文件名 regex**:`^[A-Za-z0-9._-]+\.html$`(大小写不敏感匹配 `.html`),≤ 200 字符
- **大小**:默认上限 50 MB(`config.max_file_size` 可调)
- **同名上传**:默认 409 + `-32010`;带 `force=true` 才覆盖
- **公开 URL**:`config.public_base_url + '/' + <name>`

## 设计文档

完整设计与实施任务清单在仓库根:

- 设计:`docs/html-mcp-design.md`
- 任务书:`docs/html-mcp-tasks.md`
- brainstorming 决策日志:`docs/2026-08-01-html-mcp-upload-design.md`

## 局限性

- 不管 nginx 配置 / 不 reload / 不写证书——daemon 只产生 server block 模板,用户自己装
- 不做 mTLS / OAuth(单 Bearer 静态密钥)
- 不做多 docroot / 多租户
- 不存元数据库(title 从 HTML 解析,mtime/size 从 `stat` 取)
- daemon 保活由用户负责(README hint:tmux / systemd 用户单元)
- 管理页只读:list / 预览 / 复制公开 URL 在浏览器完成;**删除** 与 **上传** 只能通过
  agent MCP(本机 Claude Code / OpenCode 调 `delete_html` / `upload_html`),管理页
  故意不做删除按钮 / 上传表单,token 也不在 UI 出现