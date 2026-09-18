"""Tests for `model-switch model probe` / `model_switch.probe`.

The probe talks to the wire with the HTTP shape (snake_case `budget_tokens`,
`output_config`) — these tests pin that shape, the verdict mapping, the
suggested-preset policy, and the `--apply` write boundary (probe-* namespace
only, atomic + .bak).
"""
import json
from pathlib import Path

from model_switch import probe
from model_switch._compat import toml_loads
from model_switch.store import ModelEntry, load_models

from _cli_runner import invoke_cli as runner


MODELS_TOML = (
    '[variants_presets.z-effort]\n'
    'high = { effort = "high" }\n'
    '\n'
    '[[models]]\n'
    'model_id = "glm-5_3-1m"\n'
    'name = "glm-5.3"\n'
    'base_url = "https://api.example.com"\n'
    'api_key = "K1"\n'
    'context_window = 1000000\n'
    'variants_preset = "z-effort"\n'
)


def _model(name="glm-5.3", model_id="glm-5_3-1m", base_url="https://api.example.com"):
    return ModelEntry(model_id=model_id, name=name, base_url=base_url, api_key="K")


def _res(label, verdict="accepted"):
    return probe.ProbeResult(
        label=label, payload={}, status=200 if verdict == "accepted" else 400,
        verdict=verdict,
    )


def test_probe_sends_wire_shapes():
    seen = {}

    def behavior(payload):
        th = payload.get("thinking")
        if th is None:
            key = "control"
        elif th.get("type") == "disabled":
            key = "disabled"
        elif th.get("type") == "adaptive":
            effort = (payload.get("output_config") or {}).get("effort", "none")
            key = "adaptive-effort-" + effort
        else:
            key = "budget-{}".format(th.get("budget_tokens"))
        seen[key] = payload
        return (200, {"content": [{"type": "text"}], "usage": {"output_tokens": 3}})

    # Sender signature: (url, headers, payload, timeout)
    calls = []

    def sender(url, headers, payload, timeout):
        calls.append(url)
        return behavior(payload)

    results = probe.probe(_model(), budgets=(4096, 8192), sender=sender)

    assert [r.label for r in results] == [
        "control", "disabled", "adaptive",
        "adaptive-effort-low", "adaptive-effort-high",
        "budget-4096", "budget-8192",
    ]
    assert all(r.verdict == "accepted" for r in results)
    # HTTP shape: snake_case budget_tokens, max_tokens above the budget,
    # base_url normalized with a version segment + /messages.
    assert seen["budget-4096"]["thinking"] == {"type": "enabled", "budget_tokens": 4096}
    assert seen["budget-4096"]["max_tokens"] > 4096
    assert seen["adaptive-effort-high"]["output_config"] == {"effort": "high"}
    assert seen["control"]["model"] == "glm-5.3"
    assert all(u == "https://api.example.com/v1/messages" for u in calls)


def test_verdict_mapping():
    def behavior(payload):
        th = payload.get("thinking") or {}
        if payload.get("thinking") is None:
            return (500, "boom")
        if th.get("type") == "disabled":
            return (400, {"error": {"message": "thinking is not supported"}})
        if th.get("type") == "enabled":
            return (400, {"error": {"message": "bad parameter"}})
        return (200, {"content": []})

    def sender(url, headers, payload, timeout):
        return behavior(payload)

    results = probe.probe(_model(), budgets=(4096,), sender=sender)
    verdicts = {r.label: r.verdict for r in results}
    assert verdicts["control"] == "endpoint-error"
    assert verdicts["disabled"] == "rejected"
    assert verdicts["budget-4096"] == "endpoint-error"  # generic message
    assert verdicts["adaptive"] == "accepted"
    assert verdicts["adaptive-effort-high"] == "accepted"


def test_suggest_variants_prefers_effort():
    results = [
        _res("control"),
        _res("disabled"),
        _res("adaptive-effort-low"),
        _res("adaptive-effort-high"),
        _res("budget-1024", verdict="rejected"),
    ]
    assert probe.suggest_variants(results) == {
        "off": {"thinking": {"type": "disabled"}},
        "low": {"thinking": {"type": "adaptive"}, "effort": "low"},
        "high": {"thinking": {"type": "adaptive"}, "effort": "high"},
    }


def test_suggest_variants_budget_fallback():
    results = [
        _res("control"),
        _res("disabled"),
        _res("budget-1024", verdict="rejected"),
        _res("budget-4096"),
        _res("budget-32768"),
        _res("adaptive-effort-high", verdict="rejected"),
    ]
    assert probe.suggest_variants(results) == {
        "off": {"thinking": {"type": "disabled"}},
        "low": {"thinking": {"type": "enabled", "budgetTokens": 4096}},
        "high": {"thinking": {"type": "enabled", "budgetTokens": 32768}},
    }


def test_suggest_variants_empty_when_nothing_accepted():
    assert probe.suggest_variants([_res("control", verdict="endpoint-error")]) == {}


