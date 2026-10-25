"""Strait view layout, applied after mandeb.SWAPS in build.py.

The industry page lays the Strait view out as a wrapping row. A wrapping row is as tall as its tallest item, so the
panel column on the right (about 1,900 px of cards) stretched the map to the same height and the map's centre, the
strait itself, opened below the fold. The World view avoids this with a single row; these rules give the Strait view
the same: the map fills the window and the panel column scrolls on its own. Narrow screens still stack the two.

The strait block also sized its canvas from the first .mapwrap on the page, which is the World view's, so it only
re-fitted when that map happened to change size (resizing the window in the Strait view left it stretched). It now
watches its own map.

Each entry is (old, new, count) like build.SWAPS: old must appear exactly count times.
"""

SWAPS = [
    ('const wrap = document.querySelector(".mapwrap");', 'const wrap = document.querySelector("#strait-stage .mapwrap");', 1),
]

CSS = """/* Strait view (strait.py): one row on wide screens, so the map fits the window and opens on the strait */
@media (min-width: 861px) {
  #strait-stage { flex-wrap: nowrap; }
  #strait-stage .hud { flex: 0 0 340px; min-height: 0; position: relative; }   /* relative: screen-reader labels stay inside the scroll */
}
"""
