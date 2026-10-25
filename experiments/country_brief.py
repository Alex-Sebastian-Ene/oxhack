# /// script
# requires-python = ">=3.11"
# ///
"""AI panels for the materials globe and the Hormuz Flow app: a small local service that asks Gemini for
  /brief     a short brief on one country's role in one material (Google Search grounding);
  /resource  what a resource is (steel, naphtha, urea...): a short description plus a pixel-art picture;
  /country   a profile of a country written only from the project's own numbers, citing them.

The pages (ui/globe/index.html?brief=1, ui/app/index.html) post the subject and our own sourced rows for it.
This service adds the instructions, calls Gemini, and returns the text (and picture) with what it cited.
Every answer is labelled as AI-written on the page; it is never mixed into the sourced tables. Design and
limits: docs/country-briefs.md. BRIEF_FAKE=1 serves labelled test answers with no key, for UI work.

    uv run experiments/country_brief.py      # serves http://127.0.0.1:8787
    uv run experiments/country_brief.py check  # one tiny live call per model, and the models this key can use

The key comes from the GEMINI_API_KEY environment variable, or from a line GEMINI_API_KEY=... in the
repo's .env (git-ignored). Never put it in git, Linear or the page. The service binds to
127.0.0.1 and answers only pages opened from disk or from localhost, so other websites cannot spend the
key. Answers are cached in data/raw/briefs/ (git-ignored) and shown as "cached" with their date.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path) -> None:
    """KEY=value lines from a git-ignored .env, for keys the environment does not already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        key = key.removeprefix("export ").strip()
        if sep and key and not key.startswith("#") and key not in os.environ:
            os.environ[key] = value.strip().strip("'\"")


load_env(ROOT / ".env")
CACHE = ROOT / "data" / "raw" / "briefs"
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")  # gemini-2.5-* is deprecated (gemini-api-dev skill)
IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-nano-banana-2.1")  # the skill's default image model
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
INTERACTIONS = "https://generativelanguage.googleapis.com/v1beta/interactions"
FAKE = os.environ.get("BRIEF_FAKE") == "1"
PORT = int(os.environ.get("BRIEF_PORT", "8787"))
MAX_FACTS = 40


def prompt(country: str, material: str, facts: list[str]) -> str:
    lines = "\n".join(f"- {f}" for f in facts[:MAX_FACTS]) or "- (none)"
    return (
        f"Write a brief on {country}'s role in the world supply of {material} and its ingredients, for a "
        "hackathon judge looking at a globe of oil-exposed materials.\n"
        "Cover: what it makes, imports and exports; how dependent it is on the Strait of Hormuz and on oil "
        "prices; anything that changed in 2026.\n"
        "Rules: 4 to 6 bullet points, under 140 words in all. Start each bullet with '- '. Give a year with "
        "every number. Prefer the sourced facts below and mark them [data]. Anything else must come from "
        "Google Search results; do not state numbers you cannot source. Say 'unclear' rather than guess.\n"
        f"Sourced facts from our tables:\n{lines}"
    )


def request_body(country: str, material: str, facts: list[str]) -> dict:
    return {"contents": [{"role": "user", "parts": [{"text": prompt(country, material, facts)}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"maxOutputTokens": 600}}


def parse(resp: dict) -> dict:
    """Text and cited web pages from a generateContent response."""
    cands = resp.get("candidates") or []
    if not cands:
        reason = (resp.get("promptFeedback") or {}).get("blockReason", "no answer")
        raise ValueError(f"Gemini returned no candidates ({reason})")
    c = cands[0]
    text = "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts", [])).strip()
    sources, seen = [], set()
    for ch in (c.get("groundingMetadata") or {}).get("groundingChunks", []):
        web = ch.get("web") or {}
        if web.get("uri") and web["uri"] not in seen:
            seen.add(web["uri"])
            sources.append({"title": web.get("title") or "", "uri": web["uri"]})
    if not text:
        raise ValueError(f"Gemini returned an empty answer ({c.get('finishReason', 'unknown')})")
    return {"text": text, "sources": sources}


# ---------------------------------------------------------------- /resource and /country (Interactions API)
STYLE = ("16-bit pixel-art illustration with crisp square pixels and a limited palette: night navy, steel blue, "
         "sodium-lamp amber and a little flame red. A refinery or harbour at night. No text, letters, labels or logos.")


