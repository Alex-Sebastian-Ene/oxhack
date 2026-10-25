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


INTERACTION_TEXT = {"id": "i1", "steps": [{"type": "user_input", "content": [{"type": "text", "text": "q"}]},
                                           {"type": "thought", "signature": "s"},
                                           {"type": "model_output", "content": [{"type": "text", "text": "- Steel is iron with carbon [1]."}]}]}
INTERACTION_IMAGE = {"id": "i2", "steps": [{"type": "model_output", "content": [{"type": "image", "data": "iVBORw0KGgo=", "mime_type": "image/png"}]}]}


def test_outputs_reads_interactions_and_generatecontent_shapes():
    assert cb.outputs(INTERACTION_TEXT) == ("- Steel is iron with carbon [1].", None)
    text, img = cb.outputs(INTERACTION_IMAGE)
    assert text == "" and img["mime_type"] == "image/png"
    text, img = cb.outputs({"candidates": [{"content": {"parts": [{"text": "hi"}, {"inlineData": {"data": "AAA", "mimeType": "image/png"}}]}}]})
    assert text == "hi" and img["data"] == "AAA"


def test_resource_asks_for_text_and_a_pixel_picture(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "CACHE", tmp_path)
    monkeypatch.setattr(cb, "FAKE", False)
    calls = []
    monkeypatch.setattr(cb, "interact", lambda model, text, key: calls.append((model, text)) or (INTERACTION_TEXT if model == cb.MODEL else INTERACTION_IMAGE))
    out = cb.resource({"id": "steel", "name": "Crude steel", "facts": ["China made 52% of world steel in 2025"]}, "k")
    assert out["text"].startswith("- Steel") and out["image"].startswith("data:image/png;base64,")
    assert [m for m, _ in calls] == [cb.MODEL, cb.IMAGE_MODEL]
    assert "[1] China made 52%" in calls[0][1] and "pixel-art" in calls[1][1] and "No text" in calls[1][1]
    assert cb.resource({"id": "steel", "name": "Crude steel", "facts": ["China made 52% of world steel in 2025"]}, None)["cached"] is True
    with pytest.raises(PermissionError):
        cb.resource({"id": "urea", "name": "Urea"}, None)


def test_country_profile_cites_only_our_facts(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "CACHE", tmp_path)
    monkeypatch.setattr(cb, "FAKE", False)
    seen = []
    monkeypatch.setattr(cb, "interact", lambda model, text, key: seen.append(text) or INTERACTION_TEXT)
    out = cb.country({"iso3": "kor", "country": "South Korea", "facts": ["Jet fuel exports: 14% of world, rank 2 (2025)"]}, "k")
    assert out["iso3"] == "KOR" and out["text"] and "[1] Jet fuel exports" in seen[0] and "Do not add numbers" in seen[0]
    assert out["model"] == cb.MODEL   # the response names no model, so the one asked for
    with pytest.raises(ValueError):
        cb.country({"iso3": "KOR"}, "k")


def test_answers_name_the_model_that_served_them(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "CACHE", tmp_path)
    monkeypatch.setattr(cb, "FAKE", False)
    monkeypatch.setattr(cb, "interact", lambda model, text, key: {**INTERACTION_TEXT, "model": "gemini-other"})
    assert cb.country({"iso3": "JPN", "country": "Japan", "facts": ["a"]}, "k")["model"] == "gemini-other"
    assert cb.resource({"id": "urea", "name": "Urea", "facts": ["a"]}, "k", image=False)["model"] == "gemini-other"


