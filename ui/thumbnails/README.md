# Thumbnails

Cover images for Hormuz Flow, in the app's night-shift pixel style. Everything is drawn in code, so it can be
rebuilt. Fonts: Pixelify Sans and VT323 (SIL Open Font License, `ui/app/vendor/fonts`).

## `globe/`: the stills (1920×1080, plus the classic at 3:2; title and pictures only)

| File | Picture |
|---|---|
| `still-1-classic.png` | Title on the left; a lit globe on the right, with oil and LNG arcs from Hormuz landing on East Asia's night side |
| `still-2-horizon.png` | Low orbit over the Gulf: a glowing horizon, Hormuz on the night side, arcs launching over the limb |
| `still-3-knockon.png` | The globe, with three streams from Hormuz running into pixel icons for crude, fuel and prices |
| `still-4-control.png` | The globe on a CRT in a steel wall, fed by an oil pipe and an LNG pipe, with a gauge and a valve wheel |
| `still-5-classic-3x2.png` | The classic at 3:2 (1920×1280), the globe enlarged to fill the taller frame |
| `still-6-logo-plain.png` to `still-9-logo-wake.png` | The 3:2 classic with the app's pixel tanker logo under the title: plain, on a strip of sea, on a riveted plate, and trailing an oil wake (`logo-contact-sheet.png`) |
| `still-10-sea-blue.png`, `still-11-sea-gold.png` | The title in the pour lettering, a big tanker logo on the horizon, and a pixel sea that mirrors the globe with a glitter path: night blue, and glowing gold with the tanker as a silhouette (`sea-contact-sheet.png`) |
| `still-12-set-blue.png`, `still-13-set-gold.png` | The same, with a bigger globe sinking into the sea like a setting sun |
| `still-14-logo-blue.png` to `still-17-logo-gold-glow.png` | The 3:2 classic with the pour lettering (a hand-drawn pixel Z) and the tanker logo on its own strip of pixel water on the ship's grid: blue, gold, and each with a glow (`logo-sea-contact-sheet.png`) |
| `still-18-logo-blue-centred.png` | The blue logo centred under the title |
| `still-19-logo-blue-lit.png` | The chosen one: 18 with the countries the rays end in picked out in copper (oil buyers) and violet (LNG-only buyers), matched by name; Singapore has no polygon at this scale and stays unlit |
| `still-20-logo-blue-lit-bright.png` | The same with the buyers lit brightly |
| `still-21-colours-subtle.png`, `still-22-colours-bright.png` | Each buyer in its own colour (`BUYER` in `kit.js`), subtle and bright; rays keep their oil and LNG colours (`colours-contact-sheet.png`) |
| `still-23-matched-subtle.png`, `still-24-matched-bright.png` | The same, with each ray taking its buyer's colour |
| `still-25-exposure-subtle.png`, `still-26-exposure-bright.png` | Buyers coloured teal to red by the share of their oil that came via Hormuz before the war (`h / c` from `ui/industry`; teal at 15% or less, red at 60% or more) |

Arc widths come from the repo's own tables. Oil is pre-war kb/d via Hormuz by destination (`ui/industry`,
EIA 2024). LNG is Mt/yr from `ui/app/data/gas.json`; those figures come from search results and are unverified.
No numbers appear on the images.

```
cd ui/thumbnails/globe
python3 flows.py     # data.js from the repo's tables
python3 make.py      # one HTML page per still (d3, countries, fonts inlined)
node capture.js      # still-N-*.png at 1920x1080 (Playwright)
```

`kit.js` holds the shared pieces:
- the pixel globe, drawn at 480×270 and scaled ×4: lit by a light direction, land and sea snapped to two ramps;
- atmosphere and city lights;
- arcs lifted off the surface, each with a bright pulse heading to the buyer;
- a soft glow on the bright layers.

## `first-round/`: the eight earlier versions (1280×720 PNG and 640×360 GIF)

These are skyline, radar, pour, globe, gauge, arcade, spike and maze. `contact-sheet.png` shows all eight.

```
cd ui/thumbnails/first-round
python3 make.py && node capture.js --gif && python3 finish.py
```
