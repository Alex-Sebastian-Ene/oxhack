# /// script
# requires-python = ">=3.11"
# ///
"""Inline ui/strait (HTML, CSS, data, script) into one file you can share or publish as a page.

    uv run experiments/strait_bundle.py out.html             # a full HTML document
    uv run experiments/strait_bundle.py out.html --fragment  # without <html>/<head>/<body>, for hosts
                                                             # that add their own skeleton
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "ui" / "strait"


def bundle(fragment: bool) -> str:
    html = (UI / "index.html").read_text()
    css = (UI / "style.css").read_text()
    html = html.replace('<link rel="stylesheet" href="style.css">', f"<style>\n{css}</style>")
    for src in ("data/scenarios.js", "app.js"):
        js = (UI / src).read_text().replace("</script", "<\\/script")
        html = html.replace(f'<script src="{src}"></script>', f"<script>\n{js}</script>")
    if fragment:
        html = re.sub(r"<!doctype html>\s*|</?html[^>]*>\s*|</?head>\s*|</?body>\s*", "", html)
        html = re.sub(r'<meta charset="utf-8">\s*|<meta name="viewport"[^>]*>\s*', "", html)
    return html


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.write_text(bundle("--fragment" in sys.argv))
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
