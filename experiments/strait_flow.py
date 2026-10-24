# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26"]
# ///
"""Estimate how much oil actually moves through the Strait of Hormuz, and flag likely ghost ships.

Three signals, combined with Monte Carlo ranges (docs/strait-live-data.md explains why):

1. Seen: AIS tracks that cross a gate line across the narrows, outbound and laden, after
   dropping tracks that fail plausibility checks (spoofing).
2. Bridged: ships that switch AIS off on one side of the gate and reappear on the other. Their
   crossing is certain even though nobody saw it.
3. Never seen: radar (SAR) detections in a corridor through the strait that match no AIS track and
   no bridged ship. One snapshot of L such ships, with W hours to cross the corridor, means about
   L / W crossings per hour (Little's law).

There is no free live AIS or radar feed for Hormuz, so `simulate` builds a synthetic 48-hour
window calibrated to a published flow figure. The estimator runs on the synthetic observations
exactly as it would on real ones, and the output keeps the true synthetic value next to the
estimate so the method can be checked. Everything simulated is labelled SYNTHETIC.

    uv run experiments/strait_flow.py   # writes ui/strait/data/scenarios.js and notes/strait-flow.md
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "ui" / "strait" / "data" / "geo.json"
BUNDLE = ROOT / "ui" / "strait" / "data" / "scenarios.js"
NOTE = ROOT / "notes" / "strait-flow.md"

KM_PER_DEG_LAT = 111.32
KNOT_KMH = 1.852
WINDOW_H = 48.0

# Published reference figures (see docs/strait-live-data.md for sources and caveats).
PREWAR_FLOW_MBD = 20.0          # EIA, 2024 average through Hormuz (crude + products)
WORLD_CONSUMPTION_MBD = 103.29  # IEA Oil Market Report, Aug 2026: 2026 world demand
SEABORNE_SHARE = 77.5 / 101.9   # EIA World Oil Transit Chokepoints: 2023 seaborne vs total supply
CRUDE_SHARE = (0.72, 0.75)      # Hormuz 2025: crude + condensate share (EIA and IEA), rest products
PUBLISHED = [
    {"who": "EIA (pre-war baseline)", "when": "2024 average", "mbd": 20.0},
    {"who": "EIA quarterly chokepoint data", "when": "Q1 2026", "mbd": 14.6},
    {"who": "Vortexa (via Argus)", "when": "Aug 2026", "mbd": 3.5},
    {"who": "Argus", "when": "Aug 2026", "mbd": 3.7},
    {"who": "Windward (satellite)", "when": "20-22 Sep 2026", "mbd": 8.9},
    {"who": "US officials (via Argus)", "when": "Aug 2026", "mbd": 10.0},
]

# Tanker classes: typical length (m), design draught (m), full cargo (million barrels), share of
# laden tankers by count in the simulator. Cargo sizes are industry rules of thumb.
CLASSES = {
    "VLCC": {"length": 330, "draught": 21.0, "cargo": 2.0, "share": 0.35},
    "Suezmax": {"length": 275, "draught": 17.0, "cargo": 1.0, "share": 0.15},
    "Aframax/LR2": {"length": 245, "draught": 14.5, "cargo": 0.75, "share": 0.2},
    "MR": {"length": 183, "draught": 12.0, "cargo": 0.3, "share": 0.3},
}

# Maritime Identification Digits (first three digits of an MMSI) -> flag. A subset for display;
# the authoritative table is the ITU's MARS database.
MID = {
    **{m: "Panama" for m in (351, 352, 353, 354, 355, 356, 357, 370, 371, 372, 373, 374)},
    **{m: "Liberia" for m in (636, 637)}, 538: "Marshall Islands",
    **{m: "Malta" for m in (215, 229, 248, 249, 256)}, **{m: "Greece" for m in (237, 239, 240, 241)},
    **{m: "Bahamas" for m in (308, 309, 311)}, **{m: "Cyprus" for m in (209, 210, 212)},
    **{m: "Singapore" for m in (563, 564, 565, 566)}, 477: "Hong Kong", 422: "Iran",
    **{m: "UAE" for m in (470, 471)}, 461: "Oman", 403: "Saudi Arabia", 466: "Qatar",
    447: "Kuwait", 419: "India", **{m: "China" for m in (412, 413, 414)}, 273: "Russia",
    616: "Comoros", 613: "Cameroon", 626: "Gabon", 518: "Cook Islands", 511: "Palau",
    667: "Sierra Leone", 677: "Tanzania", 576: "Vanuatu", 577: "Vanuatu", 341: "St Kitts and Nevis",
}


# --------------------------------------------------------------------------- identity checks

def imo_valid(imo: str | int | None) -> bool:
    """IMO ship numbers are 7 digits; the last is sum(digit_i * (7 - i)) for i = 0..5, mod 10."""
    s = str(imo or "").removeprefix("IMO").strip()
    if len(s) != 7 or not s.isdigit():
        return False
    return sum(int(d) * w for d, w in zip(s[:6], range(7, 1, -1))) % 10 == int(s[6])


def imo_with_check(six: int) -> str:
    s = f"{six:06d}"
    return s + str(sum(int(d) * w for d, w in zip(s, range(7, 1, -1))) % 10)


def mmsi_flag(mmsi: str | int | None) -> str | None:
    s = str(mmsi or "")
    if len(s) != 9 or not s.isdigit():
        return None
    return MID.get(int(s[:3]))


# --------------------------------------------------------------------------- ghost-ship score

# Weights are log-odds added to a prior. They are judgement calls to be tuned once we have labelled
# examples (reviewed dossiers); each maps to an indicator analysts use (docs/strait-live-data.md).
GHOST_PRIOR = -2.0
# Registries most used by falsely flagged tankers at end-2025 (Windward). The Netherlands Antilles
# was dissolved in 2010, so any ship claiming it is falsely flagged.
FRAUDULENT_FLAGS = {"Guinea", "Netherlands Antilles", "Guyana", "Aruba"}
GHOST_RULES = [
    ("radar_only", 2.5, "Seen by radar in the strait with no AIS signal at all"),
    ("ais_gap", 1.5, "AIS switched off inside the strait"),
    ("spoofing", 0.6, "Position unreliable: impossible AIS jumps (could be jamming, not deception)"),
    ("sanctioned", 2.0, "IMO number on a sanctions list"),
    ("false_flag", 1.5, "Claims a registry known for false flags"),
    ("bad_imo", 1.5, "IMO number fails its check digit (fake or reused identity?)"),
    ("flag_mismatch", 1.0, "Flag from MMSI differs from registry flag"),
    ("flag_hops", 0.8, "Two or more flag changes in 12 months"),
    ("old", 0.6, "15 or more years old"),
    ("opaque_owner", 0.8, "Owner unknown or a single-ship shell company"),
    ("sts", 1.0, "Met another tanker at sea (ship-to-ship transfer)"),
    ("for_orders", 0.3, "Destination blank or 'FOR ORDERS'"),
]


def ghost_score(v: dict) -> dict:
    """Probability-like score in [0, 1] plus the reasons that fired."""
    flags = {
        "radar_only": v.get("ais_mode") == "off" and bool(v.get("sar_hits")),
        "ais_gap": v.get("ais_mode") == "gap",
        "spoofing": v.get("ais_mode") == "spoof",
        "sanctioned": bool(v.get("sanctioned")),
        "bad_imo": v.get("imo") is not None and not imo_valid(v.get("imo")),
        "flag_mismatch": bool(v.get("flag") and mmsi_flag(v.get("mmsi"))
                              and v["flag"] != mmsi_flag(v.get("mmsi"))),
        "false_flag": v.get("flag") in FRAUDULENT_FLAGS,
        "flag_hops": (v.get("flag_changes_12m") or 0) >= 2,
        "old": (v.get("built") or 9999) <= datetime.now(UTC).year - 15,
        "opaque_owner": bool(v.get("owner_opaque")),
        "sts": bool(v.get("sts")),
        "for_orders": (v.get("destination") or "").strip().upper() in ("", "FOR ORDERS"),
    }
    z = GHOST_PRIOR + sum(w for k, w, _ in GHOST_RULES if flags[k])
    return {"score": round(1 / (1 + math.exp(-z)), 3),
            "codes": [k for k, _, _ in GHOST_RULES if flags[k]],
            "reasons": [text for k, _, text in GHOST_RULES if flags[k]]}


# --------------------------------------------------------------------------- geometry

def to_km(lon: float, lat: float, lat0: float = 26.4) -> tuple[float, float]:
    return lon * KM_PER_DEG_LAT * math.cos(math.radians(lat0)), lat * KM_PER_DEG_LAT


@dataclass
class Lane:
    points: list[tuple[float, float]]  # (lon, lat), in direction of travel
    cum: list[float] = field(init=False)

    def __post_init__(self):
        self.cum = [0.0]
        for a, b in zip(self.points, self.points[1:]):
            (ax, ay), (bx, by) = to_km(*a), to_km(*b)
            self.cum.append(self.cum[-1] + math.hypot(bx - ax, by - ay))

    @property
    def length(self) -> float:
        return self.cum[-1]

    def at(self, s: float) -> tuple[float, float]:
        s = min(max(s, 0.0), self.length)
        i = max(j for j, c in enumerate(self.cum) if c <= s) if s < self.length else len(self.cum) - 2
        f = (s - self.cum[i]) / (self.cum[i + 1] - self.cum[i])
        (ax, ay), (bx, by) = self.points[i], self.points[i + 1]
        return ax + f * (bx - ax), ay + f * (by - ay)

    def s_at_lon(self, lon: float) -> float:
        """Distance along the lane where it crosses a meridian (lanes are monotonic in lon)."""
        for i, (a, b) in enumerate(zip(self.points, self.points[1:])):
            if min(a[0], b[0]) <= lon <= max(a[0], b[0]):
                return self.cum[i] + (lon - a[0]) / (b[0] - a[0]) * (self.cum[i + 1] - self.cum[i])
        raise ValueError(f"lane does not reach lon {lon}")


def load_lanes(geo: dict) -> dict[str, Lane]:
    # Outbound ships travel west -> east, inbound east -> west.
    return {"outbound": Lane([tuple(p) for p in geo["lanes"]["outbound"]]),
            "inbound": Lane([tuple(p) for p in reversed(geo["lanes"]["inbound"])])}


def crosses_gate(p: tuple[float, float], q: tuple[float, float], gate) -> bool:
    """Segment p-q crosses the gate segment (proper intersection test)."""
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    g0, g1 = gate
    return (orient(g0, g1, p) * orient(g0, g1, q) < 0) and (orient(p, q, g0) * orient(p, q, g1) < 0)


def implied_speed_kn(a: tuple, b: tuple) -> float:
    """a, b = (t_hours, lon, lat)."""
    (ax, ay), (bx, by) = to_km(a[1], a[2]), to_km(b[1], b[2])
    dt = abs(b[0] - a[0])
    return math.inf if dt == 0 else math.hypot(bx - ax, by - ay) / dt / KNOT_KMH


# --------------------------------------------------------------------------- simulator

SCENARIOS = {
    "prewar": {"label": "Pre-war (EIA 2024 average)", "flow_mbd": 20.0, "dark": {"gap": 0.03, "off": 0.02, "spoof": 0.02}},
    "aug2026": {"label": "Aug 2026, trackers' view (~3.5 mb/d visible)", "flow_mbd": 6.0, "dark": {"gap": 0.25, "off": 0.30, "spoof": 0.15}},
    "sep2026": {"label": "Sep 2026, satellite view (~8.9 mb/d)", "flow_mbd": 8.9, "dark": {"gap": 0.25, "off": 0.30, "spoof": 0.15}},
}
SAR_PASSES_H = (14.5, 38.5)   # two radar passes in the 48 h window (e.g. one per ~day)
SAR_RECALL = 0.9              # share of tankers in view that a pass detects
OTHER_SHIPS_PER_DAY = 30      # non-tankers each way, for the picture only
NAMES = ["ARIEL", "BOREAS", "CALYPSO", "DORADO", "ELARA", "FENIX", "GALENE", "HALCYON", "IONA",
         "JUNO", "KESTREL", "LYRA", "MERIDIAN", "NEREID", "ORION", "PERSEUS", "QUILL", "RIGEL",
         "SIRIUS", "TETHYS", "UMBRA", "VEGA", "WREN", "XANTHE", "YARA", "ZEPHYR"]
FLAGS = [("Panama", 351), ("Liberia", 636), ("Marshall Islands", 538), ("Malta", 215),
         ("Greece", 240), ("Bahamas", 311), ("Singapore", 563), ("Hong Kong", 477),
         ("UAE", 470), ("Iran", 422), ("Comoros", 616), ("Cameroon", 613), ("Gabon", 626)]


def simulate(key: str, lanes: dict[str, Lane], gate, seed: int = 7) -> dict:
    """Synthetic ships for a 48 h window, calibrated so true laden outbound flow = scenario flow."""
    sc = SCENARIOS[key]
    rng = np.random.default_rng(seed)
    gate_lon = gate[0][0]
    cls_names = list(CLASSES)
    mean_cargo = sum(CLASSES[c]["cargo"] * CLASSES[c]["share"] for c in cls_names)
    per_day = sc["flow_mbd"] / (mean_cargo * 0.95)  # laden outbound tankers per day (load ~95%)
    ships = []

    def add(direction: str, kind: str, n: int):
        lane = lanes[direction]
        s_gate = lane.s_at_lon(gate_lon)
        for _ in range(n):
            speed = (rng.uniform(11, 14) if kind == "tanker" else rng.uniform(13, 19)) * KNOT_KMH
            t_gate = rng.uniform(0, WINDOW_H)            # when it crosses the gate
            t0 = t_gate - s_gate / speed                 # when it was at the lane start
            idx = len(ships)
            flag, mid = FLAGS[rng.integers(len(FLAGS))]
            v = {"id": f"S{idx:04d}", "kind": kind, "lane": direction, "t0": round(t0, 3),
                 "speed_kmh": round(speed, 2), "t_gate": round(t_gate, 3), "synthetic": True,
                 "name": f"{NAMES[rng.integers(len(NAMES))]} {rng.integers(1, 99)}",
                 "mmsi": f"{mid}{rng.integers(0, 10**6):06d}", "flag": flag,
                 "imo": imo_with_check(int(rng.integers(900000, 999999))),
                 "built": int(rng.integers(1998, 2024)), "flag_changes_12m": 0,
                 "destination": "", "sanctioned": False, "sts": False}
            if kind == "tanker":
                c = rng.choice(cls_names, p=[CLASSES[c]["share"] for c in cls_names])
                laden = direction == "outbound" and rng.random() < 0.97
                load = rng.uniform(0.9, 1.0) if laden else 0.0
                v.update({"class": c, "length_m": CLASSES[c]["length"], "laden": bool(laden),
                          "cargo_mbbl": round(CLASSES[c]["cargo"] * load, 3),
                          "draught_m": round(CLASSES[c]["draught"] * (0.95 if laden else 0.55), 1)})
                r = rng.random()
                d = sc["dark"]
                mode = "gap" if r < d["gap"] else "off" if r < d["gap"] + d["off"] else \
                       "spoof" if r < d["gap"] + d["off"] + d["spoof"] else "on"
                v["ais_mode"] = mode
                if mode == "gap":   # dark for a stretch that straddles the gate
                    v["gap_km"] = [round(s_gate - rng.uniform(25, 60), 1), round(s_gate + rng.uniform(25, 60), 1)]
                if mode != "on":    # risky identities are more common among ships that hide
                    v["sanctioned"] = bool(rng.random() < 0.4)
                    v["flag_changes_12m"] = int(rng.integers(0, 4))
                    v["built"] = int(rng.integers(1996, 2008))
                    v["destination"] = rng.choice(["", "FOR ORDERS", "SINGAPORE", "ZHOUSHAN"])
                    v["owner_opaque"] = bool(rng.random() < 0.6)
                    if rng.random() < 0.1:
                        v["flag"] = rng.choice(sorted(FRAUDULENT_FLAGS))
                    v["sts"] = bool(rng.random() < 0.2)
                    if rng.random() < 0.15:  # stolen or made-up identity
                        v["imo"] = f"{int(rng.integers(9000000, 9999999))}"
                else:
                    v["destination"] = rng.choice(["FUJAIRAH", "SINGAPORE", "NINGBO", "ROTTERDAM", "CHIBA"])
            else:
                v.update({"class": rng.choice(["Container", "Bulk", "General cargo", "LNG"]),
                          "length_m": int(rng.integers(120, 360)), "laden": None, "cargo_mbbl": 0.0,
                          "ais_mode": "on", "destination": rng.choice(["JEBEL ALI", "DAMMAM", "MUMBAI"])})
            ships.append(v)

    days = WINDOW_H / 24
    add("outbound", "tanker", int(round(per_day * days)))
    add("inbound", "tanker", int(round(per_day * days)))   # mostly in ballast, coming to load
    add("outbound", "other", OTHER_SHIPS_PER_DAY * 2)
    add("inbound", "other", OTHER_SHIPS_PER_DAY * 2)

    # Observations: AIS positions every 10 minutes (with gaps, spoofed jumps or nothing) and
    # SAR detections at the two passes.
    corridor = (55.3, 57.6)  # lon range of the radar corridor: about one Sentinel-1 IW swath (~250 km)
    for v in ships:
        lane = lanes[v["lane"]]
        track = []
        for k in range(int(WINDOW_H * 6) + 1):
            t = k / 6
            s = (t - v["t0"]) * v["speed_kmh"]
            if s < 0 or s > lane.length:
                continue
            if v["ais_mode"] == "off" or (v["ais_mode"] == "gap" and v["gap_km"][0] <= s <= v["gap_km"][1]):
                continue
            lon, lat = lane.at(s)
            if v["ais_mode"] == "spoof" and rng.random() < 0.08:   # occasional jump inland or far away
                lon, lat = lon + rng.uniform(-0.6, 0.6), lat + rng.uniform(0.3, 0.8)
            track.append((round(t, 3), round(lon, 4), round(lat, 4)))
        v["ais"] = track
        v["sar_hits"] = []
        for i, tp in enumerate(SAR_PASSES_H):
            s = (tp - v["t0"]) * v["speed_kmh"]
            if 0 <= s <= lane.length and v["kind"] == "tanker":
                lon, lat = lane.at(s)
                if corridor[0] <= lon <= corridor[1] and rng.random() < SAR_RECALL:
                    v["sar_hits"].append({"pass": i, "lon": round(lon, 4), "lat": round(lat, 4),
                                          "length_m": round(v["length_m"] * rng.uniform(0.85, 1.15))})
        v["ghost"] = ghost_score(v) if v["kind"] == "tanker" else {"score": 0.0, "codes": [], "reasons": []}
    truth = sum(v["cargo_mbbl"] for v in ships if v["kind"] == "tanker" and v["lane"] == "outbound"
                and 0 <= v["t_gate"] < WINDOW_H) / days
    return {"scenario": key, "label": sc["label"], "ships": ships, "truth_mbd": round(truth, 2),
            "corridor_lon": corridor, "sar_passes_h": SAR_PASSES_H}


# --------------------------------------------------------------------------- estimator

def clean_track(track: list[tuple]) -> tuple[list[tuple], int]:
    """Drop points that imply an impossible speed from the previous kept point."""
    kept, dropped = [], 0
    for p in track:
        if kept and implied_speed_kn(kept[-1], p) > 40:
            dropped += 1
            continue
        kept.append(p)
    return kept, dropped


def class_from_length(length_m: float) -> str:
    return min(CLASSES, key=lambda c: abs(CLASSES[c]["length"] - length_m))


def estimate(sim: dict, lanes: dict[str, Lane], gate, draws: int = 4000, seed: int = 11) -> dict:
    """Seen + bridged + never-seen laden outbound flow, mb/d, with a Monte Carlo range."""
    rng = np.random.default_rng(seed)
    days = WINDOW_H / 24
    mean_cargo = sum(c["cargo"] * c["share"] for c in CLASSES.values())
    tankers = [v for v in sim["ships"] if v["kind"] == "tanker"]
    seen, bridged, spoof_dropped = [], [], 0

    for v in tankers:
        track, dropped = clean_track([tuple(p) for p in v["ais"]])
        spoof_dropped += dropped
        if v["lane"] != "outbound" or not track:
            continue
        g_lon = gate[0][0]
        for p, q in zip(track, track[1:]):
            gap = (q[0] - p[0]) > 0.5   # more than 30 min of silence
            # Across a gap the straight line between the last and next positions can cut the
            # corner of the curved lane and miss the gate, so any jump across its meridian counts.
            if gap and (p[1] - g_lon) * (q[1] - g_lon) < 0:
                bridged.append(v)
                break
            if not gap and crosses_gate((p[1], p[2]), (q[1], q[2]), gate):
                seen.append(v)
                break

    # Radar: detections not explained by an AIS position within 30 min / 5 km, nor by a bridged
    # ship whose position we can interpolate between its last and next AIS points.
    out_lane = lanes["outbound"]
    corridor_km = out_lane.s_at_lon(sim["corridor_lon"][1]) - out_lane.s_at_lon(sim["corridor_lon"][0])
    unmatched = {i: [] for i in range(len(sim["sar_passes_h"]))}
    for v in tankers:
        for hit in v["sar_hits"]:
            tp = sim["sar_passes_h"][hit["pass"]]
            near = [p for p in v["ais"] if abs(p[0] - tp) <= 0.5]
            if any(math.dist(to_km(p[1], p[2]), to_km(hit["lon"], hit["lat"])) < 5 for p in near):
                continue
            before = [p for p in v["ais"] if p[0] < tp]
            after = [p for p in v["ais"] if p[0] > tp]
            if before and after:   # explained by dead reckoning between known AIS points
                continue
            if v["lane"] == "outbound":   # southern lane = outbound; lane tells the direction
                unmatched[hit["pass"]].append(hit)

    def cargo_seen(v, load):
        return CLASSES[v["class"]]["cargo"] * load if v["draught_m"] >= 0.8 * CLASSES[v["class"]]["draught"] else 0.0

    seen_mbd = np.zeros(draws)
    bridged_mbd = np.zeros(draws)
    hidden_mbd = np.zeros(draws)
    for k in range(draws):
        load = rng.uniform(0.88, 1.0)
        seen_mbd[k] = sum(cargo_seen(v, load) for v in seen) / days
        bridged_mbd[k] = sum(cargo_seen(v, load) for v in bridged) / days
        recall = rng.uniform(0.8, 0.95)
        false_pos = rng.uniform(0.0, 0.08)
        laden_share = rng.uniform(0.6, 0.98)
        speed = rng.uniform(10.5, 14.5) * KNOT_KMH
        w_hours = corridor_km / speed
        rates = []
        for hits in unmatched.values():
            # A snapshot sees only a few ships, so treat the count as Poisson: the expected number in
            # the corridor is drawn from its posterior (Jeffreys prior), not taken as exact.
            ships_in_view = rng.gamma(len(hits) + 0.5, 1.0)
            per_ship = (np.mean([CLASSES[class_from_length(h["length_m"] * rng.uniform(0.9, 1.1))]["cargo"]
                                 for h in hits]) if hits else mean_cargo)
            rates.append(ships_in_view * per_ship * (1 - false_pos) / recall / w_hours)  # mbbl/h
        hidden_mbd[k] = np.mean(rates) * 24 * laden_share * load if rates else 0.0

    total = seen_mbd + bridged_mbd + hidden_mbd

    def band(x):
        return {"p5": round(float(np.percentile(x, 5)), 2), "p50": round(float(np.percentile(x, 50)), 2),
                "p95": round(float(np.percentile(x, 95)), 2)}

    t = band(total)
    return {
        "seen": band(seen_mbd), "bridged": band(bridged_mbd), "hidden": band(hidden_mbd), "total": t,
        "counts": {"seen_crossings": len(seen), "bridged_crossings": len(bridged),
                   "unmatched_radar": {str(k): len(v) for k, v in unmatched.items()},
                   "spoofed_points_dropped": spoof_dropped},
        "global": {
            "world_consumption_mbd": WORLD_CONSUMPTION_MBD,
            "share_of_world_p50": round(t["p50"] / WORLD_CONSUMPTION_MBD, 4),
            "share_of_seaborne_p50": round(t["p50"] / (WORLD_CONSUMPTION_MBD * SEABORNE_SHARE), 4),
            "crude_mbd_p50": [round(t["p50"] * c, 2) for c in CRUDE_SHARE],
            "missing_vs_prewar_mbd": {k: round(PREWAR_FLOW_MBD - v, 2) for k, v in t.items()},
        },
        "assumptions": {
            "load_factor": [0.88, 1.0], "sar_recall": [0.8, 0.95], "sar_false_positive": [0.0, 0.08],
            "laden_share_of_dark_outbound": [0.6, 0.98], "speed_kn": [10.5, 14.5],
            "corridor_km_outbound": round(corridor_km, 1), "draws": draws,
            "radar_count": "Poisson, Jeffreys prior",
        },
    }


# --------------------------------------------------------------------------- output

def ui_ship(v: dict) -> dict:
    keep = ("id", "kind", "lane", "t0", "speed_kmh", "name", "mmsi", "flag", "imo", "built", "class",
            "length_m", "laden", "cargo_mbbl", "draught_m", "ais_mode", "gap_km", "destination", "owner_opaque",
            "sanctioned", "sts", "flag_changes_12m", "sar_hits", "ghost")
    out = {k: v[k] for k in keep if k in v}
    out["mmsi_flag"] = mmsi_flag(v.get("mmsi"))
    out["imo_valid"] = imo_valid(v.get("imo"))
    if v["ais_mode"] == "spoof":   # the fake positions it broadcast, for the map to show
        kept, _ = clean_track([tuple(p) for p in v["ais"]])
        out["spoof_points"] = [p for p in v["ais"] if tuple(p) not in set(kept)]
    return out


def main() -> None:
    geo = json.loads(GEO.read_text())
    lanes = load_lanes(geo)
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    rows, payloads = [], {}
    for key in SCENARIOS:
        sim = simulate(key, lanes, geo["gate"])
        est = estimate(sim, lanes, geo["gate"])
        payload = {
            "generated": now, "synthetic": True, "scenario": key, "label": sim["label"],
            "window_h": WINDOW_H, "sar_passes_h": sim["sar_passes_h"], "corridor_lon": sim["corridor_lon"],
            "truth_mbd": sim["truth_mbd"], "estimate": est, "published": PUBLISHED,
            "lane_km": {d: round(l.length, 1) for d, l in lanes.items()},
            "ships": [ui_ship(v) for v in sim["ships"]],
        }
        payloads[key] = payload
        t = est["total"]
        rows.append(f"| {sim['label']} | {sim['truth_mbd']:.1f} | {est['seen']['p50']:.1f} | "
                    f"{est['bridged']['p50']:.1f} | {est['hidden']['p50']:.1f} | "
                    f"{t['p50']:.1f} ({t['p5']:.1f}–{t['p95']:.1f}) |")
        print(f"{key}: truth {sim['truth_mbd']:.2f}, estimate {t['p50']:.2f} [{t['p5']:.2f}, {t['p95']:.2f}]")
    # One script file, so the page also works when opened straight from disk (file://).
    BUNDLE.write_text("window.STRAIT = " + json.dumps({"geo": geo, "scenarios": payloads}, separators=(",", ":")) + ";\n")
    print(f"wrote {BUNDLE.relative_to(ROOT)} ({BUNDLE.stat().st_size // 1024} KB)")
    NOTE.write_text(
        "# Strait flow estimator on synthetic scenarios\n\n"
        f"Generated {now} by `uv run experiments/strait_flow.py`. **All ships are SYNTHETIC**: each "
        "scenario is calibrated so the true laden outbound flow matches a published figure, then the "
        "estimator sees only what AIS and two radar passes would show. Units: million barrels/day.\n\n"
        "| Scenario | True (synthetic) | Seen on AIS | Bridged gaps | Never seen (radar) | Estimate (90% range) |\n"
        "|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n\n"
        "Method and assumptions: `docs/strait-live-data.md`.\n")
    print(f"wrote {NOTE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
