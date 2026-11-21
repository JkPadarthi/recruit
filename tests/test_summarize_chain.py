"""Chain order + resilience: OpenRouter first, local Ollama last, dead rungs skipped."""
import types

import app.summarize as S


def _settings(**kw):
    """Settings is a frozen dataclass — swap the module's handle for a stub."""
    base = dict(summarize_enabled=True, llm_base_url="", llm_api_key="k", llm_model="",
                llm_timeout_s=60)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_openrouter_comes_first_and_local_ollama_last():
    """A sleeping homelab box must never be the first thing we wait on."""
    kinds = [m["kind"] for m in S.DEFAULT_CHAIN]
    assert kinds[-1] == "local", "local Ollama must be the LAST rung"
    assert kinds[:-1] == ["openrouter"] * (len(kinds) - 1)


def test_dead_free_slug_is_gone_and_live_ones_are_used():
    models = [m["model"] for m in S.DEFAULT_CHAIN]
    assert "nvidia/nemotron-3-super-120b-a12b:free" not in models, "404'd slug must be removed"
    assert "nvidia/nemotron-3.5-lightning:free" in models
    assert "google/gemma-4-26b-a4b-it:free" in models
    assert "nvidia/nemotron-3-ultra-550b-a55b:free" in models


def test_local_rung_moves_to_the_end_even_when_configured(monkeypatch):
    monkeypatch.setattr(S, "settings", _settings(llm_base_url="http://127.0.0.1:11434/v1",
                                                 llm_model="gemma4:12b"))
    chain = S._chain()
    assert chain[-1]["kind"] == "local"
    assert chain[-1]["base_url"] == "http://127.0.0.1:11434/v1"
    assert all(m["kind"] == "openrouter" for m in chain[:-1])


def test_unreachable_rung_is_skipped_without_using_the_llm_timeout(monkeypatch):
    """The dead-box case: gate on a 1s TCP probe instead of a 60s read."""
    probed = []

    def fake_reachable(url, timeout=3.0):
        probed.append(url)
        return url.startswith("https://openrouter.ai")

    monkeypatch.setattr(S, "reachable", fake_reachable)
    monkeypatch.setattr(S, "settings", _settings(llm_base_url="http://10.255.255.1:11434/v1"))
    calls = []

    def fake_call(base_url, model, key, subject, body):
        calls.append(model)
        raise RuntimeError("nope")

    monkeypatch.setattr(S, "_call", fake_call)
    try:
        S.summarize("S", "B")
    except Exception as e:
        assert "nope" in str(e) or "unreachable" in str(e)
    assert "http://10.255.255.1:11434/v1" in probed     # the dead box was probed...
    assert "gemma4:12b" not in calls                    # ...and never called


def test_first_answering_rung_wins(monkeypatch):
    monkeypatch.setattr(S, "reachable", lambda url, timeout=3.0: True)
    seen = []

    def fake_call(base_url, model, key, subject, body):
        seen.append(model)
        if model == "nvidia/nemotron-3-ultra-550b-a55b:free":
            raise RuntimeError("429")
        return {"company": "HCL Tech", "summary": "ok", "result": False}

    monkeypatch.setattr(S, "_call", fake_call)
    out = S.summarize("S", "B")
    assert out["company"] == "HCL Tech"
    assert seen[0] == "nvidia/nemotron-3-ultra-550b-a55b:free"   # best rung first
    assert seen[1] == "google/gemma-4-26b-a4b-it:free"


def test_chain_health_is_empty_when_summarizing_is_off(monkeypatch):
    monkeypatch.setattr(S, "settings", _settings(summarize_enabled=False))
    assert S.chain_health() == [], "no probes when the feature is disabled"


async def test_status_exposes_usable_rungs(client, register, monkeypatch):
    monkeypatch.setattr("app.main._summary_health", lambda: [
        {"model": "a:free", "kind": "openrouter", "base_url": "u1", "reachable": True},
        {"model": "b:free", "kind": "openrouter", "base_url": "u2", "reachable": False},
        {"model": "gemma4:12b", "kind": "local", "base_url": "u3", "reachable": False},
    ])
    await register()
    st = (await client.get("/api/status")).json()
    assert st["summary_providers_usable"] == 1
    assert [r["reachable"] for r in st["summary_chain"]] == [True, False, False]
