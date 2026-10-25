"""Bab el-Mandeb in experiments/strait_flow.py and strait_geo.py: map geometry, the estimator on its
synthetic scenarios, the shared data shape with Hormuz, and that Hormuz output did not change."""

import json
from pathlib import Path

import numpy as np
import pytest

import strait_flow as sf

DATA = Path(__file__).resolve().parent.parent / "ui" / "strait" / "data"
GEO = json.loads((DATA / "mandeb-geo.json").read_text())
LANES = sf.load_lanes(GEO)
HORMUZ_GEO = json.loads((DATA / "geo.json").read_text())
HORMUZ_LANES = sf.load_lanes(HORMUZ_GEO)


def bundle(name: str, prefix: str) -> dict:
    text = (DATA / name).read_text()
    assert text.endswith(";\n")
    return json.loads(text[text.index(prefix) + len(prefix):-2])


# --------------------------------------------------------------------------- geometry
# Pure Python, so the test needs no shapely: a lane touches land only if one of its segments crosses
# a coastline edge or one of its points sits inside a land polygon.

def _cross(p, q, a, b) -> bool:
    def orient(u, v, w):
        return (v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0])
    return orient(a, b, p) * orient(a, b, q) <= 0 and orient(p, q, a) * orient(p, q, b) <= 0


def _inside(pt, ring) -> bool:
    x, y, hit = pt[0], pt[1], False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def _touches_land(coords, land) -> bool:
    lo = (min(c[0] for c in coords), min(c[1] for c in coords))
    hi = (max(c[0] for c in coords), max(c[1] for c in coords))
    for poly in land["coordinates"]:
        outer = poly[0]
        if (max(c[0] for c in outer) < lo[0] or min(c[0] for c in outer) > hi[0]
                or max(c[1] for c in outer) < lo[1] or min(c[1] for c in outer) > hi[1]):
            continue
        if any(_inside(p, outer) and not any(_inside(p, hole) for hole in poly[1:]) for p in coords):
            return True
        for ring in poly:
            for p, q in zip(coords, coords[1:]):
                if any(_cross(p, q, a, b) for a, b in zip(ring, ring[1:])):
                    return True
    return False


@pytest.mark.parametrize("geo", [GEO, HORMUZ_GEO], ids=["mandeb", "hormuz"])
def test_lanes_and_gate_are_clear_of_land(geo):
    for name, coords in geo["lanes"].items():
        assert not _touches_land(coords, geo["land"]), f"lane {name} touches land"
    assert not _touches_land(geo["gate"], geo["land"]), "gate touches land"


def test_the_land_check_would_catch_a_lane_through_perim():
    # Perim (Mayyun) sits in the strait at about 43.42E 12.65N; a line through it must fail.
    assert _touches_land([(43.30, 12.65), (43.55, 12.65)], GEO["land"])
    assert any(_inside((43.42, 12.652), poly[0]) for poly in GEO["land"]["coordinates"])


def test_gate_is_a_meridian_and_both_lanes_pass_through_it():
    (g_lon, lat_a), (g_lon2, lat_b) = GEO["gate"]
    assert g_lon == g_lon2   # the estimator and the map find crossings by the gate's meridian
    for d, lane in LANES.items():
        lons = [p[0] for p in GEO["lanes"][d]]
        assert all(b > a for a, b in zip(lons, lons[1:]))
        lon, lat = lane.at(lane.s_at_lon(g_lon))
        assert lon == pytest.approx(g_lon, abs=1e-9) and min(lat_a, lat_b) < lat < max(lat_a, lat_b)
    # Southbound (outbound) keeps to the west/south of the northbound lane at the gate.
    lat_out = LANES["outbound"].at(LANES["outbound"].s_at_lon(g_lon))[1]
    lat_in = LANES["inbound"].at(LANES["inbound"].s_at_lon(g_lon))[1]
    assert lat_out < lat_in


def test_map_has_the_strait_its_ports_and_its_own_scale():
    names = {p["name"] for p in GEO["places"]}
    assert {"Aden", "Djibouti", "Assab", "Mocha", "Perim (Mayyun)"} <= names
    b = GEO["bbox"]
    assert b[0] <= GEO["gate"][0][0] <= b[2] and b[1] <= GEO["gate"][0][1] <= b[3]
    assert GEO["lat0"] == pytest.approx(12.6)
    assert LANES["outbound"].lat0 == 12.6 and HORMUZ_LANES["outbound"].lat0 == 26.4


# --------------------------------------------------------------------------- estimator

def test_scenarios_cite_a_source_and_are_calibrated_on_average():
    for key, sc in sf.MANDEB_SCENARIOS.items():
        assert sc["source"] and sc["dark_basis"] and sc["split_basis"]
        truths = [sf.simulate(key, LANES, GEO["gate"], seed=s, strait="mandeb")["truth_mbd"] for s in range(30)]
        assert np.mean(truths) == pytest.approx(sc["flow_mbd"], rel=0.15)


