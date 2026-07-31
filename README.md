# model-switch

Quickly switch the model Claude Code uses — without hand-editing
`~/.claude/settings.json`.

`model-switch` is a small CLI that stores your Anthropic-compatible upstream model
definitions in its own config dir, then writes the active selection into
Claude Code's `settings.json` env block when you run `model-switch model use <name>`.
Restart Claude Code and it's talking to the new model.

## Install

```bash
# from this repo, using the bundled installer
bash scripts/install.sh
source ~/.bashrc   # or ~/.zshrc

# verify
model-switch --help

# uninstall
bash scripts/uninstall.sh

# or, once published:
pip install model-switch
```

Python 3.7+. The installer is a thin shell script: it writes
`bin/model-switch` (a 4-line bash wrapper that exec's
`python3 -m model_switch` with `PYTHONPATH=$REPO/src`) and adds an idempotent
PATH block to your shell rc. No virtualenv, no `pip install`.

### Runtime / dev deps you supply yourself

The installer does **not** install Python packages. Make sure these are
available before running `model-switch`:

| Use case        | Python < 3.11                  | Python ≥ 3.11 |
| --------------- | ------------------------------ | ------------- |
| Run the CLI     | `pip install --user 'tomli>=1.1'` | (stdlib only) |
| Run the tests   | `pip install --user pytest pytest-cov` | same |

If `tomli` is missing on Python < 3.11, the first `model-switch` invocation
will fail at `import tomli` with an `ImportError` — install it and retry.

### Shell completion (bash + fish)

`install.sh` also wires up tab completion:

- **bash** — symlinked into `~/.local/share/bash-completion/completions/`
  *and* sourced from the PATH block in `~/.bashrc`, so it works even
  without the bash-completion package.
- **fish** — symlinked into `~/.config/fish/completions/` (auto-loaded).

Completion covers subcommands, flags, `--driver` values, and model names
for `model use/show/remove`. Dynamic candidates come from the CLI itself
(the hidden `model-switch _complete models|drivers` plumbing command), so
they always match your `models.toml`. `uninstall.sh` removes the symlinks
and the sourced line. The scripts live in `completions/` if you prefer to
wire them up manually.

## Quickstart

```bash
# 1. Register a model — the API key is stored (plaintext) in models.toml
model-switch model add glm-z1-plus \
     --base-url https://open.bigmodel.cn/api/anthropic \
     --api-key sk-... \
     --model-name glm-4-plus \
     --description "GLM-4 Plus" \
     --context-window 200000

# 3. Activate it
model-switch model use glm-z1-plus

# 4. Restart Claude Code (Ctrl+D, then `claude`)
```

`model-switch status` shows the current active model and the env keys that
Claude Code will see:

```
model-switch status
----------------------
active main:  glm-z1-plus (name: glm-4-plus)

Agent (claude-code) effective env in /root/.claude/settings.json:
  ANTHROPIC_BASE_URL    = https://open.bigmodel.cn/api/anthropic
  ANTHROPIC_AUTH_TOKEN  = sk-...
  ANTHROPIC_MODEL       = glm-4-plus
```

## Commands

```
model-switch init                              # create ~/.config/model-switch/

model-switch model add <name> \
     --base-url <url> \
     --api-key <KEY> \
     --model-name <id> \
     [--description <text>] \
     [--context-window <tokens>]

model-switch model list                        # show all models + active markers
model-switch model show <name>
model-switch model remove <name>

model-switch model use <name> [--driver NAME] [--all-drivers]

model-switch status [--driver NAME] [--all-drivers]
```

## What's written to settings.json

Under the `env` block, plus a top-level `model` for the modern single-model
shape:

- `ANTHROPIC_BASE_URL` — upstream base URL
- `ANTHROPIC_AUTH_TOKEN` — the model's `api_key` from models.toml
- `ANTHROPIC_MODEL` — `<name>` or `<name>[1m]` when `context_window >= 1_000_000`
- Top-level `model` — mirrors `ANTHROPIC_MODEL`

Everything else in `settings.json` (theme, plugins, custom env vars like
`DISABLE_TELEMETRY`, etc.) is preserved untouched.

The API key is resolved from your shell env (or `api_key` field in `models.toml`)
at the moment you run `model use`, and written as the value of
`ANTHROPIC_AUTH_TOKEN`. model-switch treats `models.toml` as a local-only
config file with the same trust model as `workspace_models.toml`.

## Storage layout

```
~/.config/model-switch/
├── models.toml      # your model definitions (TOML)
└── state.toml       # which one is active
```

The `models.toml` is intentionally compatible with `workspace_models.toml`
produced by `llmw`: any unknown top-level or per-model keys (e.g. `api_key`,
`is_default`, `schema_version`, `created_at`, `updated_at`) are loaded into
`extra` buckets and written back untouched on the next save. Copying a
`workspace_models.toml` into place and switching models preserves llmw's
fields.

## Architecture notes

- **Driver abstraction.** Each agent (Claude Code and OpenCode today;
  more in the future) is a small "driver" class that knows how to read/write
  its own config file format. Adding a new agent = implementing one driver
  and registering it.
- **No daemon. No proxy. No protocol conversion.** model-switch only writes
  config files. Anthropic-compatible upstreams speak the same protocol
  Claude Code already speaks.
- **Restart required.** Switching models writes to a config file the agent
  reads at startup; restart your agent to pick up changes.

## Targeting OpenCode

`model-switch` ships a built-in driver for OpenCode in addition to the
default Claude Code driver. Pass `--driver opencode` to any command that
writes config:

```bash
# Activate a model for OpenCode
model-switch model use glm-z1-plus --driver opencode

# Inspect what OpenCode will see
model-switch status --driver opencode
```

The OpenCode driver writes a `provider.yzr` block (with the `@ai-sdk/anthropic`
adapter) into OpenCode's global config at `~/.config/opencode/opencode.json`
(`$XDG_CONFIG_HOME/opencode/opencode.json`) and writes the resolved API key
directly into `apiKey` — the key is stored in the config file, so keep its
permissions tight. The same `models.toml` definitions are shared with the
Claude Code driver, so you can switch agents without re-registering models.

## Run the tests

```bash
# pytest must be on PATH (e.g. `pip install --user pytest pytest-cov`).
# pyproject.toml's [tool.pytest.ini_options].pythonpath adds src/ directly,
# so a `pip install -e .` is NOT required to discover `import model_switch`.
pytest
```

The autouse fixture in `tests/conftest.py` ensures tests never write to
your real `~/.claude/settings.json` — it redirects all paths into a
per-test tmp directory and asserts byte-identical content of the real
configs at teardown.

## Limitations

- Only Anthropic-compatible upstreams. OpenAI-only providers (raw OpenAI,
  DeepSeek, Ollama) need a protocol-translation layer that's not in V1.
- Only Claude Code and OpenCode have built-in drivers. Other agents
  (Aider, Cursor, etc.) need a driver implementation.

## License

MIT.