"""LLM summarizer: schema validation, dedup hash, fail-open behavior."""
import pytest

from app.summarize import DEFAULT_CHAIN, content_hash, _chain, _validate


def test_content_hash_dedups_duplicates():
    a = content_hash("Honeywell drive", "Apply now  for the internship  on  Tuesday")
    b = content_hash("Honeywell drive", "Apply now for the internship on Tuesday")
    assert a == b


def test_content_hash_differs_on_subject():
    a = content_hash("A", "body")
    b = content_hash("B", "body")
    assert a != b


def test_valid_dicts():
    assert _validate({"company": "Honeywell", "summary": "Hi"})
    assert _validate({"company": "X", "summary": "y"})  # non-empty strings


def test_invalid_dicts():
    assert not _validate({"company": 5, "summary": "x"})       # wrong type
    assert not _validate({"summary": "x"})                     # missing company
    assert not _validate({"company": "", "summary": ""})       # empty company
    assert not _validate("not a dict")
    assert not _validate(None)


def test_chain_skips_empty_bases():
    # with no settings, only defaults that have base_url remain
    chain = _chain()
    assert isinstance(chain, list)
    assert all(m.get("base_url") for m in chain)


def test_default_chain_ordered():
    # P0 local first, then gemma, nemotron, qwen
    models = [m["model"] for m in DEFAULT_CHAIN]
    assert models[0] == "gemma4:12b"
    assert "gemma" in models[1].lower()
    assert "nemotron" in models[2].lower()
    assert "qwen" in models[3].lower()