# /// script
# requires-python = ">=3.11"
# ///
"""Country flags for the materials globe (ui/globe/data/flags.js), so the page shows a flag next to
each country name instead of a letter code, and still works offline.

Flags are from flag-icons 7.6.0 (MIT, Panayiotis Lipiridis; licence in ui/globe/vendor/). Every country
in the globe's data gets its flag. Other countries get one too unless the drawing is heavy (coats of
arms run to 50-180 KB); those fall back to the letter code.

    uv run experiments/globe_flags.py   # downloads the npm tarball into data/raw/ if missing
"""

from __future__ import annotations

import json
import re
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "7.6.0"
TARBALL = ROOT / "data" / "raw" / f"flag-icons-{VERSION}.tgz"
URL = f"https://registry.npmjs.org/flag-icons/-/flag-icons-{VERSION}.tgz"
NE = ROOT / "data" / "raw" / "ne_110m_admin_0_countries.geojson"
MATERIALS = ROOT / "ui" / "globe" / "data" / "materials.js"
OUT = ROOT / "ui" / "globe" / "data" / "flags.js"
LICENSE = ROOT / "ui" / "globe" / "vendor" / "flag-icons.LICENSE"
MAX_BYTES = 9000  # countries outside the data keep their flag only if it is this small or smaller

# Small countries drawn as points on the globe, and Natural Earth codes that are not ISO alpha-2.
EXTRA = {"SGP": "sg", "BHR": "bh", "HKG": "hk", "MLT": "mt", "MUS": "mu", "TTO": "tt", "BRN": "bn", "TWN": "tw"}


def iso2_by_iso3() -> dict[str, str]:
    out = dict(EXTRA)
    for f in json.loads(NE.read_text())["features"]:
        p = f["properties"]
        iso3 = p["ISO_A3"] if p["ISO_A3"] != "-99" else p["ADM0_A3"]
        a2 = p.get("ISO_A2") if p.get("ISO_A2") not in (None, "-99") else p.get("ISO_A2_EH")
        if a2 and a2 != "-99" and iso3 not in out:
            out[iso3] = a2.lower()
    return out


def minify(svg: str) -> str:
    svg = re.sub(r"<\?xml.*?\?>|<!--.*?-->", "", svg, flags=re.DOTALL)
    return re.sub(r"\s+", " ", re.sub(r">\s+<", "><", svg)).strip()


def main() -> None:
    if not TARBALL.exists():
        TARBALL.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(URL, TARBALL)
    used = set(re.findall(r'"(?:iso3|to|from)":"([A-Z]{3})"', MATERIALS.read_text()))
    codes = iso2_by_iso3()
    flags, skipped = {}, []
    with tarfile.open(TARBALL) as tar:  # read members in memory; nothing is extracted to disk
        files = {m.name: m for m in tar.getmembers() if m.isfile()}
        LICENSE.write_bytes(tar.extractfile(files["package/LICENSE"]).read())
        for iso3, a2 in sorted(codes.items()):
            m = files.get(f"package/flags/4x3/{a2}.svg")
            if not m:
                continue
            svg = minify(tar.extractfile(m).read().decode())
            if iso3 not in used and len(svg) > MAX_BYTES:
                skipped.append(iso3)
                continue
            flags[iso3] = "data:image/svg+xml," + urllib.parse.quote(svg, safe=" =:/;,'().-")
    OUT.write_text("window.FLAGS = " + json.dumps({"source": f"flag-icons {VERSION} (MIT)", "flags": flags},
                                                  separators=(",", ":")) + ";\n")
    missing = sorted(used - set(flags))
    print(f"wrote {OUT.relative_to(ROOT)}: {len(flags)} flags, {OUT.stat().st_size // 1024} KB; "
          f"heavy flags left out: {len(skipped)}; data countries without a flag: {missing or 'none'}")


if __name__ == "__main__":
    main()
