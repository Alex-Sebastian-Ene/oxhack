# /// script
# requires-python = ">=3.11"
# ///
"""Explanations for the industry view: a small local service that asks Gemini to explain, in plain words, the
numbers the page shows for one country or one product, and checks the answer against those numbers.

The page (ui/industry/index.html?explain=1) posts what it is explaining and the facts it shows, each with its
source. This service adds a fixed instruction, asks Gemini for a few bullets that each cite the facts they use,
then checks every number in every bullet against the cited facts: a number that is not in them is flagged on the
page as "not in our data". Gemini only explains; it never adds a number to the page, the colours or the tables.
No Google Search tool is used, so it runs on the plain free-tier quota.

    uv run ui/industry/explain_server.py      # serves http://127.0.0.1:8789

The key comes from the GEMINI_API_KEY environment variable, or from a line GEMINI_API_KEY=... in the
repo's .env (git-ignored). Never put it in git, Linear or the page. The service binds to 127.0.0.1 and answers
only pages opened from disk or from localhost (add more with EXPLAIN_ORIGINS for a deployment), so other
websites cannot spend the key. Answers are cached in data/raw/explain/ (git-ignored), so the same question costs
one request and a cached answer is labelled as cached.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]


def load_env(path: Path) -> None:
    """KEY=value lines from the repo's git-ignored .env, for keys the environment does not already set
    (the same rule as experiments/country_brief.py, so one .env serves both)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        key = key.removeprefix("export ").strip()
        if sep and key and not key.startswith("#") and key not in os.environ:
            os.environ[key] = value.strip().strip("'\"")


load_env(ROOT / ".env")
CACHE = ROOT / "data" / "raw" / "explain"
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")  # gemini-2.5-* is deprecated (gemini-api-dev skill)
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
PORT = int(os.environ.get("EXPLAIN_PORT", "8789"))
MAX_FACTS = 30
THINKING = os.environ.get("GEMINI_THINKING", "low")  # low, medium or high
TIMEOUT = 120
RETRY_WAIT = 8  # seconds before the one retry
KINDS = {"country": "a country's exposure to the Strait of Hormuz oil shock",
         "product": "how the Hormuz oil shock reaches one product's price and its buyers"}


def prompt(kind: str, subject: str, facts: list[str]) -> str:
    lines = "\n".join(f"[{i}] {f}" for i, f in enumerate(facts, 1)) or "(none)"
    return (
        f"Explain {KINDS[kind]}: {subject}. The reader runs a business and is looking at a dashboard of these "
        "numbers.\nIn 3 to 5 short bullets, explain why the numbers are what they are: follow the chain from oil "
        "flow through the strait, to the Brent price, to this price or cost, to who pays it. Say plainly what is "
        "uncertain: bands, simulated scenarios and missing data.\n"
        "Rules: use only the numbered facts below. Do not add any number, date or claim that is not in them. "
        "Each bullet lists the fact numbers it uses. Under 140 words in all. No headings.\n"
        f"Facts:\n{lines}"
    )


SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "bullets": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"text": {"type": "STRING"}, "facts": {"type": "ARRAY", "items": {"type": "INTEGER"}}},
                "required": ["text", "facts"],
            },
        },
    },
    "required": ["bullets"],
}


def request_body(kind: str, subject: str, facts: list[str]) -> dict:
    # Gemini 3 models think at "medium" by default, which made short answers take over a minute; restating given
    # facts needs little reasoning. Thinking tokens count against maxOutputTokens, so leave plenty of room.
    return {"contents": [{"role": "user", "parts": [{"text": prompt(kind, subject, facts)}]}],
            "generationConfig": {"maxOutputTokens": 8192, "thinkingConfig": {"thinkingLevel": THINKING},
                                 "responseMimeType": "application/json", "responseSchema": SCHEMA}}


NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers(text: str) -> set[str]:
    """The numbers in a text, normalised: no signs or thousands commas, no trailing .0."""
    out = set()
    for m in NUM.findall(text):
        n = m.replace(",", "")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n)
    return out


def check(bullets: list, facts: list[str]) -> list[dict]:
    """Keep well-formed bullets, drop fact numbers that do not exist, and flag every number in a bullet that is
    not in the facts it cites (or, if it cites none, in any fact)."""
    out = []
    for b in bullets[:6]:
        if not isinstance(b, dict) or not str(b.get("text", "")).strip():
            continue
        text = str(b["text"]).strip()[:600]
        cited = sorted({i for i in b.get("facts") or [] if isinstance(i, int) and 1 <= i <= len(facts)})
        pool = set().union(*(numbers(facts[i - 1]) for i in cited)) if cited else set().union(*(numbers(f) for f in facts), set())
        out.append({"text": text, "facts": cited, "unsupported": sorted(numbers(text) - pool)})
    return out


