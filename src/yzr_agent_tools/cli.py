"""Typer CLI for yzr-agent-tools.

The CLI is a thin wrapper that:
1. Reads models from ~/.config/yzr-agent-tools/models.yaml
2. Reads state from ~/.config/yzr-agent-tools/state.yaml
3. Calls the registered agent driver's read/apply/current methods
4. Writes updated state back

V1 ships with only the claude-code driver registered automatically.
"""
import datetime
import os
import sys
from typing import Optional

import typer

from yzr_agent_tools import paths
from yzr_agent_tools.config import (
    Model,
    ModelsConfig,
    State,
    load_models,
    load_state,
    save_models,
    save_state,
)
from yzr_agent_tools.drivers.base import registry


def _default_driver():
    """Return the default agent driver, registering the built-in on first use.

    Lazy registration avoids import-time side effects that would create a
    driver pointed at the real ~/.claude/settings.json (a test-isolation
    hazard). Tests that want a tmp-path driver should populate the
    registry BEFORE the first CLI invocation.
    """
    if "claude-code" not in registry.list():
        from yzr_agent_tools.drivers.claude_code import ClaudeCodeDriver
        registry.register(ClaudeCodeDriver())
    return registry.default()


app = typer.Typer(help="Switch Anthropic-compatible models for Claude Code (and friends).")
model_app = typer.Typer(help="Manage model definitions.")
small_app = typer.Typer(help="Manage the small/fast model selection.")
status_app = typer.Typer(help="Show current state.", invoke_without_command=True)

app.add_typer(model_app, name="model")
app.add_typer(small_app, name="small-model")


# --- top-level commands -------------------------------------------------------

@app.command("init")
def cmd_init():
    """Initialize the yzr config directory."""
    d = paths.config_dir()
    d.mkdir(parents=True, exist_ok=True)
    if not paths.models_file().exists():
        save_models(ModelsConfig(), paths.models_file())
    if not paths.state_file().exists():
        save_state(State(), paths.state_file())
    typer.echo(f"Initialized yzr config at {d}")


@app.callback(invoke_without_command=True)
def cmd_root(ctx: typer.Context):
    """Top-level help."""
    pass


# --- model subcommands --------------------------------------------------------

@model_app.command("add")
def cmd_model_add(
    name: str = typer.Argument(..., help="Local nickname for this model."),
    base_url: str = typer.Option(..., "--base-url", help="Upstream API base URL."),
    api_key_env: str = typer.Option(..., "--api-key-env",
                                    help="Name of the env var holding the API key."),
    model_name: str = typer.Option(..., "--model-name",
                                   help="Model identifier expected by upstream."),
    description: Optional[str] = typer.Option(None, "--description",
                                             help="Free-text description."),
):
    """Add a new model definition."""
    cfg = load_models(paths.models_file())
    if name in cfg.models:
        typer.echo(f"Error: model {name!r} already exists.", err=True)
        raise typer.Exit(code=1)
    cfg.models[name] = Model(
        base_url=base_url,
        api_key_env=api_key_env,
        model_name=model_name,
        description=description,
    )
    save_models(cfg, paths.models_file())
    typer.echo(f"Added model {name!r}.")


@model_app.command("list")
def cmd_model_list():
    """List all configured models."""
    cfg = load_models(paths.models_file())
    state = load_state(paths.state_file())
    if not cfg.models:
        typer.echo("(no models configured — run `yzr model add` to add one)")
        return
    name_w = max(len(n) for n in cfg.models)
    for n, m in cfg.models.items():
        markers = []
        if state.active_main == n:
            markers.append("main")
        if state.active_small == n:
            markers.append("small")
        marker = " [" + ",".join(markers) + "]" if markers else ""
        typer.echo(f"  {n.ljust(name_w)}  {m.model_name}{marker}")


@model_app.command("show")
def cmd_model_show(
    name: str = typer.Argument(...),
):
    """Show details of one model."""
    cfg = load_models(paths.models_file())
    if name not in cfg.models:
        typer.echo(f"Error: model {name!r} not found.", err=True)
        raise typer.Exit(code=1)
    m = cfg.models[name]
    typer.echo(f"name:         {name}")
    typer.echo(f"base_url:     {m.base_url}")
    typer.echo(f"api_key_env:  {m.api_key_env}")
    typer.echo(f"model_name:   {m.model_name}")
    if m.description:
        typer.echo(f"description:  {m.description}")


@model_app.command("remove")
def cmd_model_remove(
    name: str = typer.Argument(...),
):
    """Remove a model definition."""
    cfg = load_models(paths.models_file())
    if name not in cfg.models:
        typer.echo(f"Error: model {name!r} not found.", err=True)
        raise typer.Exit(code=1)
    del cfg.models[name]
    save_models(cfg, paths.models_file())
    typer.echo(f"Removed model {name!r}.")


