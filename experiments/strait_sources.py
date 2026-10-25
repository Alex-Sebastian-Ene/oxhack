# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26"]
# ///
"""Collect real observations of the Strait of Hormuz and turn them into estimator input.

None of these hosts is reachable from our cloud sessions (network policy), so this runs on a laptop.
Endpoints marked UNVERIFIED come from documentation and search snippets; check them on first use.
Keys come from the environment, never from git: GFW_TOKEN (Global Fishing Watch, free,
non-commercial).

    uv run experiments/strait_sources.py check    # which sources answer, and how fresh they are
    uv run experiments/strait_sources.py fetch    # download what we can into data/raw/strait/

Freshness, best case (docs/strait-live-data.md): Sentinel-1 scene ~3 h after a pass, passes days
apart; GFW AIS 3-4 days; GFW SAR detections ~5 days; PortWatch daily counts 3-10 days.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "strait"
BBOX = (54.6, 24.9, 57.9, 27.5)
POLYGON = [[BBOX[0], BBOX[1]], [BBOX[2], BBOX[1]], [BBOX[2], BBOX[3]], [BBOX[0], BBOX[3]], [BBOX[0], BBOX[1]]]

GFW = "https://gateway.api.globalfishingwatch.org/v3"
CDSE_ODATA = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
OPENSANCTIONS_MARITIME = "https://data.opensanctions.org/datasets/latest/maritime/targets.simple.csv"  # UNVERIFIED path
PORTWATCH = os.environ.get(
    "PORTWATCH_URL",  # UNVERIFIED: the ArcGIS layer behind portwatch.imf.org's chokepoint page
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/Daily_Chokepoints_Data/FeatureServer/0/query",
)


def get(url: str, params: dict | None = None, token: str | None = None, body: dict | None = None, timeout=60):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, safe="[]':,")
    headers = {"User-Agent": "oxhack-hormuz/0.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=timeout) as r:
        return r.read()


# --------------------------------------------------------------------------- sources

def sentinel1_passes(days: int = 14) -> list[dict]:
    """Sentinel-1 scenes over the strait from the Copernicus catalogue (no key needed to search)."""
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    wkt = "POLYGON((" + ",".join(f"{x} {y}" for x, y in POLYGON) + "))"
    flt = (f"Collection/Name eq 'SENTINEL-1' and ContentDate/Start gt {since} and "
           f"OData.CSC.Intersects(area=geography'SRID=4326;{wkt}')")
    rows = json.loads(get(CDSE_ODATA, {"$filter": flt, "$orderby": "ContentDate/Start desc", "$top": 50}))["value"]
    return [{"name": r["Name"], "start": r["ContentDate"]["Start"]} for r in rows]


def gfw_sar_unmatched(start: str, end: str, token: str) -> dict:
    """Radar detections with no matching AIS in the box (GFW 4Wings report). UNVERIFIED parameters."""
    return json.loads(get(f"{GFW}/4wings/report", {
        "spatial-resolution": "HIGH", "temporal-resolution": "DAILY", "format": "JSON",
        "datasets[0]": "public-global-sar-presence:latest", "filters[0]": "matched='false'",
        "date-range": f"{start},{end}", "group-by": "VESSEL_ID",
    }, token=token, body={"geojson": {"type": "Polygon", "coordinates": [POLYGON]}}))


def gfw_gap_events(start: str, end: str, token: str) -> dict:
    """'AIS off' events (prototype dataset) in the box. UNVERIFIED parameters."""
    return json.loads(get(f"{GFW}/events", {
        "datasets[0]": "public-global-gaps-events:latest", "start-date": start, "end-date": end, "limit": 500, "offset": 0,
    }, token=token, body={"geometry": {"type": "Polygon", "coordinates": [POLYGON]}}))


def gfw_vessel(query: str, token: str) -> dict:
    """Identity and registry records for an IMO, MMSI or name."""
    return json.loads(get(f"{GFW}/vessels/search", {
        "query": query, "datasets[0]": "public-global-vessel-identity:latest"}, token=token))


def portwatch_hormuz() -> list[dict]:
    """Daily AIS-visible transits through Hormuz (IMF PortWatch)."""
    out = json.loads(get(PORTWATCH, {"where": "portname='Strait of Hormuz'", "outFields": "*",
                                     "orderByFields": "date DESC", "resultRecordCount": 120, "f": "json"}))
    return [f["attributes"] for f in out.get("features", [])]


def sanctioned_imos(path: Path | None = None) -> set[str]:
    """IMO numbers of vessels on sanctions lists (OpenSanctions maritime, CC BY-NC)."""
    text = path.read_text() if path else get(OPENSANCTIONS_MARITIME).decode()
    imos = set()
    for row in csv.DictReader(io.StringIO(text)):
        for field in ("imo", "identifiers", "id"):
            for tok in (row.get(field) or "").replace(";", " ").split():
                digits = "".join(ch for ch in tok if ch.isdigit())
                if len(digits) == 7:
                    imos.add(digits)
    return imos


# --------------------------------------------------------------------------- real rows -> estimator input

TANKER_AIS_TYPES = range(80, 90)  # AIS ship-type codes 80-89 are tankers


def observations_to_sim(ais_rows: list[dict], sar_rows: list[dict], t0: datetime, lanes: dict, window_h: float,
                        corridor_lon=(55.3, 57.6), sar_passes: list[datetime] | None = None,
                        strait: str = "hormuz") -> dict:
    """Shape real AIS and radar rows like `strait_flow.simulate` output, so `estimate` runs unchanged.

    ais_rows: {"mmsi", "time" (datetime), "lon", "lat", "draught_m", "length_m", "ship_type"}
    sar_rows: {"time" (datetime), "lon", "lat", "length_m", "matched" (bool)}
    For Bab el-Mandeb pass strait="mandeb" and its corridor (strait_flow.STRAITS["mandeb"]["corridor_lon"]).
    """
    import strait_flow as sf

    lat0 = lanes["outbound"].lat0
    hours = lambda t: (t - t0).total_seconds() / 3600
    tracks: dict[str, list] = {}
    meta: dict[str, dict] = {}
    for r in ais_rows:
        if r.get("ship_type") not in TANKER_AIS_TYPES and (r.get("length_m") or 0) < 150:
            continue
        tracks.setdefault(str(r["mmsi"]), []).append((round(hours(r["time"]), 3), r["lon"], r["lat"]))
        meta[str(r["mmsi"])] = r
    ships = []
    for mmsi, tr in tracks.items():
        tr.sort()
        m = meta[mmsi]
        cls = sf.class_from_length(m.get("length_m") or 250)
        ships.append({"id": mmsi, "kind": "tanker", "mmsi": mmsi, "class": cls,
                      "lane": "outbound" if tr[-1][1] > tr[0][1] else "inbound",
                      "draught_m": m.get("draught_m") or 0.0, "ais": tr, "sar_hits": [], "ais_mode": "on"})
    passes = sorted({r["time"] for r in sar_rows}) if sar_passes is None else sorted(sar_passes)
    for r in sar_rows:
        if r.get("matched") or not (corridor_lon[0] <= r["lon"] <= corridor_lon[1]):
            continue
        # Direction from the nearer lane (Hormuz: outbound keeps to the southern lane).
        d = {k: min(math.dist(sf.to_km(r["lon"], r["lat"], lat0), sf.to_km(*lanes[k].at(s), lat0))
                    for s in range(0, int(lanes[k].length), 5)) for k in lanes}
        ships.append({"id": f"SAR-{len(ships)}", "kind": "tanker", "class": sf.class_from_length(r["length_m"]),
                      "lane": min(d, key=d.get), "draught_m": 0.0, "ais": [], "ais_mode": "off",
                      "sar_hits": [{"pass": passes.index(r["time"]), "lon": r["lon"], "lat": r["lat"],
                                    "length_m": r["length_m"]}]})
    return {"ships": ships, "corridor_lon": corridor_lon, "sar_passes_h": [hours(p) for p in passes],
            "window_h": window_h, "synthetic": False, "strait": strait}


# --------------------------------------------------------------------------- CLI

def check() -> None:
    token = os.environ.get("GFW_TOKEN")
    today = datetime.now(UTC).date()
    tests = {
        "Copernicus Sentinel-1 catalogue": lambda: (lambda p: f"{len(p)} scenes in 14 days, latest {p[0]['start'] if p else 'none'}")(sentinel1_passes()),
        "IMF PortWatch (Hormuz daily)": lambda: (lambda r: f"{len(r)} days, latest {r[0].get('date') if r else 'none'}")(portwatch_hormuz()),
        "OpenSanctions maritime": lambda: f"{len(sanctioned_imos())} IMO numbers",
        "GFW SAR (needs GFW_TOKEN)": (lambda: f"{len(json.dumps(gfw_sar_unmatched(str(today - timedelta(days=14)), str(today), token)))} bytes")
        if token else None,
    }
    for name, fn in tests.items():
        if fn is None:
            print(f"- {name}: skipped (no key)")
            continue
        try:
            print(f"- {name}: OK, {fn()}")
        except Exception as e:  # report and carry on: this is a reachability check
            print(f"- {name}: FAILED ({type(e).__name__}: {e})")


def fetch() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%MZ")
    (RAW / f"sentinel1_passes_{stamp}.json").write_text(json.dumps(sentinel1_passes(30), indent=1))
    (RAW / f"portwatch_hormuz_{stamp}.json").write_text(json.dumps(portwatch_hormuz(), indent=1))
    (RAW / "opensanctions_maritime.csv").write_bytes(get(OPENSANCTIONS_MARITIME))
    token = os.environ.get("GFW_TOKEN")
    if token:
        today = datetime.now(UTC).date()
        (RAW / f"gfw_sar_unmatched_{stamp}.json").write_text(json.dumps(gfw_sar_unmatched(str(today - timedelta(days=14)), str(today), token)))
        (RAW / f"gfw_gaps_{stamp}.json").write_text(json.dumps(gfw_gap_events(str(today - timedelta(days=14)), str(today), token)))
    print(f"saved to {RAW.relative_to(ROOT)} (collected {stamp})")


if __name__ == "__main__":
    {"check": check, "fetch": fetch}.get(sys.argv[1] if len(sys.argv) > 1 else "check", check)()
