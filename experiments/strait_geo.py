# /// script
# requires-python = ">=3.11"
# dependencies = ["shapely>=2.0"]
# ///
"""Build the map geometry for the Strait of Hormuz view (ui/strait/data/geo.json).

Land and islands come from Natural Earth 1:10m (public domain). The shipping lanes are hand-drawn
waypoints that follow the shape of the Hormuz traffic separation scheme (inbound/westbound traffic
on the northern lane, outbound/eastbound on the southern lane). They are approximate, for display
and for the simulator only, never for navigation. The script refuses to write the file if a lane
or the counting gate touches land.

    uv run experiments/strait_geo.py   # downloads Natural Earth into data/raw/ if missing
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from shapely.geometry import LineString, Polygon, box, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "ui" / "strait" / "data" / "geo.json"
NE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/{}.geojson"
LAYERS = ("ne_10m_land", "ne_10m_minor_islands")

BBOX = (54.6, 24.9, 57.9, 27.5)  # lon_min, lat_min, lon_max, lat_max: the starting view
CLIP = (52.5, 23.0, 60.0, 29.0)  # land is kept for a wider area so panning never shows a cut edge

# (lon, lat) waypoints, west to east. Ships keep to starboard, so westbound (into the Gulf) traffic
# uses the northern lane and eastbound (out of the Gulf) traffic the southern one.
LANES = {
    "inbound": [(54.6, 26.12), (55.0, 26.18), (55.45, 26.38), (55.85, 26.55), (56.2, 26.64),
                (56.45, 26.6), (56.65, 26.42), (56.85, 26.15), (57.1, 25.85), (57.9, 25.45)],
    "outbound": [(54.6, 26.02), (55.0, 26.08), (55.45, 26.28), (55.85, 26.46), (56.2, 26.55),
                 (56.4, 26.5), (56.58, 26.36), (56.78, 26.1), (57.02, 25.8), (57.9, 25.35)],
}
# Counting gate across the narrows, between the Musandam peninsula and Larak island.
GATE = [(56.42, 26.42), (56.42, 26.78)]

PLACES = [
    {"name": "IRAN", "lon": 56.9, "lat": 27.25, "kind": "country"},
    {"name": "OMAN (Musandam)", "lon": 56.2, "lat": 25.95, "kind": "country"},
    {"name": "UAE", "lon": 55.35, "lat": 25.2, "kind": "country"},
    {"name": "Persian Gulf", "lon": 55.05, "lat": 26.55, "kind": "sea"},
    {"name": "Gulf of Oman", "lon": 57.35, "lat": 25.3, "kind": "sea"},
    {"name": "Bandar Abbas", "lon": 56.28, "lat": 27.18, "kind": "port"},
    {"name": "Fujairah", "lon": 56.36, "lat": 25.12, "kind": "port"},
    {"name": "Khasab", "lon": 56.25, "lat": 26.18, "kind": "port"},
]


def load_land() -> Polygon:
    clip = box(*CLIP)
    parts = []
    for layer in LAYERS:
        path = RAW / f"{layer}.geojson"
        if not path.exists():
            RAW.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(NE_URL.format(layer), path)
        for feat in json.loads(path.read_text())["features"]:
            geom = shape(feat["geometry"])
            if geom.intersects(clip):
                parts.append(geom.intersection(clip))
    return unary_union(parts)


def check_clear(land, name: str, coords) -> None:
    line = LineString(coords)
    if line.intersects(land):
        hit = line.intersection(land)
        raise SystemExit(f"{name} crosses land near {hit.representative_point().coords[0]}")


def rounded(geom, nd=4):
    def r(c):
        return [round(c[0], nd), round(c[1], nd)]
    g = mapping(geom)
    if g["type"] == "Polygon":
        return {"type": "MultiPolygon", "coordinates": [[[r(c) for c in ring] for ring in g["coordinates"]]]}
    return {"type": "MultiPolygon", "coordinates": [[[r(c) for c in ring] for ring in poly] for poly in g["coordinates"]]}


def main() -> None:
    land = load_land().simplify(0.004, preserve_topology=True)
    for name, coords in LANES.items():
        check_clear(land, f"lane {name}", coords)
    check_clear(land, "gate", GATE)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    geo = {
        "bbox": BBOX,
        "clip": CLIP,
        "source": "Natural Earth 1:10m land + minor islands (public domain); lanes approximate, not for navigation",
        "land": rounded(land),
        "lanes": {k: [list(p) for p in v] for k, v in LANES.items()},
        "gate": [list(p) for p in GATE],
        "places": PLACES,
    }
    OUT.write_text(json.dumps(geo, separators=(",", ":")))
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
