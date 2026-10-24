# /// script
# requires-python = ">=3.11"
# ///
"""Supplier-list reader for the industry view: a small local service that asks Gemini to turn a company's
supplier list or bill of materials (PDF, image, CSV or text) into rows of product and supplier country.

The page (ui/industry/index.html?suppliers=1) posts the file. This service sends it to Gemini with a fixed
instruction and a JSON schema, checks the rows it gets back, and returns them. Gemini only reads the
document: every price move, share and exposure the page then shows comes from our own sourced tables,
never from Gemini. No Google Search tool is used, so it works on the plain free-tier quota.

    $env:GEMINI_API_KEY = "..."; uv run ui/industry/extract_server.py      # serves http://127.0.0.1:8789

The key is read from the environment only: never put it in git, Linear or the page. The service binds to
127.0.0.1 and answers only pages opened from disk or from localhost (add more with EXTRACT_ORIGINS for a
deployment), so other websites cannot spend the key. Answers are cached by file hash in
data/raw/extract/ (git-ignored), so the same file costs one request.
"""

from __future__ import annotations

import base64
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

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "raw" / "extract"
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.7-flash")
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
PORT = int(os.environ.get("EXTRACT_PORT", "8789"))
MAX_BYTES = 8_000_000
MAX_ROWS = 60
# what Gemini may send, and the text formats the page reads itself
FILE_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp"}
TEXT_TYPES = {"text/csv", "text/plain", "text/tab-separated-values"}
# the products our tables cover; anything else is "other" and only gets the supplier country's exposure
MATERIALS = {
    "steel": "steel of any form: coil, sheet, rebar, beams, pipe, iron ore, coking coal for steel",
    "jet_fuel": "jet fuel, aviation kerosene, Jet A-1, ATF",
    "aluminium": "aluminium (aluminum): ingot, sheet, foil, cans, extrusions, alumina, bauxite",
    "fertiliser": "nitrogen fertiliser: urea, ammonia, ammonium nitrate, UAN, DAP",
    "polyethylene": "plastics: polyethylene, PE or PP resin, film, plastic packaging, bottles",
    "crude_oil": "crude oil, diesel, petrol, fuel oil, LPG, naphtha",
    "other": "anything else",
}

INSTRUCTION = (
    "This file is a company's supplier list, purchase list or bill of materials. List every item it buys.\n"
    "For each item give: the item as written (short), the material it is from this list, the supplier's "
    "country as an ISO 3166-1 alpha-3 code (the country the goods ship from; empty if the file does not say), "
    "the supplier company if named, and the quantity with its unit if given.\n"
    "Materials:\n" + "\n".join(f"- {k}: {v}" for k, v in MATERIALS.items()) + "\n"
    "Rules: copy only what the file says; do not guess a country or a quantity that is not there. "
    f"At most {MAX_ROWS} items. If the file is not a list of purchases, return no items."
)

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "item": {"type": "STRING"},
                    "material": {"type": "STRING", "enum": list(MATERIALS)},
                    "country_iso3": {"type": "STRING"},
                    "supplier": {"type": "STRING"},
                    "quantity": {"type": "STRING"},
                },
                "required": ["item", "material", "country_iso3"],
            },
        },
    },
    "required": ["items"],
}


def request_body(mime: str, data: bytes) -> dict:
    """The file goes in as inline data (PDF, image) or as text (CSV, plain text)."""
    if mime in TEXT_TYPES:
        part = {"text": "File contents:\n" + data.decode("utf-8", errors="replace")[:200_000]}
    elif mime in FILE_TYPES:
        part = {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}}
    else:
        raise ValueError(f"file type {mime or 'unknown'} is not supported: use PDF, PNG, JPG, WEBP, CSV or TXT")
    return {"contents": [{"role": "user", "parts": [{"text": INSTRUCTION}, part]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 4000,
                                 "responseMimeType": "application/json", "responseSchema": SCHEMA}}


def clean_rows(rows: list) -> list[dict]:
    """Keep only well-formed rows; an unknown material becomes 'other', a bad country code becomes ''."""
    out = []
    for r in rows[:MAX_ROWS]:
        if not isinstance(r, dict):
            continue
        item = str(r.get("item", "")).strip()[:120]
        if not item:
            continue
        mat = str(r.get("material", "other")).strip()
        iso = str(r.get("country_iso3", "")).strip().upper()
        out.append({"item": item, "material": mat if mat in MATERIALS else "other",
                    "country_iso3": iso if len(iso) == 3 and iso.isalpha() else "",
                    "supplier": str(r.get("supplier", "") or "").strip()[:120],
                    "quantity": str(r.get("quantity", "") or "").strip()[:60]})
    return out


def parse(resp: dict) -> list[dict]:
    """Rows from a generateContent response that was asked for JSON."""
    cands = resp.get("candidates") or []
    if not cands:
        reason = (resp.get("promptFeedback") or {}).get("blockReason", "no answer")
        raise ValueError(f"Gemini returned no candidates ({reason})")
    c = cands[0]
    text = "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts", [])).strip()
    if not text:
        raise ValueError(f"Gemini returned an empty answer ({c.get('finishReason', 'unknown')})")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Gemini's answer was not valid JSON ({c.get('finishReason', 'unknown')})") from e
    return clean_rows(obj.get("items") or [] if isinstance(obj, dict) else [])


