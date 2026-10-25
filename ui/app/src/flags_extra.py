"""Flags the industry page leaves out, for ui/app/data/flags-extra.json.

experiments/globe_flags.py skips flags whose drawings are heavy (coats of arms, 10-180 KB each), so countries
like Spain, Sri Lanka and Serbia show a letter code. The app wants a flag beside every country name, so this
draws each missing one from the same flag-icons 7.6.0 package (MIT; licence in ui/globe/vendor/) at 96x72 px in
Chromium and stores it as a small PNG. Run it again when the industry page's countries change:

    uv run experiments/globe_flags.py   # first, if data/raw/flag-icons-7.6.0.tgz is missing
    python3 ui/app/src/flags_extra.py   # needs node with Playwright's Chromium
"""
import base64
import json
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "experiments"))
import globe_flags  # noqa: E402  (the tarball, its version and the ISO3 -> ISO2 table)

PAGE = ROOT / "ui" / "industry" / "index.html"
OUT = ROOT / "ui" / "app" / "data" / "flags-extra.json"
W, H = 96, 72

RENDER = r"""
const { chromium } = require("playwright");
const files = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8"));
(async () => {
  const b = await chromium.launch(), p = await b.newPage({ deviceScaleFactor: 1 });
  const out = {};
  for (const [iso, src] of Object.entries(files)) {
    await p.setContent(`<body style="margin:0"><img id="f" src="${src}" style="display:block;width:%(W)spx;height:%(H)spx"></body>`);
    await p.waitForFunction(() => document.getElementById("f").complete);
    out[iso] = (await (await p.$("#f")).screenshot({ type: "png" })).toString("base64");
  }
  await b.close();
  process.stdout.write(JSON.stringify(out));
})();
""" % {"W": W, "H": H}


def page_json(name: str):
    s = PAGE.read_text(encoding="utf-8")
    i = s.index(f"window.{name} = ") + len(f"window.{name} = ")
    return json.JSONDecoder().raw_decode(s[i:s.index("\n", i)])[0]


def main() -> None:
    have = page_json("FLAGS")["flags"]
    cn = page_json("COUNTRIES")
    isos = {f["properties"]["iso3"] for f in cn["features"]} | set(cn["points"])
    codes = globe_flags.iso2_by_iso3()
    svgs, none = {}, []
    with tarfile.open(globe_flags.TARBALL) as tar:
        files = {m.name: m for m in tar.getmembers() if m.isfile()}
        for iso in sorted(isos - set(have)):
            m = files.get(f"package/flags/4x3/{codes.get(iso)}.svg")
            if not m:
                none.append(iso)
                continue
            svgs[iso] = "data:image/svg+xml," + urllib.parse.quote(globe_flags.minify(tar.extractfile(m).read().decode()))
    with tempfile.TemporaryDirectory() as d:
        src = pathlib.Path(d) / "svgs.json"
        src.write_text(json.dumps(svgs))
        r = subprocess.run(["node", "-e", RENDER, str(src)], capture_output=True, text=True, check=True)
    pngs = json.loads(r.stdout)
    flags = {iso: "data:image/png;base64," + pngs[iso] for iso in sorted(pngs)}
    OUT.write_text(json.dumps({"source": f"flag-icons {globe_flags.VERSION} (MIT), drawn at {W}x{H} px by ui/app/src/flags_extra.py",
                               "flags": flags}, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(flags)} flags, {OUT.stat().st_size // 1024} KB; no flag in the package: {none or 'none'}")


if __name__ == "__main__":
    main()
