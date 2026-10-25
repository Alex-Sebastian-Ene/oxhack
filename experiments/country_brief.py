# /// script
# requires-python = ">=3.11"
# ///
"""AI country briefs for the materials globe: a small local service that asks Gemini, with Google Search
grounding, for a short brief on one country's role in one material.

The globe page (ui/globe/index.html?brief=1) posts the country, the material and our own sourced rows
for that country. This service adds the instructions, calls Gemini, and returns the text with the web
pages Gemini cited. Every answer is labelled as AI-written on the page; it is never mixed into the
sourced tables. Design and limits: docs/country-briefs.md.

    uv run experiments/country_brief.py      # serves http://127.0.0.1:8787

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
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
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
        if urlparse(self.path).path != "/brief":
            return self._send(404, {"error": "not found"})
        if not allowed_origin(self.headers.get("Origin")):
            return self._send(403, {"error": "origin not allowed"})
        try:
            n = min(int(self.headers.get("Content-Length", "0")), 64_000)
            payload = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, brief(payload, os.environ.get("GEMINI_API_KEY"), "refresh" in self.path))
        except PermissionError as e:
            self._send(503, {"error": str(e)})
        except urllib.error.HTTPError as e:
            self._send(502, {"error": f"Gemini HTTP {e.code}"})  # the body can echo the request; keep it out
        except (ValueError, urllib.error.URLError, TimeoutError) as e:
            self._send(502, {"error": str(e)})

    def log_message(self, fmt: str, *args) -> None:  # one line per request, never headers (the key)
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


def main() -> None:
    if not os.environ.get("GEMINI_API_KEY"):
        print("note: GEMINI_API_KEY is not set, so only cached briefs can be served", file=sys.stderr)
    print(f"country briefs on http://127.0.0.1:{PORT}/brief (model {MODEL}); open ui/globe/index.html?brief=1")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