def allowed_origin(origin: str | None) -> bool:
    """Pages opened from disk send Origin 'null'; local dev servers send http://localhost:<port>.
    A deployment lists its own origins in EXTRACT_ORIGINS (comma-separated)."""
    if origin in (None, "null"):
        return True
    if origin in [o.strip() for o in os.environ.get("EXTRACT_ORIGINS", "").split(",") if o.strip()]:
        return True
    return urlparse(origin).hostname in ("localhost", "127.0.0.1")


def ask_gemini(body: dict, key: str) -> dict:
    req = urllib.request.Request(API.format(model=MODEL), data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())


def extract(payload: dict, key: str | None) -> dict:
    mime = str(payload.get("mime", "")).lower().split(";")[0].strip()
    name = str(payload.get("name", "file"))[:120]
    try:
        data = base64.b64decode(str(payload.get("data", "")), validate=True)
    except ValueError as e:
        raise ValueError("the file was not sent as base64") from e
    if not data:
        raise ValueError("the file is empty")
    if len(data) > MAX_BYTES:
        raise ValueError(f"the file is over {MAX_BYTES // 1_000_000} MB")
    body = request_body(mime, data)      # rejects unsupported types before any request
    path = CACHE / f"{hashlib.sha256(json.dumps([MODEL, mime]).encode() + data).hexdigest()[:16]}.json"
    if path.exists():
        return {**json.loads(path.read_text(encoding="utf-8")), "cached": True}
    if not key:
        raise PermissionError("GEMINI_API_KEY is not set on the machine running extract_server.py")
    out = {"rows": parse(ask_gemini(body, key)), "model": MODEL, "file": name,
           "generated_at": datetime.now(UTC).isoformat(timespec="seconds")}
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
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
        if urlparse(self.path).path != "/extract":
            return self._send(404, {"error": "not found"})
        if not allowed_origin(self.headers.get("Origin")):
            return self._send(403, {"error": "origin not allowed"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > MAX_BYTES * 4 // 3 + 10_000:
                return self._send(413, {"error": f"the file is over {MAX_BYTES // 1_000_000} MB"})
            self._send(200, extract(json.loads(self.rfile.read(n) or b"{}"), os.environ.get("GEMINI_API_KEY")))
        except PermissionError as e:
            self._send(503, {"error": str(e)})
        except urllib.error.HTTPError as e:
            msg = {429: "Gemini quota used up (HTTP 429): try later or another GEMINI_MODEL",
                   404: f"model {MODEL} not found (HTTP 404): set GEMINI_MODEL"}.get(e.code, f"Gemini HTTP {e.code}")
            self._send(502, {"error": msg})  # the body can echo the file; keep it out
        except (ValueError, urllib.error.URLError, TimeoutError) as e:
            self._send(400 if isinstance(e, ValueError) else 502, {"error": str(e)})

    def log_message(self, fmt: str, *args) -> None:  # one line per request, never headers (the key)
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


class Server(ThreadingHTTPServer):
    # Windows lets a second server share a port that is already taken, and requests may then go to the old one
    # (say, one started without the key). Refuse to start instead.
    allow_reuse_address = False


def main() -> None:
    if not os.environ.get("GEMINI_API_KEY"):
        print("note: GEMINI_API_KEY is not set, so only files read before can be served", file=sys.stderr)
    try:
        server = Server(("127.0.0.1", PORT), Handler)
    except OSError:
        sys.exit(f"port {PORT} is already in use: stop the other extract_server.py, or set EXTRACT_PORT")
    print(f"supplier lists on http://127.0.0.1:{PORT}/extract (model {MODEL}); open ui/industry/index.html?suppliers=1")
    server.serve_forever()


if __name__ == "__main__":
    main()