def test_fake_mode_is_labelled_and_needs_no_key(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "CACHE", tmp_path)
    monkeypatch.setattr(cb, "FAKE", True)
    r = cb.resource({"id": "naphtha", "name": "Naphtha"}, None)
    c = cb.country({"iso3": "JPN", "country": "Japan", "facts": ["a"]}, None)
    assert "TEST ANSWER" in r["text"] and "TEST ANSWER" in c["text"] and r["model"].startswith("test")
    import base64
    raw = base64.b64decode(r["image"].split(",", 1)[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n" and raw[12:16] == b"IHDR"


def test_check_without_a_key_fails_without_calling_out(capsys):
    assert cb.check(None) == 1
    assert "nothing to check" in capsys.readouterr().out


def test_http_error_reads_both_error_shapes():
    import io, urllib.error
    for body in (b'{"error": {"code": 401, "message": "bad key"}}', b'[{"error": {"code": 401, "message": "bad key"}}]', b"not json"):
        e = urllib.error.HTTPError("https://example.invalid", 401, "Unauthorized", {}, io.BytesIO(body))
        msg = cb._http_error(e)
        assert msg.startswith("HTTP 401")
        assert ("bad key" in msg) == body.startswith((b"{", b"["))


def test_resource_keeps_the_text_when_the_picture_is_refused(tmp_path, monkeypatch):
    import io, urllib.error
    monkeypatch.setattr(cb, "CACHE", tmp_path)
    monkeypatch.setattr(cb, "FAKE", False)

    def interact(model, text, key):
        if model == cb.IMAGE_MODEL:   # a free-tier key: no image quota
            raise urllib.error.HTTPError("https://example.invalid", 429, "Too Many Requests", {}, io.BytesIO(b'{"error": {"message": "limit: 0"}}'))
        return INTERACTION_TEXT
    monkeypatch.setattr(cb, "interact", interact)
    out = cb.resource({"id": "steel", "name": "Crude steel", "facts": ["a"]}, "k")
    assert out["text"].startswith("- Steel") and out["image"] is None and out["image_model"] is None
    calls = []
    monkeypatch.setattr(cb, "interact", lambda model, text, key: calls.append(model) or INTERACTION_TEXT)
    cb.resource({"id": "urea", "name": "Urea", "facts": ["a"]}, "k", image=False)
    assert calls == [cb.MODEL]


def test_retrying_waits_out_rate_limits(monkeypatch):
    import io, urllib.error
    monkeypatch.setattr("time.sleep", lambda s: None)
    tries = []

    def flaky():
        tries.append(1)
        if len(tries) < 3:
            raise urllib.error.HTTPError("https://example.invalid", 429 if len(tries) == 1 else 503, "busy", {}, io.BytesIO(b"{}"))
        return "ok"
    assert cb._retrying(flaky, "x") == "ok" and len(tries) == 3
    with pytest.raises(urllib.error.HTTPError):   # a bad request is not retried
        cb._retrying(lambda: (_ for _ in ()).throw(urllib.error.HTTPError("https://example.invalid", 400, "bad", {}, io.BytesIO(b"{}"))), "y")


def test_bake_writes_every_panel_with_its_facts_and_setting(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "CACHE", tmp_path)
    monkeypatch.setattr(cb, "FAKE", True)
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"setting": "2026-closure", "read_at": "2026-10-25T08:00:00Z",
                                 "resources": [{"id": "steel", "name": "Crude steel", "facts": ["a", "b"]}],
                                 "countries": [{"iso3": "JPN", "country": "Japan", "facts": ["c"]}]}))
    out = tmp_path / "ai-panels.json"
    assert cb.bake(None, facts, out, workers=2) == 0
    d = json.loads(out.read_text())
    assert d["setting"] == "2026-closure" and set(d["resources"]) == {"steel"} and set(d["countries"]) == {"JPN"}
    assert d["resources"]["steel"]["facts"] == ["a", "b"] and "image" not in d["resources"]["steel"]
    assert d["countries"]["JPN"]["country"] == "Japan" and "TEST ANSWER" in d["countries"]["JPN"]["text"] and d["written"]


def test_bake_keeps_earlier_answers_and_stops_at_the_daily_quota(tmp_path, monkeypatch):
    import io, urllib.error
    monkeypatch.setattr(cb, "CACHE", tmp_path)
    monkeypatch.setattr(cb, "FAKE", False)
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"setting": "2026-closure", "resources": [{"id": "steel", "name": "Crude steel", "facts": ["a"]}],
                                 "countries": [{"iso3": "JPN", "country": "Japan", "facts": ["c", "d"]}, {"iso3": "FJI", "country": "Fiji", "facts": ["e"]}]}))
    out = tmp_path / "ai-panels.json"
    out.write_text(json.dumps({"resources": {"steel": {"name": "Crude steel", "text": "- old", "facts": ["a"], "model": "m0", "generated_at": "2026-10-25T08:00:00+00:00"}}}))
    asked = []

    def interact(model, text, key):
        asked.append(text)
        if len(asked) > 1:   # the second call finds the day's quota used up
            raise urllib.error.HTTPError("https://example.invalid", 429, "Too Many Requests", {"Retry-After": "79000"}, io.BytesIO(b"{}"))
        return INTERACTION_TEXT
    monkeypatch.setattr(cb, "interact", interact)
    assert cb.bake("k", facts, out, workers=1) == 1
    d = json.loads(out.read_text())
    assert d["resources"]["steel"]["text"] == "- old"   # kept: same facts, no call
    assert set(d["countries"]) == {"JPN"} and d["missing"] == ["FJI"]   # Japan first: it has more facts
    assert "Japan" in asked[0] and len(asked) == 2


