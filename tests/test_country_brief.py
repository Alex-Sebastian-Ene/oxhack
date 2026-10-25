"""Offline tests for experiments/country_brief.py: no network and no API key needed."""

import importlib.util
import json
import threading
import urllib.request
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("country_brief", Path(__file__).resolve().parent.parent / "experiments" / "country_brief.py")
cb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cb)

GEMINI_REPLY = {
    "candidates": [{
        "content": {"parts": [{"text": "- China made 52% of world steel in 2025 [data]."}, {"text": "\n- Imports ore from Australia."}]},
        "finishReason": "STOP",
        "groundingMetadata": {"groundingChunks": [
            {"web": {"uri": "https://example.org/a", "title": "example.org"}},
            {"web": {"uri": "https://example.org/a", "title": "dup"}},
            {"web": {"uri": "https://example.org/b"}},
        ]},
    }],
}


def test_parse_joins_parts_and_dedupes_sources():
    out = cb.parse(GEMINI_REPLY)
    assert out["text"].startswith("- China made 52%") and "Australia" in out["text"]
    assert [s["uri"] for s in out["sources"]] == ["https://example.org/a", "https://example.org/b"]


def test_parse_raises_on_blocked_or_empty():
    with pytest.raises(ValueError, match="SAFETY"):
        cb.parse({"promptFeedback": {"blockReason": "SAFETY"}})
    with pytest.raises(ValueError, match="empty"):
        cb.parse({"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]})


def test_request_uses_search_grounding_and_our_facts():
    body = cb.request_body("China", "Crude steel", ["Crude steel, production: 52% of world (2025; https://worldsteel.org)"])
    assert body["tools"] == [{"google_search": {}}]
    text = body["contents"][0]["parts"][0]["text"]
    assert "China" in text and "52% of world" in text and "[data]" in text


def test_origins():
    assert cb.allowed_origin(None) and cb.allowed_origin("null")
    assert cb.allowed_origin("http://localhost:5173") and cb.allowed_origin("http://127.0.0.1:8000")
    assert not cb.allowed_origin("https://evil.example") and not cb.allowed_origin("http://localhost.evil.example")


def test_brief_caches_and_needs_key(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "CACHE", tmp_path)
    calls = []
    monkeypatch.setattr(cb, "ask_gemini", lambda body, key: calls.append(key) or GEMINI_REPLY)
    payload = {"iso3": "chn", "country": "China", "material": "Crude steel", "facts": ["a"]}
    with pytest.raises(PermissionError):
        cb.brief(payload, None)
    first = cb.brief(payload, "k")
    again = cb.brief(payload, None)  # served from cache, no key needed
    assert first["cached"] is False and again["cached"] is True and calls == ["k"]
    assert again["text"] == first["text"] and again["iso3"] == "CHN" and again["generated_at"] == first["generated_at"]
    assert "k" not in json.dumps(json.loads(next(tmp_path.iterdir()).read_text()))  # the key is never stored


def test_server_refuses_other_origins(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "CACHE", tmp_path)
    monkeypatch.setattr(cb, "ask_gemini", lambda body, key: GEMINI_REPLY)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    srv = cb.ThreadingHTTPServer(("127.0.0.1", 0), cb.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/brief"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # straight to localhost, even behind a proxy
    data = json.dumps({"iso3": "CHN", "material": "Crude steel"}).encode()

    def post(origin):
        req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json", "Origin": origin})
        try:
            with opener.open(req) as r:
                return r.status, json.loads(r.read()), r.headers.get("Access-Control-Allow-Origin")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read()), None

    try:
        code, body, cors = post("null")
        assert code == 200 and body["text"] and cors == "null"
        code, body, _ = post("https://evil.example")
        assert code == 403
    finally:
        srv.shutdown()


def test_load_env_reads_dotenv_without_overriding(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nexport BRIEF_TEST_A='one'\nBRIEF_TEST_B=two\nBRIEF_TEST_C=from-file\nnot a pair\n")
    monkeypatch.delenv("BRIEF_TEST_A", raising=False)
    monkeypatch.delenv("BRIEF_TEST_B", raising=False)
    monkeypatch.setenv("BRIEF_TEST_C", "from-env")
    cb.load_env(env)
    assert cb.os.environ["BRIEF_TEST_A"] == "one" and cb.os.environ["BRIEF_TEST_B"] == "two"
    assert cb.os.environ["BRIEF_TEST_C"] == "from-env"  # the environment wins
    monkeypatch.delenv("BRIEF_TEST_A")
    monkeypatch.delenv("BRIEF_TEST_B")