@pytest.mark.parametrize("key", list(sf.MANDEB_SCENARIOS))
def test_estimator_recovers_the_synthetic_truth(key):
    hits, ratio = 0, []
    for seed in range(40):
        sim = sf.simulate(key, LANES, GEO["gate"], seed=seed, strait="mandeb")
        est = sf.estimate(sim, LANES, GEO["gate"], draws=400, strait="mandeb")
        t = est["total"]
        hits += t["p5"] <= sim["truth_mbd"] <= t["p95"]
        ratio.append(t["p50"] / sim["truth_mbd"])
        assert est["seen"]["p50"] <= sim["truth_mbd"] * 1.1   # AIS alone never over-counts much
    # The 90% range covers the truth in 35-40 of these 40 seeds; 32 leaves room for library changes.
    assert hits >= 32
    assert 0.85 < np.median(ratio) < 1.25


def test_both_directions_count_at_bab_el_mandeb_but_not_at_hormuz():
    sim = sf.simulate("pre2023", LANES, GEO["gate"], seed=10, strait="mandeb")
    north = {**sim, "ships": [v for v in sim["ships"] if v["lane"] == "inbound"]}
    assert sf.estimate(north, LANES, GEO["gate"], draws=200, strait="mandeb")["counts"]["seen_crossings"] > 0
    hz = sf.simulate("prewar", HORMUZ_LANES, HORMUZ_GEO["gate"], seed=7)
    hz_in = {**hz, "ships": [v for v in hz["ships"] if v["lane"] == "inbound"]}
    assert sf.estimate(hz_in, HORMUZ_LANES, HORMUZ_GEO["gate"], draws=200)["counts"]["seen_crossings"] == 0


def test_dark_ships_and_security_messages_appear_in_the_blockade_scenario():
    sim = sf.simulate("sep2026", LANES, GEO["gate"], seed=3, strait="mandeb")
    tankers = [v for v in sim["ships"] if v["kind"] == "tanker"]
    assert any(v["ais_mode"] in ("gap", "off") for v in tankers)
    calm = sf.simulate("pre2023", LANES, GEO["gate"], seed=3, strait="mandeb")
    msgs = lambda s: sum(v.get("destination") in sf.SECURITY_MSGS for v in s["ships"])
    assert msgs(sim) > 0 and msgs(calm) == 0


# --------------------------------------------------------------------------- outputs

def _keys(x):
    if isinstance(x, dict):
        return {k: _keys(v) for k, v in x.items() if k not in ("ships", "land")}
    return type(x).__name__ if not isinstance(x, (int, float)) or isinstance(x, bool) else "number"


def test_mandeb_bundle_has_the_same_shape_as_hormuz():
    hz = bundle("scenarios.js", "window.STRAIT = ")
    mb = bundle("mandeb-scenarios.js", "window.STRAITS.mandeb = ")
    assert (DATA / "mandeb-scenarios.js").read_text().startswith("window.STRAITS = window.STRAITS || {};\n")
    assert mb.keys() == hz.keys() == {"geo", "scenarios"}
    assert set(mb["geo"]) - set(hz["geo"]) == {"lat0"} and set(hz["geo"]) <= set(mb["geo"])
    one_hz, one_mb = next(iter(hz["scenarios"].values())), next(iter(mb["scenarios"].values()))
    assert _keys(one_mb) == _keys(one_hz)
    hz_ship_keys = {k for s in hz["scenarios"].values() for v in s["ships"] for k in v}
    assert {k for s in mb["scenarios"].values() for v in s["ships"] for k in v} <= hz_ship_keys
    assert mb["geo"] == GEO


def test_published_bundle_matches_the_code_and_each_truth_is_in_its_band():
    mb = bundle("mandeb-scenarios.js", "window.STRAITS.mandeb = ")
    assert list(mb["scenarios"]) == list(sf.MANDEB_SCENARIOS)
    for key, sc in mb["scenarios"].items():
        assert sc["synthetic"] is True and sc["published"] == sf.MANDEB_PUBLISHED
        t = sc["estimate"]["total"]
        assert t["p5"] <= sc["truth_mbd"] <= t["p95"]
        assert sc["truth_mbd"] == pytest.approx(sf.MANDEB_SCENARIOS[key]["flow_mbd"], rel=0.1)
        seed = sf.display_seed(key, LANES, GEO["gate"], "mandeb")
        sim = sf.simulate(key, LANES, GEO["gate"], seed=seed, strait="mandeb")
        assert sim["truth_mbd"] == sc["truth_mbd"]
        assert sf.estimate(sim, LANES, GEO["gate"], strait="mandeb")["total"] == t


def test_hormuz_output_is_unchanged_by_the_second_strait():
    hz = bundle("scenarios.js", "window.STRAIT = ")
    assert "lat0" not in hz["geo"] and hz["geo"] == HORMUZ_GEO
    for key, sc in hz["scenarios"].items():
        sim = sf.simulate(key, HORMUZ_LANES, HORMUZ_GEO["gate"])
        est = sf.estimate(sim, HORMUZ_LANES, HORMUZ_GEO["gate"])
        assert sim["truth_mbd"] == sc["truth_mbd"]
        assert est["total"] == sc["estimate"]["total"] and est["counts"] == sc["estimate"]["counts"]
