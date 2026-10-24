# /// script
# requires-python = ">=3.11"
# ///
"""Country shapes for the materials globe (ui/globe/data/countries.js).

Natural Earth 1:110m admin-0 countries (public domain), keyed by ISO 3166-1 alpha-3, with a label
point per country for drawing supply arcs. Small producers missing at this scale (Singapore,
Bahrain, Hong Kong...) get a point only, so arcs can still start or end there.

    uv run experiments/globe_geo.py   # downloads Natural Earth into data/raw/ if missing
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "ne_110m_admin_0_countries.geojson"
OUT = ROOT / "ui" / "globe" / "data" / "countries.js"
URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"

# Countries too small for 1:110m polygons: (name, lat, lng).
POINTS = {
    "SGP": ("Singapore", 1.35, 103.82), "BHR": ("Bahrain", 26.07, 50.55), "HKG": ("Hong Kong", 22.32, 114.17),
    "MLT": ("Malta", 35.94, 14.38), "MUS": ("Mauritius", -20.3, 57.58), "TTO": ("Trinidad and Tobago", 10.69, -61.22),
    "BRN": ("Brunei", 4.54, 114.73),
}


def rounded(coords, nd=2):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], nd), round(coords[1], nd)]
    return [rounded(c, nd) for c in coords]


def main() -> None:
    if not RAW.exists():
        RAW.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(URL, RAW)
    src = json.loads(RAW.read_text())
    feats = []
    for f in src["features"]:
        p = f["properties"]
        iso = p["ISO_A3"] if p["ISO_A3"] != "-99" else p["ADM0_A3"]
        feats.append({"type": "Feature", "properties": {"iso3": iso, "name": p["NAME"], "lat": round(p["LABEL_Y"], 2),
                                                        "lng": round(p["LABEL_X"], 2)},
                      "geometry": {"type": f["geometry"]["type"], "coordinates": rounded(f["geometry"]["coordinates"])}})
    have = {f["properties"]["iso3"] for f in feats}
    points = {k: {"name": n, "lat": la, "lng": lo} for k, (n, la, lo) in POINTS.items() if k not in have}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("window.COUNTRIES = " + json.dumps(
        {"source": "Natural Earth 1:110m admin-0 countries (public domain)", "features": feats, "points": points},
        separators=(",", ":")) + ";\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(feats)} shapes, {len(points)} points, {OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
