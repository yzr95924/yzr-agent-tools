"""Pydantic models + YAML I/O for yzr-agent-tools.

Stores two files under the config dir:
- models.yaml — list of Anthropic-compatible upstream model definitions
- state.yaml — currently active main + small model selections
"""
from pathlib import Path
from typing import Dict, Optional

import yaml
from pydantic import BaseModel, Field


class Model(BaseModel):
    """One Anthropic-compatible upstream model."""
    base_url: str
    api_key_env: str
    model_name: str
    description: Optional[str] = None


class ModelsConfig(BaseModel):
    """Top-level models.yaml schema."""
    models: Dict[str, Model] = Field(default_factory=dict)


class State(BaseModel):
    """Top-level state.yaml schema."""
    active_main: Optional[str] = None
    active_small: Optional[str] = None
    last_updated: Optional[str] = None


def load_models(path: Path) -> ModelsConfig:
    """Read models.yaml. Missing file -> empty config."""
    if not path.exists():
        return ModelsConfig()
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return ModelsConfig(**raw)


def save_models(cfg: ModelsConfig, path: Path) -> None:
    """Write models.yaml atomically (tmp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = {"models": {name: m.dict(exclude_none=True)
                      for name, m in cfg.models.items()}}
    _atomic_write_yaml(raw, path)


def load_state(path: Path) -> State:
    """Read state.yaml. Missing file -> empty state."""
    if not path.exists():
        return State()
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return State(**raw)


def save_state(state: State, path: Path) -> None:
    """Write state.yaml atomically (tmp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = state.dict(exclude_none=True)
    _atomic_write_yaml(raw, path)


def _atomic_write_yaml(raw: dict, path: Path) -> None:
    """Write a YAML dict atomically: write tmp then rename."""
    import os
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, default_flow_style=False, sort_keys=False)
    os.replace(tmp, path)