@model_app.command("use")
def cmd_model_use(
    name: str = typer.Argument(..., help="Model name to activate."),
    small: Optional[str] = typer.Option(
        None, "--small",
        help="Also activate this model as the small/fast model. Omit to use main as small.",
    ),
):
    """Activate a model as main; write the active state and push to the agent driver."""
    cfg = load_models(paths.models_file())
    if name not in cfg.models:
        typer.echo(f"Error: model {name!r} not found.", err=True)
        raise typer.Exit(code=1)

    main_model = cfg.models[name]
    small_model_name = small if small else name
    if small_model_name not in cfg.models:
        typer.echo(f"Error: small model {small_model_name!r} not found.", err=True)
        raise typer.Exit(code=1)
    small_model = cfg.models[small_model_name]

    api_key = _resolve_api_key(main_model.api_key_env)

    # Apply to the default agent driver (claude-code for V1).
    driver = _default_driver()
    if driver is None:
        typer.echo("Error: no agent driver registered.", err=True)
        raise typer.Exit(code=1)
    driver.apply(main=main_model, small=small_model, api_key=api_key)

    # Update state.
    state = load_state(paths.state_file())
    state.active_main = name
    state.active_small = small_model_name
    state.last_updated = datetime.datetime.utcnow().isoformat() + "Z"
    save_state(state, paths.state_file())

    typer.echo(f"Switched to {name!r} (small: {small_model_name!r}).")
    typer.echo(f"  Wrote {driver.settings_path}")
    typer.echo("  Restart Claude Code (Ctrl+D, then `claude`) to take effect.")


# --- small-model subcommands --------------------------------------------------

@small_app.command("use")
def cmd_small_use(
    name: str = typer.Argument(...),
):
    """Activate a model as the small/fast model only (keeps current main)."""
    cfg = load_models(paths.models_file())
    if name not in cfg.models:
        typer.echo(f"Error: model {name!r} not found.", err=True)
        raise typer.Exit(code=1)
    state = load_state(paths.state_file())
    if not state.active_main:
        typer.echo("Error: no main model active; run `yzr model use <name>` first.",
                   err=True)
        raise typer.Exit(code=1)
    main_model = cfg.models[state.active_main]
    small_model = cfg.models[name]
    api_key = _resolve_api_key(main_model.api_key_env)
    driver = _default_driver()
    driver.apply(main=main_model, small=small_model, api_key=api_key)
    state.active_small = name
    state.last_updated = datetime.datetime.utcnow().isoformat() + "Z"
    save_state(state, paths.state_file())
    typer.echo(f"Small model switched to {name!r}.")


@small_app.command("clear")
def cmd_small_clear():
    """Reset small model to follow main (small uses main's model_name)."""
    state = load_state(paths.state_file())
    if not state.active_main:
        typer.echo("Error: no main model active.", err=True)
        raise typer.Exit(code=1)
    cfg = load_models(paths.models_file())
    main_model = cfg.models[state.active_main]
    api_key = _resolve_api_key(main_model.api_key_env)
    driver = _default_driver()
    driver.apply(main=main_model, small=main_model, api_key=api_key)
    state.active_small = state.active_main
    state.last_updated = datetime.datetime.utcnow().isoformat() + "Z"
    save_state(state, paths.state_file())
    typer.echo("Small model cleared (now follows main).")


# --- status -------------------------------------------------------------------

@app.command("status")
def cmd_status():
    """Show the currently active model + effective agent config."""
    state = load_state(paths.state_file())
    cfg = load_models(paths.models_file())

    typer.echo("yzr-agent-tools status")
    typer.echo("----------------------")
    if not state.active_main:
        typer.echo("active main:  (none)")
        typer.echo("active small: (none)")
    else:
        typer.echo(f"active main:  {state.active_main} "
                   f"(model_name: {cfg.models[state.active_main].model_name})")
        if state.active_small:
            typer.echo(f"active small: {state.active_small} "
                       f"(model_name: {cfg.models[state.active_small].model_name})")

    driver = _default_driver()
    if driver is not None:
        typer.echo("")
        typer.echo(f"Agent ({driver.name}) effective env in {driver.settings_path}:")
        current = driver.current()
        if not current:
            typer.echo("  (empty)")
        else:
            # Show only the yzr-managed keys, in canonical order.
            ordered = (
                "ANTHROPIC_BASE_URL",
                "ANTHROPIC_AUTH_TOKEN",
                "ANTHROPIC_DEFAULT_OPUS_MODEL",
                "ANTHROPIC_DEFAULT_SONNET_MODEL",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL",
            )
            for k in ordered:
                if k in current:
                    typer.echo(f"  {k} = {current[k]}")


# --- helpers ------------------------------------------------------------------

def _resolve_api_key(env_var: str) -> str:
    """Read the API key from the named env var, or fail with a friendly message."""
    val = os.environ.get(env_var)
    if not val:
        typer.echo(
            f"Error: environment variable {env_var!r} is not set.\n"
            f"  Set it before activating:  export {env_var}=<your-key>",
            err=True,
        )
        raise typer.Exit(code=1)
    return val


if __name__ == "__main__":
    app()