def test_bake_gives_up_on_a_model_that_keeps_failing(tmp_path, monkeypatch):
    import io, urllib.error
    monkeypatch.setattr(cb, "CACHE", tmp_path)
    monkeypatch.setattr(cb, "FAKE", False)
    monkeypatch.setattr("time.sleep", lambda s: None)
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"setting": "2026-closure", "resources": [],
                                 "countries": [{"iso3": f"C{i:02d}", "country": f"Country {i}", "facts": ["x"]} for i in range(10)]}))
    out = tmp_path / "ai-panels.json"
    asked = []

    def interact(model, text, key):   # overloaded: every call is a 503
        asked.append(text)
        raise urllib.error.HTTPError("https://example.invalid", 503, "Service Unavailable", {}, io.BytesIO(b"{}"))
    monkeypatch.setattr(cb, "interact", interact)
    assert cb.bake("k", facts, out, workers=1) == 10
    assert len(asked) == cb.STUCK * 6   # STUCK countries, six tries each, then no more calls
    assert len(json.loads(out.read_text())["missing"]) == 10


def test_bake_keeps_an_answer_whose_long_facts_were_cut(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "CACHE", tmp_path)
    monkeypatch.setattr(cb, "FAKE", False)
    long = "x" * 450   # the service sends at most 400 characters of a fact, and stores what it sent
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"setting": "2026-closure", "resources": [], "countries": [{"iso3": "LBN", "country": "Lebanon", "facts": [long]}]}))
    out = tmp_path / "ai-panels.json"
    asked = []
    monkeypatch.setattr(cb, "interact", lambda model, text, key: asked.append(text) or INTERACTION_TEXT)
    assert cb.bake("k", facts, out, workers=1) == 0 and len(asked) == 1
    assert json.loads(out.read_text())["countries"]["LBN"]["facts"] == ["x" * 400]
    for f in tmp_path.glob("cty-*.json"):
        f.unlink()   # not from the cache: a rerun keeps the baked answer without asking
    assert cb.bake("k", facts, out, workers=1) == 0 and len(asked) == 1


def test_bake_images_adds_a_picture_to_each_resource(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "CACHE", tmp_path)
    monkeypatch.setattr(cb, "FAKE", False)
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"setting": "2026-closure", "resources": [{"id": "urea", "name": "Urea", "facts": ["a"]}], "countries": []}))
    out = tmp_path / "ai-panels.json"
    calls = []

    def interact(model, text, key, response_format=None):
        calls.append((model, response_format))
        return {**(INTERACTION_IMAGE if model == cb.IMAGE_MODEL else INTERACTION_TEXT), "model": model}
    monkeypatch.setattr(cb, "interact", interact)
    assert cb.bake("k", facts, out, workers=1, images=True) == 0
    b = json.loads(out.read_text())["resources"]["urea"]
    assert b["image"].startswith("data:image/png;base64,") and b["image_model"] == cb.IMAGE_MODEL and b["text"]
    assert calls[-1] == (cb.IMAGE_MODEL, cb.PICTURE)
    calls.clear()   # a rerun keeps text and picture without asking
    assert cb.bake("k", facts, out, workers=1, images=True) == 0 and calls == []
    assert json.loads(out.read_text())["resources"]["urea"]["image"] == b["image"]


def test_bake_images_stops_when_the_key_has_no_image_quota(tmp_path, monkeypatch, capsys):
    import io, urllib.error
    monkeypatch.setattr(cb, "CACHE", tmp_path)
    monkeypatch.setattr(cb, "FAKE", False)
    monkeypatch.setattr("time.sleep", lambda s: pytest.fail("a limit of 0 is not waited out"))
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"setting": "2026-closure", "countries": [],
                                 "resources": [{"id": i, "name": i.title(), "facts": ["a"]} for i in ("urea", "steel", "naphtha")]}))
    out = tmp_path / "ai-panels.json"
    pics = []

    def interact(model, text, key, response_format=None):
        if model == cb.IMAGE_MODEL:
            pics.append(text)
            raise urllib.error.HTTPError("https://example.invalid", 429, "Too Many Requests", {},
                                         io.BytesIO(b'{"error": {"message": "Rate limit exceeded (limit: 0 requests per day on Free Tier)"}}'))
        return INTERACTION_TEXT
    monkeypatch.setattr(cb, "interact", interact)
    assert cb.bake("k", facts, out, workers=1, images=True) == 0   # pictures are extra: the text panels are all there
    d = json.loads(out.read_text())
    assert len(pics) == 1 and all("image" not in b for b in d["resources"].values())
    assert "pictures need a key with billing" in capsys.readouterr().err


def test_interact_sends_a_response_format_only_when_asked(monkeypatch):
    sent = []

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"{}"
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: sent.append(json.loads(req.data)) or Resp())
    cb.interact("m", "hi", "k")
    cb.interact("m", "draw", "k", cb.PICTURE)
    assert "response_format" not in sent[0] and sent[1]["response_format"]["type"] == "image"
