"""LLM summarizer for Recruit (GATED behind SUMMARIZE_ENABLED).

Deterministic matcher stays the source of truth; this layer only produces a
human-readable structured summary + advisory flags. It can never hide or invent
a selection — worst case it degrades to shipping the raw mail (fail-open).

Priority chain (locked 2026-10-01):
  P0 local Ollama gemma4:12b  ->  P1 gemma-4-26b:free  ->  P2 nemotron-super:free
  ->  P3 qwen3.8-27b:free  ->  fail-open ship raw mail (summary_status='deferred')
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

# P0 -> P3 in order. Each is (base_url, api_key, model). "" base = skip.
# Resolved at call-time from settings + defaults so tests can inject.
DEFAULT_CHAIN: list[dict] = [
    {"base_url": "", "api_key": "", "model": "gemma4:12b",             "kind": "local"},
    {"base_url": "https://openrouter.ai/api/v1", "api_key": "", "model": "google/gemma-4-26b-a4b-it:free", "kind": "openrouter"},
    {"base_url": "https://openrouter.ai/api/v1", "api_key": "", "model": "nvidia/nemotron-3-super-120b-a12b:free", "kind": "openrouter"},
    {"base_url": "https://openrouter.ai/api/v1", "api_key": "", "model": "qwen/qwen3.8-27b:free",          "kind": "openrouter"},
]


def content_hash(subject: str, body: str) -> str:
    """Dedup key: hash subject + normalized body. VIT re-blats duplicates with
    near-identical content, so this trims repeated LLM calls."""
    return hashlib.sha1((subject + "|" + " ".join(body.split())).encode()).hexdigest()[:16]


def _chain() -> list[dict]:
    """Build the effective chain: settings.llm_* override P0 when provided."""
    chain = [dict(x) for x in DEFAULT_CHAIN]
    if settings.llm_base_url:
        chain[0].update({"base_url": settings.llm_base_url,
                         "api_key": settings.llm_api_key,
                         "model": settings.llm_model or chain[0]["model"]})
    return [m for m in chain if m.get("base_url")]


def _validate(data) -> bool:
    """Schema sanity: types must broadly match. Never rejects on missing fields;
    only on structurally wrong types (which would break consumers)."""
    if not isinstance(data, dict):
        return False
    for key, typ in SUMMARY_SCHEMA.items():
        if key in data and not isinstance(data[key], (typ,)) and typ is not list:
            return False
        if typ is list and key in data and not isinstance(data[key], list):
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
                "is a selection/shortlist OUTCOME.")},
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
        return json.loads(content)
    except Exception as e:  # network, HTTP, JSON parse
        log.warning("LLM call failed (%s %s): %s", base_url, model, e)
        raise


def summarize(subject: str, body: str) -> dict:
    """Walk the priority chain, return the first valid summary dict.
    Raises the last error if the whole chain fails (caller decides fail-open)."""
    last_err: Exception | None = None
    for link in _chain():
        try:
            parsed = _call(link["base_url"], link["model"], link["api_key"], subject, body)
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