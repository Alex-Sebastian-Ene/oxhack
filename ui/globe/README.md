# Materials Globe

3D globe: who makes and ships steel, jet fuel, aluminium, nitrogen fertiliser and polyethylene, where each
producer's ingredients come from, and how a Brent move feeds through to prices. Open
`index.html` in a browser (works offline). Why and how: `docs/materials-globe.md`.

| File | Made by |
|---|---|
| `data/countries.js` | `uv run experiments/globe_geo.py` (Natural Earth 1:110m) |
| `data/materials.js` | `uv run experiments/globe_data.py` (from `notes/materials/*.json`) |
| `data/flags.js` | `uv run experiments/globe_flags.py` (flag-icons 7.6.0, MIT, see `vendor/flag-icons.LICENSE`) |
| `vendor/globe.gl.min.js` | globe.gl 2.41.4 (MIT, see `vendor/globe.gl.LICENSE`) |
| `index.html`, `style.css`, `app.js` | by hand |
