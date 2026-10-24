"""Offline tests for ui/industry/extract_server.py: no network and no API key needed."""

import base64
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "extract_server", Path(__file__).resolve().parent.parent / "ui" / "industry" / "extract_server.py")
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)


def reply(obj):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}, "finishReason": "STOP"}]}


def test_parse_keeps_good_rows_and_cleans_bad_fields():
    rows = ex.parse(reply({"items": [
        {"item": "Urea 46% N", "material": "fertiliser", "country_iso3": "omn", "supplier": "OMIFCO", "quantity": "2,000 t"},
        {"item": "Widgets", "material": "gizmos", "country_iso3": "Oman"},
        {"item": "", "material": "steel", "country_iso3": "CHN"},
        "not a row",
    ]}))
    assert rows == [
        {"item": "Urea 46% N", "material": "fertiliser", "country_iso3": "OMN", "supplier": "OMIFCO", "quantity": "2,000 t"},
        {"item": "Widgets", "material": "other", "country_iso3": "", "supplier": "", "quantity": ""},
    ]


def test_parse_raises_on_blocked_empty_or_not_json():
    with pytest.raises(ValueError, match="SAFETY"):
        ex.parse({"promptFeedback": {"blockReason": "SAFETY"}})
    with pytest.raises(ValueError, match="empty"):
        ex.parse({"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]})
    with pytest.raises(ValueError, match="not valid JSON"):
        ex.parse({"candidates": [{"content": {"parts": [{"text": "{oops"}]}, "finishReason": "MAX_TOKENS"}]})


def test_request_body_sends_files_inline_and_text_as_text():
    pdf = ex.request_body("application/pdf", b"%PDF-1.4")
    part = pdf["contents"][0]["parts"][1]
    assert part["inlineData"]["mimeType"] == "application/pdf"
    assert base64.b64decode(part["inlineData"]["data"]) == b"%PDF-1.4"
    assert pdf["generationConfig"]["responseMimeType"] == "application/json"
    assert "tools" not in pdf  # no Google Search: plain quota only
    csv = ex.request_body("text/csv", b"item,country\nurea,Oman\n")
    assert "urea,Oman" in csv["contents"][0]["parts"][1]["text"]
    with pytest.raises(ValueError, match="not supported"):
        ex.request_body("application/zip", b"PK")


def test_extract_checks_input_before_any_request(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "CACHE", tmp_path)
    monkeypatch.setattr(ex, "ask_gemini", lambda *a: pytest.fail("must not call Gemini"))
    with pytest.raises(ValueError, match="empty"):
        ex.extract({"mime": "text/csv", "data": ""}, "key")
    with pytest.raises(ValueError, match="base64"):
        ex.extract({"mime": "text/csv", "data": "not base64!"}, "key")
    with pytest.raises(PermissionError):
        ex.extract({"mime": "text/csv", "data": base64.b64encode(b"urea,Oman").decode()}, None)


def test_extract_caches_by_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "CACHE", tmp_path)
    calls = []
    monkeypatch.setattr(ex, "ask_gemini", lambda body, key: calls.append(1) or reply(
        {"items": [{"item": "Urea", "material": "fertiliser", "country_iso3": "OMN"}]}))
    payload = {"mime": "text/csv", "name": "suppliers.csv", "data": base64.b64encode(b"urea,Oman").decode()}
    first = ex.extract(payload, "key")
    second = ex.extract(payload, None)  # served from the cache, so no key needed
    assert first["cached"] is False and second["cached"] is True
    assert second["rows"] == first["rows"] and len(calls) == 1


def test_allowed_origin(monkeypatch):
    monkeypatch.delenv("EXTRACT_ORIGINS", raising=False)
    assert ex.allowed_origin(None) and ex.allowed_origin("null")
    assert ex.allowed_origin("http://localhost:8765") and ex.allowed_origin("http://127.0.0.1:3000")
    assert not ex.allowed_origin("https://evil.example")
    monkeypatch.setenv("EXTRACT_ORIGINS", "https://hormuz.example")
    assert ex.allowed_origin("https://hormuz.example")
