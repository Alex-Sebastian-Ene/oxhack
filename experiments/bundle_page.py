# /// script
# requires-python = ">=3.11"
# ///
"""Inline a ui/ page (HTML, its stylesheet and local scripts) into one shareable file.

    uv run experiments/bundle_page.py ui/globe out.html             # full HTML document
    uv run experiments/bundle_page.py ui/globe out.html --fragment  # no <html>/<head>/<body>, for
                                                                    # hosts that add their own
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def bundle(page: Path, fragment: bool) -> str:
    html = (page / "index.html").read_text()
    for href in re.findall(r'<link rel="stylesheet" href="([^"]+)">', html):
        html = html.replace(f'<link rel="stylesheet" href="{href}">', f"<style>\n{(page / href).read_text()}</style>")
    for src in re.findall(r'<script src="([^":]+)"></script>', html):
        js = (page / src).read_text().replace("</script", "<\\/script")
        html = html.replace(f'<script src="{src}"></script>', f"<script>\n{js}</script>")
    if fragment:
        html = re.sub(r"<!doctype html>\s*|</?html[^>]*>\s*|</?head>\s*|</?body>\s*", "", html)
        html = re.sub(r'<meta charset="utf-8">\s*|<meta name="viewport"[^>]*>\s*', "", html)
    return html


if __name__ == "__main__":
    page, out = ROOT / sys.argv[1], Path(sys.argv[2])
    out.write_text(bundle(page, "--fragment" in sys.argv))
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