def parse(resp: dict, facts: list[str]) -> list[dict]:
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
    bullets = check(obj.get("bullets") or [] if isinstance(obj, dict) else [], facts)
    if not bullets:
        raise ValueError("Gemini returned no explanation")
    return bullets


def allowed_origin(origin: str | None) -> bool:
    """Pages opened from disk send Origin 'null'; local dev servers send http://localhost:<port>.
    A deployment lists its own origins in EXPLAIN_ORIGINS (comma-separated)."""
    if origin in (None, "null"):
        return True
    if origin in [o.strip() for o in os.environ.get("EXPLAIN_ORIGINS", "").split(",") if o.strip()]:
        return True
    return urlparse(origin).hostname in ("localhost", "127.0.0.1")


def ask_gemini(body: dict, key: str) -> dict:
    """One call, retried once after a pause when Gemini is busy or over its per-minute limit."""
    for attempt in (1, 2):
        req = urllib.request.Request(API.format(model=MODEL), data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            sys.stderr.write(f"Gemini answered HTTP {e.code} (attempt {attempt})
")  # the code only, never the body
            if attempt == 2 or e.code not in (429, 500, 503):
                raise
            time.sleep(RETRY_WAIT)


def explain(payload: dict, key: str | None) -> dict:
    kind = str(payload.get("kind", ""))
    if kind not in KINDS:
        raise ValueError("kind must be country or product")
    subject = str(payload.get("subject", "")).strip()[:80]
    facts = [str(f).strip()[:300] for f in (payload.get("facts") or []) if str(f).strip()][:MAX_FACTS]
    if not subject or not facts:
        raise ValueError("need a subject and at least one fact")
    path = CACHE / f"{hashlib.sha256(json.dumps([MODEL, kind, subject, facts]).encode()).hexdigest()[:16]}.json"
    if path.exists():
        return {**json.loads(path.read_text(encoding="utf-8")), "cached": True}
    if not key:
        raise PermissionError("GEMINI_API_KEY is not set (environment or the repo's .env) on the machine running explain_server.py")
    out = {"bullets": parse(ask_gemini(request_body(kind, subject, facts), key), facts), "facts": facts,
           "model": MODEL, "generated_at": datetime.now(UTC).isoformat(timespec="seconds")}
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
        if urlparse(self.path).path != "/explain":
            return self._send(404, {"error": "not found"})
        if not allowed_origin(self.headers.get("Origin")):
            return self._send(403, {"error": "origin not allowed"})
        try:
            n = min(int(self.headers.get("Content-Length", "0")), 64_000)
            self._send(200, explain(json.loads(self.rfile.read(n) or b"{}"), os.environ.get("GEMINI_API_KEY")))
        except PermissionError as e:
            self._send(503, {"error": str(e)})
        except urllib.error.HTTPError as e:
            msg = {429: "Gemini's free limit was hit (HTTP 429), even after one retry: wait a minute and try again",
                   503: "Gemini is busy (HTTP 503), even after one retry: try again shortly",
                   404: f"model {MODEL} not found (HTTP 404): set GEMINI_MODEL"}.get(e.code, f"Gemini HTTP {e.code}")
            self._send(502, {"error": msg})  # the body can echo the request; keep it out
        except TimeoutError:
            self._send(504, {"error": f"Gemini took over {TIMEOUT} s: try again, or set GEMINI_THINKING=low and a Flash model"})
        except (ValueError, urllib.error.URLError) as e:
            self._send(400 if isinstance(e, ValueError) else 502, {"error": str(e)})

    def log_message(self, fmt: str, *args) -> None:  # one line per request, never headers (the key)
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


class Server(ThreadingHTTPServer):
    # Windows lets a second server share a port that is already taken, and requests may then go to the old one
    # (say, one started without the key). Refuse to start instead.
    allow_reuse_address = False


def main() -> None:
    if not os.environ.get("GEMINI_API_KEY"):
        print("note: GEMINI_API_KEY is not set, so only cached explanations can be served", file=sys.stderr)
    try:
        server = Server(("127.0.0.1", PORT), Handler)
    except OSError:
        sys.exit(f"port {PORT} is already in use: stop the other explain_server.py, or set EXPLAIN_PORT")
    print(f"explanations on http://127.0.0.1:{PORT}/explain (model {MODEL}); open ui/industry/index.html?explain=1")
    server.serve_forever()


if __name__ == "__main__":
    main()
