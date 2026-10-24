# Runs after patch_strait.py on hormuz-flow.html.
# Steel and aluminium get Seb's OXH-5 oil links (notes/steel-aluminium-responses.csv, branch claude/upbeat-jones-ba5f1a,
# commit e0d122f). Linear links: a +10% Brent move gives the mean below after 12 months, a -10% move the mirror image.
# The band is mean ± 1.645 standard errors, the 90% interval of the average effect, same as the other products.
import pathlib, subprocess

here = pathlib.Path(__file__).parent
p = here / "hormuz-flow.html"
s = p.read_text(encoding="utf-8")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} of {old[:80]!r}, found {n}"
    s = s.replace(old, new)


SRC = ("Seb's linear oil link, notes/steel-aluminium-responses.csv on claude/upbeat-jones-ba5f1a, commit e0d122f "
       "(experiments/metal_links.py; FRED monthly 2001-2026, fetched 2026-10-24)")
METALS = {
    # series, mean, SE (12 months, per +10% Brent), mean and SE with world demand held fixed, what happened in the 2026 closure
    "steel": ("FRED WPU1017 (US PPI steel mill products)", 3.7, 1.0, 2.3, 0.9, "+27.6%", "+16.9%"),
    "aluminium": ("FRED WPU102501 (US PPI aluminium mill shapes)", 2.0, 0.5, 1.4, 0.6, "+25.2%", "+7.7%"),
}
js = []
for mid, (series, mu, se, mu_d, se_d, actual, link) in METALS.items():
    lo, hi = round(mu - 1.645 * se, 2), round(mu + 1.645 * se, 2)
    js.append(
        f'  if (mats.{mid}) mats.{mid}.oil = {{ up: [{mu}, {lo}, {hi}], down: [{-mu}, {-hi}, {-lo}], series: "{series}", validated: true, '
        f'horizon: "12 months", linear: true, source: "{SRC}", '
        f'extra: "Upper end for a supply shock: with world demand held fixed the link is +{mu_d} ± {se_d} per 10% Brent. '
        f'Average historical pass-through, not a forecast: in the 2026 closure the price rose {actual} against {link} from the link." }};')
sub("  const mats = Object.fromEntries(MAT.materials.map((m) => [m.id, m]));",
    "  const mats = Object.fromEntries(MAT.materials.map((m) => [m.id, m]));\n"
    "  // steel and aluminium: Seb's OXH-5 links (US prices of mill products, not world crude steel or primary aluminium)\n"
    + "\n".join(js))
# the product card shows the caveat after the series name
sub("${m.oil.series}.`", "${m.oil.series}.${m.oil.extra ? ` ${m.oil.extra}` : \"\"}`")
# the info sheet says where the metal numbers come from
sub("Steel and aluminium have no fitted link yet (OXH-5).",
    "Steel and aluminium use Seb's linear links instead (OXH-5, <code>notes/steel-aluminium-responses.csv</code>): US PPI steel mill products +3.7 ± 1.0 and aluminium mill shapes +2.0 ± 0.5 after 12 months per 10% Brent, the same size up or down; validated in 7/8 and 8/8 forward folds. These are US mill-product prices and the upper end for a supply shock.")

p.write_text(s, encoding="utf-8")
print("written", len(s.encode()))
for marker in ["// Hormuz Flow: zoomable", "// World view: where Hormuz oil goes"]:
    x = s.index(marker); y = s.index("</script>", x)
    (here / "chk.js").write_text(s[x:y], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(here / "chk.js")], capture_output=True, text=True)
    print(marker[:30], "ok" if r.returncode == 0 else r.stderr)
