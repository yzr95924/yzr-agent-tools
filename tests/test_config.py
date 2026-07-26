"""Tests for config layer — Pydantic models + YAML read/write."""
import textwrap
from pathlib import Path

import pytest

from yzr_agent_tools.config import (
    Model,
    ModelsConfig,
    State,
    load_models,
    save_models,
    load_state,
    save_state,
)


# --- Model pydantic model -----------------------------------------------------

def test_model_round_trip_preserves_all_fields():
    m = Model(
        base_url="https://api.example.com",
        api_key_env="EXAMPLE_KEY",
        model_name="example-large",
        description="An example",
    )
    dumped = m.dict()
    restored = Model(**dumped)
    assert restored == m


def test_model_description_is_optional():
    m = Model(
        base_url="https://x",
        api_key_env="X",
        model_name="x",
    )
    assert m.description is None


def test_model_rejects_missing_required_fields():
    with pytest.raises(Exception):
        Model(base_url="x", api_key_env="X")  # missing model_name


# --- ModelsConfig -------------------------------------------------------------

def test_models_config_defaults_to_empty_dict():
    cfg = ModelsConfig()
    assert cfg.models == {}


def test_models_config_round_trip():
    cfg = ModelsConfig(
        models={
            "a": Model(base_url="u1", api_key_env="K1", model_name="m1"),
            "b": Model(base_url="u2", api_key_env="K2", model_name="m2",
                       description="d"),
        }
    )
    dumped = cfg.dict()
    restored = ModelsConfig(**dumped)
    assert restored == cfg


# --- State --------------------------------------------------------------------

def test_state_defaults_all_to_none():
    s = State()
    assert s.active_main is None
    assert s.active_small is None
    assert s.last_updated is None


def test_state_round_trip():
    s = State(active_main="a", active_small="b", last_updated="2026-01-01T00:00:00Z")
    dumped = s.dict()
    restored = State(**dumped)
    assert restored == s


# --- YAML I/O -----------------------------------------------------------------

def test_load_models_returns_empty_when_file_missing(tmp_path: Path):
    assert load_models(tmp_path / "models.yaml") == ModelsConfig()


def test_save_and_load_models_round_trip(tmp_path: Path):
    p = tmp_path / "models.yaml"
    cfg = ModelsConfig(
        models={
            "glm": Model(
                base_url="https://open.bigmodel.cn/api/anthropic",
                api_key_env="GLM_API_KEY",
                model_name="glm-4-plus",
                description="GLM-4 Plus",
            )
        }
    )
    save_models(cfg, p)
    loaded = load_models(p)
    assert loaded == cfg


def test_save_models_produces_valid_yaml(tmp_path: Path):
    p = tmp_path / "models.yaml"
    cfg = ModelsConfig(
        models={
            "x": Model(base_url="u", api_key_env="K", model_name="m"),
        }
    )
    save_models(cfg, p)
    text = p.read_text()
    # Snake-case keys; should contain model_name, base_url, api_key_env
    assert "model_name: m" in text
    assert "base_url: u" in text
    assert "api_key_env: K" in text


def test_load_models_rejects_invalid_yaml(tmp_path: Path):
    p = tmp_path / "models.yaml"
    p.write_text("not: valid: yaml: at: all:\n  - : ::\n")
    with pytest.raises(Exception):
        load_models(p)


def test_load_models_rejects_yaml_with_missing_required_fields(tmp_path: Path):
    p = tmp_path / "models.yaml"
    p.write_text(textwrap.dedent("""\
        models:
          bad:
            base_url: u
            # missing api_key_env, model_name
    """))
    with pytest.raises(Exception):
        load_models(p)


def test_load_state_returns_empty_when_file_missing(tmp_path: Path):
    assert load_state(tmp_path / "state.yaml") == State()


def test_save_and_load_state_round_trip(tmp_path: Path):
    p = tmp_path / "state.yaml"
    s = State(active_main="a", active_small="b", last_updated="2026-01-01T00:00:00Z")
    save_state(s, p)
    loaded = load_state(p)
    assert loaded == s