def test_suggest_variants_effort_high_only_on_partial_failure():
    """A transient effort-low failure yields high-only effort, not a budget flip."""
    results = [
        _res("adaptive-effort-high"),
        _res("adaptive-effort-low", verdict="endpoint-error"),
        _res("budget-4096"),
    ]
    assert probe.suggest_variants(results) == {
        "high": {"thinking": {"type": "adaptive"}, "effort": "high"},
    }


def test_probe_retries_transport_once():
    calls = {"n": 0}

    def sender(url, headers, payload, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("stall")
        return (200, {"content": [{"type": "text"}]})

    results = probe.probe(_model(), budgets=(4096,), sender=sender)
    assert results[0].verdict == "accepted"
    assert calls["n"] > 1


def test_apply_preset_only_touches_probe_namespace(_isolate_yzr_state):
    p = _isolate_yzr_state["models"]
    p.write_text(MODELS_TOML, encoding="utf-8")
    tiers = {"high": {"thinking": {"type": "adaptive"}, "effort": "high"}}

    key = probe.apply_preset(p, "glm-5_3-1m", tiers)

    assert key == "probe-glm-5_3-1m"
    assert Path(str(p) + ".bak").exists()
    reg = load_models(p)
    presets = reg.extra_top["variants_presets"]
    assert "z-effort" in presets  # user preset untouched
    assert presets["probe-glm-5_3-1m"] == tiers
    assert "glm-5_3-1m" in reg.models


def test_render_report_snippet_is_valid_toml():
    results = [
        _res("control"),
        _res("disabled"),
        _res("adaptive-effort-low"),
        _res("adaptive-effort-high"),
    ]
    report = probe.render_report(_model(), results)
    assert "## Suggested preset" in report
    block = report.split("```toml\n", 1)[1].split("```", 1)[0]
    tiers = toml_loads(block)["variants_presets"]["probe-glm-5_3-1m"]
    assert tiers["off"] == {"thinking": {"type": "disabled"}}
    assert tiers["high"] == {"thinking": {"type": "adaptive"}, "effort": "high"}

    empty = probe.render_report(_model(), [_res("control", verdict="endpoint-error")])
    assert "nothing to suggest" in empty


def test_lookup_catalog_prefers_host_match(tmp_path):
    cat = {
        "alibaba": {
            "api": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "models": {"glm-5.3": {"reasoning_options": None}},
        },
        "zai-coding-plan": {
            "api": "https://api.z.ai/api/coding/paas/v4",
            "models": {"glm-5.3": {"reasoning_options": [
                {"type": "effort", "values": ["low", "high", "max"]},
            ], "limit": {"context": 1000000}}},
        },
    }
    cat_path = tmp_path / "models.json"
    cat_path.write_text(json.dumps(cat), encoding="utf-8")

    m = _model(base_url="https://api.z.ai/api/anthropic")
    matches = probe.lookup_catalog(m, catalog_path=str(cat_path))
    assert len(matches) == 2
    assert matches[0]["provider"] == "zai-coding-plan"
    assert matches[0]["host_match"] is True
    assert matches[1]["host_match"] is False


def test_lookup_catalog_missing_cache(tmp_path):
    m = _model()
    assert probe.lookup_catalog(m, catalog_path=str(tmp_path / "nope.json")) == []


def test_lookup_catalog_orders_actionable_over_toggle_only():
    """Same host, two providers: the entry declaring effort/budget shapes
    must outrank a toggle-only declaration — the ordering that makes the
    qwen3.7 case (14 same-host candidates) deterministic."""
    cat = {
        "zz-coding-plan": {
            "api": "https://dashscope.aliyuncs.com/v1",
            "models": {"qwen3.7-max": {"reasoning_options": [{"type": "toggle"}]}},
        },
        "alibaba-cn": {
            "api": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "models": {"qwen3.7-max": {"reasoning_options": [
                {"type": "toggle"}, {"type": "budget_tokens", "max": 262144},
            ]}},
        },
    }
    m = _model(name="qwen3.7-max",
               base_url="https://dashscope.aliyuncs.com/apps/anthropic")
    matches = probe.lookup_catalog(m, catalog_data=cat)
    assert [x["provider"] for x in matches] == ["alibaba-cn", "zz-coding-plan"]


def test_lookup_catalog_provider_pin():
    cat = {
        "a": {"api": "https://api.z.ai/x", "models": {
            "glm-5.3": {"reasoning_options": [{"type": "effort", "values": ["low"]}]}}},
        "b": {"api": "https://api.z.ai/y", "models": {
            "glm-5.3": {"reasoning_options": [
                {"type": "effort", "values": ["high"]}]}}},
    }
    m = _model(base_url="https://api.z.ai/api/anthropic")
    pinned = probe.lookup_catalog(m, catalog_data=cat, provider="a")
    assert len(pinned) == 1 and pinned[0]["provider"] == "a"
    # Unknown pin → empty, not a silent fallback to the "best" guess.
    assert probe.lookup_catalog(m, catalog_data=cat, provider="nope") == []


def test_build_rows_effort_family_covers_declared_values():
    entry = {"reasoning_options": [
        {"type": "toggle"},
        {"type": "effort", "values": ["low", "medium", "xhigh"]},
        {"type": "budget_tokens", "min": 0, "max": 262144},
    ]}
    labels = [l for l, _, _ in probe.build_rows(entry)]
    # effort declared → budget family skipped, every declared value probed
    # (medium/xhigh are exactly what the legacy fixed matrix could not see)
    assert labels == ["control", "disabled", "adaptive",
                      "adaptive-effort-low", "adaptive-effort-medium",
                      "adaptive-effort-xhigh"]


def test_build_rows_budget_family_uses_catalog_bounds():
    entry = {"reasoning_options": [
        {"type": "toggle"}, {"type": "budget_tokens", "max": 8192},
    ]}
    labels = [l for l, _, _ in probe.build_rows(entry)]
    assert labels == ["control", "disabled", "adaptive",
                      "budget-1024", "budget-4096", "budget-8192"]


def test_build_rows_toggle_only_and_fallback():
    toggle_only = {"reasoning_options": [{"type": "toggle"}]}
    assert [l for l, _, _ in probe.build_rows(toggle_only)] == [
        "control", "disabled", "adaptive"]
    # no catalog entry at all → legacy discovery matrix
    fallback = [l for l, _, _ in probe.build_rows(None)]
    assert fallback == [
        "control", "disabled", "adaptive",
        "adaptive-effort-low", "adaptive-effort-high",
        "budget-1024", "budget-4096", "budget-8192", "budget-32768"]
    # explicit budgets override the ladder even with an effort entry
    both = [l for l, _, _ in probe.build_rows(
        {"reasoning_options": [{"type": "effort", "values": ["low"]}]},
        budgets=(2048,))]
    assert "budget-2048" in both and "adaptive-effort-low" in both


def test_suggest_skips_none_and_minimal_effort_tiers():
    results = [
        _res("control"),
        _res("disabled"),
        _res("adaptive-effort-none"),
        _res("adaptive-effort-minimal"),
        _res("adaptive-effort-low"),
    ]
    tiers = probe.suggest_variants(results)
    assert tiers == {
        "off": {"thinking": {"type": "disabled"}},
        "low": {"thinking": {"type": "adaptive"}, "effort": "low"},
    }


def test_default_fetcher_sends_explicit_user_agent(monkeypatch):
    """models.opencode.ai 403s the stdlib default UA — the fetcher must
    send its own (regression: live source silently fell back to cache)."""
    import urllib.request as _ur

    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": 1}'

    def fake_open(req, timeout=None):
        captured["req"] = req
        return _Resp()

    monkeypatch.setattr(_ur, "urlopen", fake_open)
    assert probe._default_fetcher(probe.CATALOG_URL, 5) == {"ok": 1}
    assert captured["req"].get_header("User-agent") == "model-switch"


def test_load_catalog_auto_falls_back_to_cache(tmp_path):
    cat = {"zai": {"api": "https://api.z.ai/x", "models": {
        "glm-5.3": {"reasoning_options": None}}}}
    cat_path = tmp_path / "models.json"
    cat_path.write_text(json.dumps(cat), encoding="utf-8")

    def boom(url, timeout):
        raise OSError("network down")

    data, desc = probe.load_catalog("auto", catalog_path=str(cat_path), fetcher=boom)
    assert data == cat and desc.startswith("cache")

    data, desc = probe.load_catalog("live", fetcher=boom)
    assert data is None and "live fetch failed" in desc

    def fetch(url, timeout):
        assert url == probe.CATALOG_URL
        return cat

    data, desc = probe.load_catalog("live", fetcher=fetch)
    assert data == cat and desc.startswith("live")


def test_cli_probe_json_and_apply(_isolate_yzr_state, monkeypatch):
    p = _isolate_yzr_state["models"]
    p.write_text(MODELS_TOML, encoding="utf-8")

    canned = [
        _res("control"),
        _res("disabled"),
        _res("adaptive-effort-low"),
        _res("adaptive-effort-high"),
    ]
    monkeypatch.setattr(probe, "probe",
                        lambda model, budgets=None, entry=None: canned)

    r = runner(["model", "probe", "glm-5_3-1m", "--json"])
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["model"] == "glm-5_3-1m"
    assert out["suggested"]["high"] == {"thinking": {"type": "adaptive"}, "effort": "high"}

    r2 = runner(["model", "probe", "glm-5_3-1m", "--apply"])
    assert r2.exit_code == 0, r2.stdout
    reg = load_models(p)
    assert "probe-glm-5_3-1m" in reg.extra_top["variants_presets"]


def test_cli_probe_unknown_model(_isolate_yzr_state):
    r = runner(["model", "probe", "nope"])
    assert r.exit_code == 1
    assert "not found" in r.stdout
