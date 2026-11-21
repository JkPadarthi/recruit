"""LLM summarizer for Recruit (GATED behind SUMMARIZE_ENABLED).

Deterministic matcher stays the source of truth; this layer only produces a
human-readable structured summary + advisory flags. It can never hide or invent
a selection — worst case it degrades to shipping the raw mail (fail-open).

Priority chain (order reversed 2026-11-21 at the user's request): OpenRouter
FIRST because it is a public endpoint that either answers in a second or fails
in a second, then the local Ollama box LAST as the offline fallback — a dead or
sleeping box must never delay a summary that a remote rung could have served.

  P0 gemma-4-26b:free -> P1 nemotron-3.5-lightning:free -> P2 nemotron-ultra:free
  -> P3 local Ollama (LLM_BASE_URL) -> fail-open ship raw mail (status=deferred)

Free slugs ROT: qwen3.8-27b:free and nemotron-3-super-120b:free were both
withdrawn and 404'd. Verify a rung against GET /api/v1/models before trusting it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from .config import settings

log = logging.getLogger("recruit.summarize")

SUMMARY_SCHEMA = {
    "company": str,
    "category": str,        # shortlist|drive|test|interview|registration|other
    "role": str,
    "package": str,         # "₹8 LPA" or ""
    "event_date": str,      # ISO date or ""
    "deadline": str,        # ISO date or ""
    "eligible_branches": list,
    "apply_link": str,
    "result": bool,         # is this a selection OUTCOME?
    "summary": str,         # one-line human summary
    "interesting": bool,    # advisory focus flag
}

# Ordered by MEASURED latency + reliability (2026-11-21 bench, 3 tries each):
#   nemotron-3-ultra    3/3 valid  6.0-12.5s   <- first: it carries the load
#   gemma-4-26b         rate-limited (429) but fast when free
#   nemotron-3.5-lightning 3/3 valid 22-59s    <- slow reasoning model, last resort
#   local Ollama        offline fallback; probed, never waited on
DEFAULT_CHAIN: list[dict] = [
    {"base_url": "https://openrouter.ai/api/v1", "api_key": "",
     "model": "nvidia/nemotron-3-ultra-550b-a55b:free", "kind": "openrouter"},
    {"base_url": "https://openrouter.ai/api/v1", "api_key": "",
     "model": "google/gemma-4-26b-a4b-it:free", "kind": "openrouter"},
    {"base_url": "https://openrouter.ai/api/v1", "api_key": "",
     "model": "nvidia/nemotron-3.5-lightning:free", "kind": "openrouter"},
    {"base_url": "", "api_key": "", "model": "gemma4:12b", "kind": "local"},
]


def content_hash(subject: str, body: str) -> str:
    """Dedup key: hash subject + normalized body. VIT re-blats duplicates with
    near-identical content, so this trims repeated LLM calls."""
    return hashlib.sha1((subject + "|" + " ".join(body.split())).encode()).hexdigest()[:16]


def _chain() -> list[dict]:
    """Build the effective chain: OpenRouter rungs first, local Ollama last.

    settings.llm_base_url fills the LOCAL rung (wherever it sits) and the local
    rung is forced to the end so a sleeping homelab box can never delay a
    summary that a public endpoint could have served.
    """
    chain = [dict(x) for x in DEFAULT_CHAIN]
    local = next((m for m in chain if m.get("kind") == "local"), None)
    if local is not None:
        if settings.llm_base_url:
            local.update({"base_url": settings.llm_base_url,
                          "api_key": settings.llm_api_key,
                          "model": settings.llm_model or local["model"]})
        chain = [m for m in chain if m is not local] + [local]
    # Propagate the configured key to every provider that lacks one. The local
    # Ollama tier ignores auth, but OpenRouter requires a key EVEN for `:free`
    # models -- without a key those calls 401 before the model is reached, so
    # the whole fallback ladder is inert and any hiccup falls straight through
    # to summary_status='deferred'.
    if settings.llm_api_key:
        for m in chain:
            if not m.get("api_key"):
                m["api_key"] = settings.llm_api_key
    return [m for m in chain if m.get("base_url")]


def reachable(base_url: str, timeout: float = 3.0) -> bool:
    """Cheap TCP connect, so a dead host costs ~3s instead of the full LLM timeout.

    A 60s read timeout on an unplugged box is 60s of a 180s poll window wasted on
    every single mail — measured live, that was the whole summarizer's latency.
    """
    import socket
    from urllib.parse import urlparse

    try:
        u = urlparse(base_url)
        host = u.hostname
        port = u.port or (443 if u.scheme == "https" else 80)
        if not host:
            return False
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_HEALTH: dict[str, Any] = {"at": 0.0, "value": []}


def chain_health(timeout: float = 1.5, ttl: float = 30.0) -> list[dict]:
    """[{model, kind, reachable}] for /api/status + the Prometheus gauge.

    Cached (30s) because a scrape or a status hit must never block on probes.
    Returns [] when summarizing is disabled — no point probing a sleeping feature.
    """
    if not settings.summarize_enabled:
        return []
    now = time.time()
    if _HEALTH["value"] and now - _HEALTH["at"] < ttl:
        return _HEALTH["value"]
    out = [{"model": m["model"], "kind": m.get("kind", ""),
            "base_url": m["base_url"], "reachable": reachable(m["base_url"], timeout)}
           for m in _chain()]
    _HEALTH.update(at=now, value=out)
    return out


def _normalize_aliases(data: dict) -> dict:
    """Map common model output variants to canonical schema keys and flatten nulls."""
    alias = {
        "company_name": "company",
        "role_name": "role",
        "ctc": "package",
        "lpa": "package",
        "interview_date": "event_date",
        "registration_deadline": "deadline",
    }
    for src, dst in alias.items():
        if src in data and dst not in data:
            data[dst] = data.pop(src)
    # never store raw nulls — consumers expect "" / []
    for key, typ in SUMMARY_SCHEMA.items():
        if key in data and data[key] is None:
            data[key] = [] if typ is list else ""
    return data


def _validate(data) -> bool:
    """Schema sanity: types must broadly match. Never rejects on missing fields;
    only on structurally wrong types (which would break consumers).
    None (null) is accepted — the model legitimately emits null for absent fields."""
    if not isinstance(data, dict):
        return False
    for key, typ in SUMMARY_SCHEMA.items():
        if key in data and data[key] is not None:
            if typ is list:
                if not isinstance(data[key], list):
                    return False
            elif not isinstance(data[key], typ):
                return False
    # requires the two fields consumers depend on to be present AND strings
    return (isinstance(data.get("company"), str) and data.get("company", "") != ""
            and isinstance(data.get("summary"), str) and data.get("summary", "") != "")


def _call(base_url: str, model: str, api_key: str, subject: str, body: str) -> dict:
    """POST a single OpenAI-compatible chat completion, return parsed JSON dict."""
    import urllib.request

    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": (
                "You extract structured details from a VIT placement (CDC) email into JSON. "
                "Only JSON output. Never invent fields: use empty string/null when absent. "
                "summary is a one-line plain-English summary. result=true only if this mail "
                "is a selection/shortlist OUTCOME. IMPORTANT TONE RULE: if this is a FINAL "
                "SELECTION or OFFER (the student has been SELECTED, received an offer letter, "
                "or appears on a final selection list), make `summary` genuinely celebratory "
                "and warm, e.g. '🎉 Congratulations! You've been selected for the Analyst role "
                "at Deloitte India.' — do NOT write a dry phrase like 'Selection list for ...'. "
                "If it is merely a shortlist or a non-result announcement, keep `summary` "
                "neutral and factual. Use EXACTLY these keys (no others, never "
                "variants like company_name or role_name): company, category, role, package, "
                "event_date, deadline, eligible_branches (array of strings), apply_link, "
                "result (boolean), summary, interesting (boolean).")},
            {"role": "user", "content": f"SUBJECT:\n{subject}\n\nBODY:\n{body[:4000]}"},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=settings.llm_timeout_s) as resp:
            out = json.loads(resp.read().decode())
        content = out["choices"][0]["message"]["content"]
        return _extract_json(content)
    except Exception as e:  # network, HTTP, JSON parse
        log.warning("LLM call failed (%s %s): %s", base_url, model, e)
        raise


def _extract_json(content: str) -> dict:
    """Parse model output that may be wrapped in a markdown ```json fence."""
    s = content.strip()
    # strip a leading ```json / ``` and trailing ``` if present
    if s.startswith("```"):
        body = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
        s = body.strip()
    return json.loads(s)


def summarize(subject: str, body: str) -> dict:
    """Walk the priority chain, return the first valid summary dict.
    Raises the last error if the whole chain fails (caller decides fail-open)."""
    last_err: Exception | None = None
    for link in _chain():
        # Cheap reachability gate FIRST: skip an unplugged endpoint in ~1-3s
        # rather than burning the full read timeout on it.
        if not reachable(link["base_url"]):
            last_err = ConnectionError(f"{link['base_url']} unreachable")
            log.warning("skip unreachable LLM endpoint %s (%s)",
                        link["base_url"], link["model"])
            continue
        try:
            parsed = _call(link["base_url"], link["model"], link["api_key"], subject, body)
            parsed = _normalize_aliases(parsed)
            if _validate(parsed):
                return parsed
            log.warning("invalid summary schema from %s", link["model"])
            last_err = ValueError(f"bad schema from {link['model']}")
        except Exception as e:
            last_err = e
        # backoff between link attempts (don't hammer)
        time.sleep(0.3)
    if last_err:
        raise last_err
    raise RuntimeError("no LLM endpoints configured in chain")
