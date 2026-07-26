# yzr-agent-tools

Quickly switch the model Claude Code uses — without hand-editing
`~/.claude/settings.json`.

yzr is a small CLI that stores your Anthropic-compatible upstream model
definitions in its own config dir, then writes the active selection into
Claude Code's `settings.json` env block when you run `yzr model use <name>`.
Restart Claude Code and it's talking to the new model.

## Install

```bash
pip install -e ".[dev]"   # from this repo, editable
# or, once published:
pip install yzr-agent-tools
```

Python 3.7+.

## Quickstart

```bash
# 1. Set your API key as an env var (yzr never writes keys to disk)
export GLM_API_KEY=sk-...

# 2. Register a model
yzr model add glm-z1-plus \
     --base-url https://open.bigmodel.cn/api/anthropic \
     --api-key-env GLM_API_KEY \
     --model-name glm-4-plus \
     --description "GLM-4 Plus"

# 3. Activate it
yzr model use glm-z1-plus

# 4. Restart Claude Code (Ctrl+D, then `claude`)
```

`yzr status` shows the current active model and the env keys that
Claude Code will see:

```
yzr-agent-tools status
----------------------
active main:  glm-z1-plus (model_name: glm-4-plus)
active small: glm-z1-plus (model_name: glm-4-plus)

Agent (claude-code) effective env in /root/.claude/settings.json:
  ANTHROPIC_BASE_URL              = https://open.bigmodel.cn/api/anthropic
  ANTHROPIC_AUTH_TOKEN            = sk-...
  ANTHROPIC_DEFAULT_OPUS_MODEL    = glm-4-plus
  ANTHROPIC_DEFAULT_SONNET_MODEL  = glm-4-plus
  ANTHROPIC_DEFAULT_HAIKU_MODEL   = glm-4-plus
```

## Commands

```
yzr init                              # create ~/.config/yzr-agent-tools/

yzr model add <name> \
     --base-url <url> \
     --api-key-env <ENV_VAR> \
     --model-name <id> \
     [--description <text>]

yzr model list                        # show all models + active markers
yzr model show <name>
yzr model remove <name>

yzr model use <name> [--small <name>] # activate main (+ optional small)
yzr small-model use <name>            # change small only
yzr small-model clear                 # small follows main

yzr status                            # current state + effective env
```

## How main vs small work

Claude Code uses two model slots:

| Slot    | Used for                                       |
| ------- | ---------------------------------------------- |
| main    | The actual coding work                         |
| small   | Background tasks: session titles, summaries, etc |

yzr writes both into `settings.json`:

- `ANTHROPIC_DEFAULT_OPUS_MODEL` + `ANTHROPIC_DEFAULT_SONNET_MODEL` ← main
- `ANTHROPIC_DEFAULT_HAIKU_MODEL` ← small

So Opus/Sonnet alias both route to your main model, and Haiku alias routes
to your small model.

## What's written to settings.json

Only these keys, under the `env` block:

- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_AUTH_TOKEN`
- `ANTHROPIC_DEFAULT_OPUS_MODEL`
- `ANTHROPIC_DEFAULT_SONNET_MODEL`
- `ANTHROPIC_DEFAULT_HAIKU_MODEL`

Everything else in `settings.json` (theme, plugins, custom env vars like
`DISABLE_TELEMETRY`, etc.) is preserved untouched.

The API key is resolved from your shell env at the moment you run
`model use` and written as the value of `ANTHROPIC_AUTH_TOKEN`. yzr never
stores keys in its own config files.

## Storage layout

```
~/.config/yzr-agent-tools/
├── models.yaml      # your model definitions
└── state.yaml       # which one is active
```

## Architecture notes

- **Driver abstraction.** Each agent (Claude Code today, OpenCode etc. in
  the future) is a small "driver" class that knows how to read/write its
  own config file format. Adding a new agent = implementing one driver
  and registering it.
- **No daemon. No proxy. No protocol conversion.** yzr only writes
  config files. Anthropic-compatible upstreams speak the same protocol
  Claude Code already speaks.
- **Restart required.** Switching models writes to a config file Claude
  Code reads at startup; restart `claude` (Ctrl+D then `claude`) to pick
  up changes.

## Run the tests

```bash
pip install -e ".[dev]"
pytest
```

The autouse fixture in `tests/conftest.py` ensures tests never write to
your real `~/.claude/settings.json` — it redirects all paths into a
per-test tmp directory and asserts byte-identical content of the real
configs at teardown.

## Limitations

- Only Anthropic-compatible upstreams. OpenAI-only providers (raw OpenAI,
  DeepSeek, Ollama) need a protocol-translation layer that's not in V1.
- Only Claude Code is supported. OpenCode / Aider / Cursor etc. need
  driver implementations in V2.
- API keys must be in env vars; yzr won't store them.

## License

MIT.