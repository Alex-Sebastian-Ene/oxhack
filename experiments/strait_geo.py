# /// script
# requires-python = ">=3.11"
# dependencies = ["shapely>=2.0"]
# ///
"""Build the map geometry for a strait view (ui/strait/data/geo.json for Hormuz,
ui/strait/data/mandeb-geo.json for Bab el-Mandeb).

Land and islands come from Natural Earth 1:10m (public domain). The shipping lanes are hand-drawn
waypoints that follow the shape of each strait's traffic separation scheme. They are approximate,
for display and for the simulator only, never for navigation. The script refuses to write the file
if a lane or the counting gate touches land, if the gate is not a meridian, if a lane is not
monotonic in longitude, or if a lane misses the gate: the estimator and the map rely on all four.

    uv run experiments/strait_geo.py                  # Hormuz (default)
    uv run experiments/strait_geo.py --strait mandeb  # Bab el-Mandeb
    # downloads Natural Earth into data/raw/ if missing
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

from shapely.geometry import LineString, Polygon, box, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DATA = ROOT / "ui" / "strait" / "data"
NE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/{}.geojson"
LAYERS = ("ne_10m_land", "ne_10m_minor_islands")
SOURCE = "Natural Earth 1:10m land + minor islands (public domain); lanes approximate, not for navigation"

# Each strait: bbox is the starting view (lon_min, lat_min, lon_max, lat_max); clip keeps land for a
# wider area so panning never shows a cut edge. Lanes are (lon, lat) waypoints listed west to east.
# "outbound" is the lane leaving the enclosed sea (the Gulf for Hormuz, the Red Sea for Bab
# el-Mandeb), "inbound" the lane entering it. Ships keep to starboard. The gate is a meridian
# segment across the strait where crossings are counted. lat0 is the latitude the map and the
# simulator use to turn degrees into km; Hormuz leaves it out and readers default to 26.4.
STRAITS = {
    "hormuz": {
        "out": DATA / "geo.json",
        "bbox": (54.6, 24.9, 57.9, 27.5),
        "clip": (52.5, 23.0, 60.0, 29.0),
        # Westbound (into the Gulf) traffic uses the northern lane, eastbound (out of it) the southern.
        "lanes": {
            "inbound": [(54.6, 26.12), (55.0, 26.18), (55.45, 26.38), (55.85, 26.55), (56.2, 26.64),
                        (56.45, 26.6), (56.65, 26.42), (56.85, 26.15), (57.1, 25.85), (57.9, 25.45)],
            "outbound": [(54.6, 26.02), (55.0, 26.08), (55.45, 26.28), (55.85, 26.46), (56.2, 26.55),
                         (56.4, 26.5), (56.58, 26.36), (56.78, 26.1), (57.02, 25.8), (57.9, 25.35)],
        },
        # Across the narrows, between the Musandam peninsula and Larak island.
        "gate": [(56.42, 26.42), (56.42, 26.78)],
        "places": [
            {"name": "IRAN", "lon": 56.9, "lat": 27.25, "kind": "country"},
            {"name": "OMAN (Musandam)", "lon": 56.2, "lat": 25.95, "kind": "country"},
            {"name": "UAE", "lon": 55.35, "lat": 25.2, "kind": "country"},
            {"name": "Persian Gulf", "lon": 55.05, "lat": 26.55, "kind": "sea"},
            {"name": "Gulf of Oman", "lon": 57.35, "lat": 25.3, "kind": "sea"},
            {"name": "Bandar Abbas", "lon": 56.28, "lat": 27.18, "kind": "port"},
            {"name": "Fujairah", "lon": 56.36, "lat": 25.12, "kind": "port"},
            {"name": "Khasab", "lon": 56.25, "lat": 26.18, "kind": "port"},
        ],
    },
    "mandeb": {
        "out": DATA / "mandeb-geo.json",
        "bbox": (42.5, 11.8, 44.5, 13.6),
        "clip": (40.5, 10.3, 46.5, 15.3),
        "lat0": 12.6,
        # The Bab el-Mandeb TSS runs through the main channel west of Perim (Mayyun) island, about
        # 40 km long (CNES). Southbound traffic (out of the Red Sea, toward the Gulf of Aden) keeps to
        # the western lane, northbound (toward Suez) to the eastern one. North of the strait the lanes
        # pass east of the Hanish islands, as the IMO scheme off Jabal Zuqar does.
        "lanes": {
            "inbound": [(43.05, 13.6), (43.13, 13.3), (43.22, 13.0), (43.3, 12.8), (43.35, 12.69),
                        (43.4, 12.6), (43.56, 12.515), (43.85, 12.39), (44.15, 12.26), (44.5, 12.13)],
            "outbound": [(42.95, 13.6), (43.03, 13.3), (43.12, 13.0), (43.21, 12.8), (43.29, 12.64),
                         (43.38, 12.535), (43.52, 12.46), (43.8, 12.33), (44.1, 12.2), (44.5, 12.06)],
        },
        # From the Djibouti shore north to Perim: closes the southern mouth of the main channel.
        "gate": [(43.41, 12.255), (43.41, 12.643)],
        "places": [
            {"name": "YEMEN", "lon": 43.9, "lat": 13.1, "kind": "country"},
            {"name": "DJIBOUTI", "lon": 42.85, "lat": 12.2, "kind": "country"},
            {"name": "ERITREA", "lon": 42.55, "lat": 12.8, "kind": "country"},
            {"name": "Red Sea", "lon": 42.7, "lat": 13.45, "kind": "sea"},
            {"name": "Gulf of Aden", "lon": 44.0, "lat": 11.95, "kind": "sea"},
            {"name": "Perim (Mayyun)", "lon": 43.45, "lat": 12.66, "kind": "island"},
            {"name": "Aden", "lon": 45.03, "lat": 12.79, "kind": "port"},
            {"name": "Djibouti", "lon": 43.145, "lat": 11.59, "kind": "port"},
            {"name": "Assab", "lon": 42.74, "lat": 13.01, "kind": "port"},
            {"name": "Mocha", "lon": 43.25, "lat": 13.32, "kind": "port"},
        ],
    },
}
# Hormuz names, for anything that imported them before there was more than one strait.
BBOX, CLIP, LANES, GATE, PLACES = (STRAITS["hormuz"][k] for k in ("bbox", "clip", "lanes", "gate", "places"))
OUT = STRAITS["hormuz"]["out"]


def load_land(clip_box=CLIP) -> Polygon:
    clip = box(*clip_box)
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


def check_layout(lanes: dict, gate) -> None:
    """The estimator and the map find a crossing by the meridian of the gate, so the gate must be a
    meridian, each lane must run monotonically in longitude, and each lane must cross the gate."""
    (g_lon, g_lat0), (g_lon1, g_lat1) = gate
    if g_lon != g_lon1:
        raise SystemExit("gate must be a meridian (both ends at the same longitude)")
    for name, pts in lanes.items():
        lons = [p[0] for p in pts]
        if any(b <= a for a, b in zip(lons, lons[1:])):
            raise SystemExit(f"lane {name} must run west to east with rising longitude")
        for a, b in zip(pts, pts[1:]):
            if a[0] <= g_lon <= b[0]:
                lat = a[1] + (g_lon - a[0]) / (b[0] - a[0]) * (b[1] - a[1])
                if not min(g_lat0, g_lat1) < lat < max(g_lat0, g_lat1):
                    raise SystemExit(f"lane {name} crosses the gate meridian at {lat:.3f}N, outside the gate")
                break
        else:
            raise SystemExit(f"lane {name} never reaches the gate meridian")


def rounded(geom, nd=4):
    def r(c):
        return [round(c[0], nd), round(c[1], nd)]
    g = mapping(geom)
    if g["type"] == "Polygon":
        return {"type": "MultiPolygon", "coordinates": [[[r(c) for c in ring] for ring in g["coordinates"]]]}
    return {"type": "MultiPolygon", "coordinates": [[[r(c) for c in ring] for ring in poly] for poly in g["coordinates"]]}


def build(strait: str = "hormuz") -> dict:
    cfg = STRAITS[strait]
    land = load_land(cfg["clip"]).simplify(0.004, preserve_topology=True)
    check_layout(cfg["lanes"], cfg["gate"])
    for name, coords in cfg["lanes"].items():
        check_clear(land, f"lane {name}", coords)
    check_clear(land, "gate", cfg["gate"])
    geo = {
        "bbox": cfg["bbox"],
        "clip": cfg["clip"],
        "source": SOURCE,
        "land": rounded(land),
        "lanes": {k: [list(p) for p in v] for k, v in cfg["lanes"].items()},
        "gate": [list(p) for p in cfg["gate"]],
        "places": cfg["places"],
    }
    if "lat0" in cfg:
        geo["lat0"] = cfg["lat0"]
    return geo


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strait", choices=sorted(STRAITS), default="hormuz")
    args = ap.parse_args()
    out = STRAITS[args.strait]["out"]
    geo = build(args.strait)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(geo, separators=(",", ":")))
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