def resource_prompt(name: str, facts: list[str]) -> str:
    lines = "\n".join(f"[{i + 1}] {f}" for i, f in enumerate(facts[:MAX_FACTS])) or "(none)"
    return (
        f"Explain what {name} is to a hackathon judge looking at a globe of oil-exposed materials.\n"
        "Cover, in 3 or 4 short bullet points (under 110 words in all): what it is and how it is made; what it is "
        "used for; why the price of oil or the Strait of Hormuz matters to it. Start each bullet with '- '.\n"
        "Use general knowledge for what it is and how it is made. Use only the facts below for any number, and put "
        "the fact's number in square brackets after it, like [2]. Do not state any other numbers.\n"
        f"Facts from our tables:\n{lines}"
    )


def image_prompt(name: str) -> str:
    return f"{STYLE} Subject: {name}, shown as the thing itself (a sample, a product or a cargo) at an industrial site."


def country_prompt(country: str, facts: list[str]) -> str:
    lines = "\n".join(f"[{i + 1}] {f}" for i, f in enumerate(facts[:MAX_FACTS])) or "(none)"
    return (
        f"Write a profile of {country} for a hackathon judge, using only the numbered facts below from our project.\n"
        "Cover, in 4 or 5 short bullet points (under 130 words in all): its main export and its biggest role in world "
        "production or trade; how it ranks in oil, steel and the other materials listed; where its key inputs come "
        "from; how exposed it is to the Hormuz shock. Start each bullet with '- '. After every number, cite the fact "
        "it comes from in square brackets, like [3]. Do not add numbers, rankings or claims that are not in the facts; "
        "if something is not covered, leave it out.\n"
        f"Facts:\n{lines}"
    )


