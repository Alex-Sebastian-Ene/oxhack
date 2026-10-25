"""Offline tests for ui/industry/explain_server.py: no network and no API key needed."""

import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "explain_server", Path(__file__).resolve().parent.parent / "ui" / "industry" / "explain_server.py")
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)

FACTS = ["Nitrogen fertiliser price +27.3% in 12 months at Brent $104 (Seb's Bayesian model)",
         "About 38% of India's oil use comes through Hormuz (this page's country table)",
         "46% of India's imported urea comes from Oman (2025)"]


def reply(obj):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}, "finishReason": "STOP"}]}


def test_numbers_normalises_signs_commas_and_decimals():
    assert ex.numbers("+27.3% and −1,500 t, 38.0 or 2026") == {"27.3", "1500", "38", "2026"}


def test_check_flags_numbers_not_in_the_cited_facts():
    out = ex.check([
        {"text": "Fertiliser costs rise about 27.3% as Brent reaches $104.", "facts": [1]},
        {"text": "India gets 38% of its oil via Hormuz, and 60% of its urea from Oman.", "facts": [2, 3, 9]},
        {"text": "   ", "facts": [1]},
        "not a bullet",
    ], FACTS)
    assert [b["facts"] for b in out] == [[1], [2, 3]]      # fact 9 does not exist
    assert out[0]["unsupported"] == []
    assert out[1]["unsupported"] == ["60"]                  # 60% is in no fact


def test_check_without_citations_uses_all_facts():
    out = ex.check([{"text": "Urea from Oman: 46%; oil via Hormuz: 38%.", "facts": []}], FACTS)
    assert out[0]["unsupported"] == []


def test_parse_raises_on_blocked_empty_bad_json_or_no_bullets():
    with pytest.raises(ValueError, match="SAFETY"):
        ex.parse({"promptFeedback": {"blockReason": "SAFETY"}}, FACTS)
    with pytest.raises(ValueError, match="empty"):
        ex.parse({"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]}, FACTS)
    with pytest.raises(ValueError, match="not valid JSON"):
        ex.parse({"candidates": [{"content": {"parts": [{"text": "{oops"}]}}]}, FACTS)
    with pytest.raises(ValueError, match="no explanation"):
        ex.parse(reply({"bullets": []}), FACTS)


def test_request_body_numbers_the_facts_and_uses_no_tools():
    body = ex.request_body("product", "Nitrogen fertiliser", FACTS)
    text = body["contents"][0]["parts"][0]["text"]
    assert "[1] Nitrogen fertiliser price +27.3%" in text and "[3] 46% of India's" in text
    assert "Do not add any number" in text
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}  # fast: default thinking took over a minute
    assert body["generationConfig"]["maxOutputTokens"] >= 4096  # thinking counts against this limit
    assert "tools" not in body  # no Google Search: plain quota only


def test_explain_checks_input_before_any_request(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "CACHE", tmp_path)
    monkeypatch.setattr(ex, "ask_gemini", lambda *a: pytest.fail("must not call Gemini"))
    with pytest.raises(ValueError, match="kind"):
        ex.explain({"kind": "poem", "subject": "India", "facts": FACTS}, "key")
    with pytest.raises(ValueError, match="at least one fact"):
        ex.explain({"kind": "country", "subject": "India", "facts": ["  "]}, "key")
    with pytest.raises(PermissionError):
        ex.explain({"kind": "country", "subject": "India", "facts": FACTS}, None)


def test_explain_caches_the_same_question(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "CACHE", tmp_path)
    calls = []
    monkeypatch.setattr(ex, "ask_gemini", lambda body, key: calls.append(1) or reply(
        {"bullets": [{"text": "Fertiliser is up 27.3%.", "facts": [1]}]}))
    payload = {"kind": "product", "subject": "Nitrogen fertiliser", "facts": FACTS}
    first = ex.explain(payload, "key")
    second = ex.explain(payload, None)  # served from the cache, so no key needed
    assert first["cached"] is False and second["cached"] is True
    assert second["bullets"] == first["bullets"] and second["facts"] == FACTS and len(calls) == 1


def test_allowed_origin(monkeypatch):
    monkeypatch.delenv("EXPLAIN_ORIGINS", raising=False)
    assert ex.allowed_origin(None) and ex.allowed_origin("null") and ex.allowed_origin("http://localhost:8765")
    assert not ex.allowed_origin("https://evil.example")
    monkeypatch.setenv("EXPLAIN_ORIGINS", "https://hormuz.example")
    assert ex.allowed_origin("https://hormuz.example")
