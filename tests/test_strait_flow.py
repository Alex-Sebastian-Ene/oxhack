"""experiments/strait_flow.py: identity checks, ghost score, geometry and the flow estimator."""

import json
from pathlib import Path

import pytest

import strait_flow as sf

GEO = json.loads((Path(__file__).resolve().parent.parent / "ui" / "strait" / "data" / "geo.json").read_text())
LANES = sf.load_lanes(GEO)


def test_imo_check_digit_accepts_real_numbers_and_rejects_typos():
    # Macho Queen and the scrapped Pedrot, whose identity it reused (Lloyd's List, 2026).
    assert sf.imo_valid("9238868") and sf.imo_valid("IMO 9177686")
    assert not sf.imo_valid("9238869") and not sf.imo_valid("923886") and not sf.imo_valid(None)
    assert sf.imo_valid(sf.imo_with_check(123456))


def test_mmsi_flag_reads_the_maritime_identification_digits():
    assert sf.mmsi_flag("422123456") == "Iran"
    assert sf.mmsi_flag(538000001) == "Marshall Islands"
    assert sf.mmsi_flag("12345") is None and sf.mmsi_flag("999123456") is None


def test_ghost_score_rises_with_each_indicator_and_explains_itself():
    clean = {"imo": sf.imo_with_check(111111), "mmsi": "636000001", "flag": "Liberia",
             "built": 2020, "destination": "SINGAPORE", "ais_mode": "on", "sar_hits": []}
    base = sf.ghost_score(clean)
    assert base["score"] < 0.2 and base["reasons"] == []
    dark = sf.ghost_score({**clean, "ais_mode": "off", "sar_hits": [{"pass": 0}], "sanctioned": True})
    assert dark["score"] > 0.9 and len(dark["reasons"]) == 2
    mismatch = sf.ghost_score({**clean, "flag": "Panama"})   # MMSI says Liberia
    assert mismatch["score"] > base["score"]
    assert any("MMSI" in r for r in mismatch["reasons"])


def test_lanes_follow_their_waypoints_and_reach_the_gate():
    out = LANES["outbound"]
    assert out.at(0) == pytest.approx(out.points[0])
    assert out.at(out.length) == pytest.approx(out.points[-1])
    s = out.s_at_lon(GEO["gate"][0][0])
    assert out.at(s)[0] == pytest.approx(GEO["gate"][0][0], abs=1e-6)
    lon, lat = out.at(s)
    assert GEO["gate"][0][1] < lat < GEO["gate"][1][1]   # the lane passes through the gate


def test_gate_crossing_and_spoof_filter():
    gate = GEO["gate"]
    assert sf.crosses_gate((56.3, 26.5), (56.5, 26.5), gate)
    assert not sf.crosses_gate((56.3, 26.5), (56.4, 26.5), gate)
    assert not sf.crosses_gate((56.3, 26.9), (56.5, 26.9), gate)   # north of the gate
    track = [(0.0, 56.0, 26.5), (1 / 6, 56.04, 26.5), (2 / 6, 56.5, 27.3), (3 / 6, 56.08, 26.5)]
    kept, dropped = sf.clean_track(track)
    assert dropped == 1 and kept[-1] == track[-1]


@pytest.mark.parametrize("key", list(sf.SCENARIOS))
def test_estimator_recovers_the_synthetic_truth(key):
    hits = 0
    for seed in range(6):
        sim = sf.simulate(key, LANES, GEO["gate"], seed=seed)
        est = sf.estimate(sim, LANES, GEO["gate"], draws=400)
        t = est["total"]
        hits += t["p5"] <= sim["truth_mbd"] <= t["p95"]
        assert est["seen"]["p50"] <= sim["truth_mbd"] * 1.1   # AIS alone never over-counts much
    assert hits >= 5   # the 90% range should cover the truth almost every time


def test_dark_ships_raise_the_estimate_above_what_ais_sees():
    sim = sf.simulate("aug2026", LANES, GEO["gate"], seed=3)
    est = sf.estimate(sim, LANES, GEO["gate"], draws=400)
    assert est["total"]["p50"] > est["seen"]["p50"] * 1.5
    assert est["global"]["share_of_world_p50"] == pytest.approx(est["total"]["p50"] / sf.WORLD_CONSUMPTION_MBD, abs=1e-3)


def test_real_observation_rows_feed_the_same_estimator():
    from datetime import UTC, datetime, timedelta

    import strait_sources as ss

    sim = sf.simulate("aug2026", LANES, GEO["gate"], seed=5)
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    at = lambda h: t0 + timedelta(hours=h)
    ais = [{"mmsi": v["mmsi"], "time": at(t), "lon": lon, "lat": lat, "draught_m": v["draught_m"],
            "length_m": v["length_m"], "ship_type": 80}
           for v in sim["ships"] if v["kind"] == "tanker" for t, lon, lat in v["ais"]]
    passes = [at(h) for h in sim["sar_passes_h"]]
    sar = [{"time": passes[h["pass"]], "lon": h["lon"], "lat": h["lat"], "length_m": h["length_m"],
            "matched": v["ais_mode"] != "off"}
           for v in sim["ships"] for h in v["sar_hits"]]
    real = ss.observations_to_sim(ais, sar, t0, LANES, sf.WINDOW_H, sar_passes=passes)
    assert real["synthetic"] is False
    a = sf.estimate(sim, LANES, GEO["gate"], draws=300)
    b = sf.estimate(real, LANES, GEO["gate"], draws=300)
    assert b["counts"]["seen_crossings"] == a["counts"]["seen_crossings"]
    assert b["total"]["p50"] == pytest.approx(a["total"]["p50"], rel=0.35)
