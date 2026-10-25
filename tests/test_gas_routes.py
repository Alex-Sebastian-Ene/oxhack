"""ui/app/data/gas.json: LNG through Hormuz and the Gulf gas pipelines (experiments/gas_routes.py)."""

import copy
import json
from pathlib import Path

import gas_routes as gr

DATA = json.loads((Path(__file__).resolve().parent.parent / "ui" / "app" / "data" / "gas.json").read_text())


def points(data):
    """Every [lng, lat] in the file, with where it came from."""
    for f in data["lng"]:
        for key in ("route", "alt_route"):
            if key in f:
                for p in f[key]["path"] + f[key]["end"] + [f[key]["start"]]:
                    yield f"{f['from']}->{f['to']} {key}", p
    for p in data["pipelines"]:
        for q in p["path"] + p.get("planned_path", []):
            yield p["name"], q
    for name, pts in data["segments"].items():
        for q in pts:
            yield f"segment {name}", q
    for t in data["terminals"].values():
        yield t["name"], t["at"]
    for o in data["outside_strait"]:
        yield o["name"], o["at"]


def test_file_passes_the_script_validator():
    assert gr.validate(DATA) == []


def test_file_is_what_the_script_builds():
    assert DATA == gr.build(today=DATA["generated"])


def test_iso_list_is_the_full_iso_3166_alpha3_set():
    assert len(gr.ISO3) == 249 and all(len(c) == 3 and c.isalpha() and c.isupper() for c in gr.ISO3)
    assert {"QAT", "ARE", "CHN", "IND", "KOR", "TWN", "PAK", "OMN", "IRN", "IRQ", "TUR"} <= gr.ISO3
    assert not {"UAE", "UK", "XXX", "TAI"} & gr.ISO3


def test_every_country_code_is_iso3():
    codes = [c for f in DATA["lng"] for c in (f["from"], f["to"])]
    codes += [c for p in DATA["pipelines"] for c in (p["from"], p["to"])]
    codes += [o["iso3"] for o in DATA["outside_strait"]] + list(DATA["terminals"])
    assert codes and all(c in gr.ISO3 for c in codes), [c for c in codes if c not in gr.ISO3]


def test_every_value_has_a_source_url_year_and_flags():
    records = DATA["lng"] + DATA["pipelines"] + DATA["facts"]
    for r in records:
        value = r.get("value", r.get("capacity"))
        assert isinstance(value, (int, float)) and value > 0, r
        assert r["source"].strip() and r["url"].startswith("https://"), r
        assert isinstance(r["year"], int) and 2000 <= r["year"] <= 2026, r
        assert r["verify"] is True and isinstance(r["approx"], bool), r
    for f in DATA["lng"]:
        assert f["unit"] == "Mt" and f["via"] == "hormuz"
        assert f["from"] in ("QAT", "ARE")
        if "y2024" in f:
            assert f["y2024"]["value"] > 0 and f["y2024"]["url"].startswith("https://")


def test_every_point_is_a_valid_lng_lat():
    pts = list(points(DATA))
    assert len(pts) > 200
    bad = [(w, p) for w, p in pts if not gr._point_ok(p)]
    assert bad == []


def test_routes_start_at_the_terminal_and_pass_the_strait():
    for f in DATA["lng"]:
        r = f["route"]
        assert r["start"] == DATA["terminals"][f["from"]]["at"]
        assert r["segments"][0] == "gulf" and set(r["segments"]) <= set(gr.SEGMENTS)
        assert r["path"] == gr.expand(r["start"], r["segments"], r["end"])
        assert DATA["segments"]["gulf"][0] in r["path"]  # the Hormuz waypoint


def test_europe_flows_go_by_suez_with_the_cape_as_alternative():
    europe = {"ITA", "BEL", "POL", "GBR", "ESP", "FRA"}
    for f in DATA["lng"]:
        if f["to"] in europe:
            assert "red" in f["route"]["segments"]
            assert f["alt_route"]["segments"] == ["gulf", "cape"] and f["alt_route"]["url"].startswith("https://")
        else:
            assert "alt_route" not in f


def test_pipelines_have_paths_status_and_a_common_capacity_scale():
    names = {p["name"] for p in DATA["pipelines"]}
    assert any("Dolphin" in n for n in names) and any("Tabriz" in n for n in names)
    assert any("Iraq" in n for n in names)
    for p in DATA["pipelines"]:
        assert len(p["path"]) >= 2 and p["status"].strip() and isinstance(p["bypasses_hormuz"], bool)
        assert p["unit"] in gr.TO_BCM_Y and p["capacity_bcm_y"] > 0
    dolphin = next(p for p in DATA["pipelines"] if p["name"].startswith("Dolphin (Ras Laffan"))
    assert abs(dolphin["capacity_bcm_y"] - 33.1) < 0.1  # 3.2 bcf/d


def test_validator_catches_bad_codes_points_and_missing_sources():
    bad = copy.deepcopy(DATA)
    bad["lng"][0]["to"] = "UAE"
    bad["lng"][1]["url"] = ""
    bad["lng"][2]["route"]["end"][0] = [200, 10]
    bad["pipelines"][0]["path"][1] = [25.5, 52.4]   # lng/lat swapped makes a long jump
    bad["facts"][0]["source"] = " "
    errs = "\n".join(gr.validate(bad))
    assert "not an ISO 3166-1 alpha-3 code" in errs
    assert "url must start with https://" in errs
    assert "bad lng/lat [200, 10]" in errs
    assert "jump of" in errs
    assert "missing source" in errs