def interact(model: str, text: str, key: str) -> dict:
    req = urllib.request.Request(INTERACTIONS, data=json.dumps({"model": model, "input": text}).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def outputs(resp: dict) -> tuple[str, dict | None]:
    """Text and the last image from an Interactions response (its model_output steps); a generateContent-shaped
    response is read too, in case the endpoint answers in that form."""
    parts = []
    for st in resp.get("steps") or []:
        if st.get("type") == "model_output":
            parts += st.get("content") or []
    parts += resp.get("outputs") or []
    for c in resp.get("candidates") or []:
        for p in (c.get("content") or {}).get("parts", []):
            if "text" in p:
                parts.append({"type": "text", "text": p["text"]})
            if "inlineData" in p:
                parts.append({"type": "image", "data": p["inlineData"].get("data"), "mime_type": p["inlineData"].get("mimeType")})
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
    imgs = [p for p in parts if p.get("type") == "image" and p.get("data")]
    return text, (imgs[-1] if imgs else None)


def png(w: int, h: int, pixel) -> bytes:
    """A small RGB PNG from pixel(x, y) -> (r, g, b), standard library only."""
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(c for x in range(w) for c in pixel(x, y)) for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def fake_image() -> dict:
    """Test card for BRIEF_FAKE: navy with amber hazard stripes, so it can't be mistaken for a real picture."""
    import base64
    def px(x, y):
        return (255, 164, 36) if (x + y) // 4 % 2 == 0 and 8 <= y <= 15 else (11, 34, 64) if y < 8 else (18, 26, 45)
    return {"data": base64.b64encode(png(48, 24, px)).decode(), "mime_type": "image/png"}


def _subject(payload: dict, key: str) -> tuple[str, list[str]]:
    name = str(payload.get(key, ""))[:80].strip()
    facts = [str(f)[:400] for f in (payload.get("facts") or [])][:MAX_FACTS]
    if not name:
        raise ValueError(f"need {key}")
    return name, facts


def resource(payload: dict, key: str | None, refresh: bool = False) -> dict:
    name, facts = _subject(payload, "name")
    rid = "".join(ch for ch in str(payload.get("id", name)).lower() if ch.isalnum() or ch == "_")[:40] or "item"
    h = hashlib.sha256(json.dumps([MODEL, IMAGE_MODEL, name, facts, FAKE], sort_keys=True).encode()).hexdigest()[:12]
    path = CACHE / f"res-{rid}-{h}.json"
    if path.exists() and not refresh:
        return {**json.loads(path.read_text()), "cached": True}
    if FAKE:
        text, img = f"- TEST ANSWER, not from Gemini: {name} would be described here [1].\n- Set GEMINI_API_KEY and unset BRIEF_FAKE for real answers.", fake_image()
        model, image_model = "test (BRIEF_FAKE)", "test (BRIEF_FAKE)"
    else:
        if not key:
            raise PermissionError("GEMINI_API_KEY is not set (environment or the repo's .env) on the machine running country_brief.py")
        text, _ = outputs(interact(MODEL, resource_prompt(name, facts), key))
        _, img = outputs(interact(IMAGE_MODEL, image_prompt(name), key))
        model, image_model = MODEL, IMAGE_MODEL
        if not text:
            raise ValueError("Gemini returned no description")
    out = {"id": rid, "name": name, "text": text, "facts": facts, "model": model, "image_model": image_model if img else None,
           "image": f"data:{img.get('mime_type') or 'image/png'};base64,{img['data']}" if img else None,
           "generated_at": datetime.now(UTC).isoformat(timespec="seconds")}
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    return {**out, "cached": False}


def country(payload: dict, key: str | None, refresh: bool = False) -> dict:
    name, facts = _subject(payload, "country")
    iso3 = "".join(ch for ch in str(payload.get("iso3", "")).upper() if ch.isalpha())[:3] or "XXX"
    h = hashlib.sha256(json.dumps([MODEL, name, facts, FAKE], sort_keys=True).encode()).hexdigest()[:12]
    path = CACHE / f"cty-{iso3}-{h}.json"
    if path.exists() and not refresh:
        return {**json.loads(path.read_text()), "cached": True}
    if FAKE:
        text, model = f"- TEST ANSWER, not from Gemini: a profile of {name} would be written here from the {len(facts)} facts [1].", "test (BRIEF_FAKE)"
    else:
        if not key:
            raise PermissionError("GEMINI_API_KEY is not set (environment or the repo's .env) on the machine running country_brief.py")
        text, _ = outputs(interact(MODEL, country_prompt(name, facts), key))
        model = MODEL
        if not text:
            raise ValueError("Gemini returned no profile")
    out = {"iso3": iso3, "country": name, "text": text, "facts": facts, "model": model,
           "generated_at": datetime.now(UTC).isoformat(timespec="seconds")}
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    return {**out, "cached": False}


ROUTES = {"/brief": lambda p, k, r: brief(p, k, r), "/resource": lambda p, k, r: resource(p, k, r), "/country": lambda p, k, r: country(p, k, r)}


def allowed_origin(origin: str | None) -> bool:
    """Pages opened from disk send Origin 'null'; local dev servers send http://localhost:<port>."""
    if origin in (None, "null"):
        return True
    host = urlparse(origin).hostname
    return host in ("localhost", "127.0.0.1")


def cache_key(iso3: str, material: str, facts: list[str]) -> str:
    h = hashlib.sha256(json.dumps([MODEL, material, facts], sort_keys=True).encode()).hexdigest()[:12]
    return f"{iso3}-{h}"


def ask_gemini(body: dict, key: str) -> dict:
    req = urllib.request.Request(API.format(model=MODEL), data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def brief(payload: dict, key: str | None, refresh: bool = False) -> dict:
    iso3 = str(payload.get("iso3", ""))[:3].upper()
    country, material = str(payload.get("country", iso3))[:80], str(payload.get("material", ""))[:80]
    facts = [str(f)[:400] for f in (payload.get("facts") or [])][:MAX_FACTS]
    if not iso3.isalpha() or not material:
        raise ValueError("need iso3 and material")
    path = CACHE / f"{cache_key(iso3, material, facts)}.json"
    if path.exists() and not refresh:
        return {**json.loads(path.read_text()), "cached": True}
    if not key:
        raise PermissionError("GEMINI_API_KEY is not set (environment or the repo's .env) on the machine running country_brief.py")
    out = {**parse(ask_gemini(request_body(country, material, facts), key)), "model": MODEL,
           "generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "iso3": iso3, "material": material}
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    return {**out, "cached": False}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        data = json.dumps(obj).encode()
        self.send_response(code)
        origin = self.headers.get("Origin")
        if allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin or "null")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        self._send(204 if allowed_origin(self.headers.get("Origin")) else 403, {})

    def do_POST(self) -> None:
        route = ROUTES.get(urlparse(self.path).path)
        if not route:
            return self._send(404, {"error": "not found"})
        if not allowed_origin(self.headers.get("Origin")):
            return self._send(403, {"error": "origin not allowed"})
        try:
            n = min(int(self.headers.get("Content-Length", "0")), 64_000)
            payload = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, route(payload, os.environ.get("GEMINI_API_KEY"), "refresh" in self.path))
        except PermissionError as e:
            self._send(503, {"error": str(e)})
        except urllib.error.HTTPError as e:
            self._send(502, {"error": f"Gemini HTTP {e.code}"})  # the body can echo the request; keep it out
        except (ValueError, urllib.error.URLError, TimeoutError) as e:
            self._send(502, {"error": str(e)})

    def log_message(self, fmt: str, *args) -> None:  # one line per request, never headers (the key)
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


def _http_error(e: Exception) -> str:
    """Google's error message for a failed call (its JSON body), never the request or its headers."""
    if isinstance(e, urllib.error.HTTPError):
        try:
            body = json.loads(e.read())
            body = (body[0] if body else {}) if isinstance(body, list) else body   # Interactions errors come as a list
            return f"HTTP {e.code}: {str((body.get('error') or {}).get('message', ''))[:200]}"
        except (ValueError, OSError, AttributeError):
            return f"HTTP {e.code}"
    return str(e)[:200]


def check(key: str | None) -> int:
    """A live smoke test before a demo: list the models this key can use, then one tiny text call and one
    picture through the Interactions API, and one generateContent call (ui/industry/explain_server.py uses
    it). Prints what worked and what to change; never prints the key. Returns the number of failures."""
    if not key:
        print("no GEMINI_API_KEY (environment or the repo's .env): nothing to check")
        return 1
    fails = 0
    try:
        req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", headers={"x-goog-api-key": key})
        with urllib.request.urlopen(req, timeout=30) as r:
            names = [m["name"].removeprefix("models/") for m in json.loads(r.read()).get("models", [])]
        print(f"key works: {len(names)} models; gemini ones: {', '.join(n for n in names if n.startswith('gemini'))[:900]}")
        for want in (MODEL, IMAGE_MODEL):
            print(f"  {want}: {'listed' if want in names else 'NOT LISTED, set GEMINI_MODEL / GEMINI_IMAGE_MODEL to one above'}")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"model list failed: {_http_error(e)}"); fails += 1
    try:
        text, _ = outputs(interact(MODEL, "Reply with the single word: ready", key))
        print(f"text ({MODEL}, Interactions): {'ok, said ' + repr(text[:40]) if text else 'answered, but no text found in the response'}")
        fails += 0 if text else 1
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"text ({MODEL}, Interactions) failed: {_http_error(e)}"); fails += 1
    try:
        _, img = outputs(interact(IMAGE_MODEL, image_prompt("crude oil"), key))
        print(f"picture ({IMAGE_MODEL}, Interactions): {'ok, ' + str(len(img['data']) * 3 // 4 // 1024) + ' KB ' + str(img.get('mime_type')) if img else 'answered, but no image found in the response'}")
        fails += 0 if img else 1
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"picture ({IMAGE_MODEL}, Interactions) failed: {_http_error(e)}"); fails += 1
    try:
        resp = ask_gemini({"contents": [{"parts": [{"text": "Reply with the single word: ready"}]}]}, key)
        text, _ = outputs(resp)
        print(f"text ({MODEL}, generateContent): {'ok, said ' + repr(text[:40]) if text else 'answered, but no text found'}")
        fails += 0 if text else 1
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"text ({MODEL}, generateContent) failed: {_http_error(e)}"); fails += 1
    print("all good" if not fails else f"{fails} check(s) failed")
    return fails


def main() -> None:
    if sys.argv[1:2] == ["check"]:
        sys.exit(1 if check(os.environ.get("GEMINI_API_KEY")) else 0)
    if FAKE:
        print("BRIEF_FAKE=1: serving labelled test answers, not Gemini", file=sys.stderr)
    elif not os.environ.get("GEMINI_API_KEY"):
        print("note: GEMINI_API_KEY is not set, so only cached answers can be served", file=sys.stderr)
    print(f"AI panels on http://127.0.0.1:{PORT} (/brief, /resource, /country; text {MODEL}, images {IMAGE_MODEL}); "
          "open ui/app/index.html or ui/globe/index.html?brief=1")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
