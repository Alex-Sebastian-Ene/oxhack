# Hormuz Flow: the app

One page that holds everything: the World view (exposure map, flat or 3D globe, the five materials),
the Strait view (simulated ships, real IMF PortWatch counts) and the stats (Seb's chain, the Economy and Trends tabs).
It opens on a pixel-art landing page and keeps one night-shift theme throughout. Open `index.html` in a
browser; it needs no server and no network. `#app` at the end of the address skips the landing page.

The page is built from Eileen's integrated industry view (`ui/industry/index.html`), unchanged except
for the colours, with these layers added (`src/`):

| File | What it adds |
|---|---|
| `theme.css` | The night-shift theme for every view: steel panels with rivets, chunky keys, a pipe-and-valve slider, Pixelify Sans and VT323 type |
| `landing.html`, `landing.css`, `landing.js` | The landing page: three headline numbers with their sources, sound, and "Open the valve" |
| `pixel.js` | The landing scene, drawn in code as pixel art: refinery, flare, tankers (one running dark), water, the pipeline and its valve |
| `sound.js` | Sound, all synthesised in the browser: "Night Shift" (an original chiptune loop), harbour ambience and interface sounds |
| `shell.js` | The pipe strip under the header (its oil runs at the share of Hormuz flow getting through), the home, sound and music keys |
| `ai.js`, `ai.css` | Sources (every material and ingredient with its datasets) and country Profiles, each with an optional Gemini panel |
| `build.py` | Puts it together; each colour swap in Eileen's page must match exactly, so the build stops if her page changes |
| `world.py` | World view: Made and Shipped together (front layer fills, back layer stands as columns, faint arcs), flags in every tooltip |
| `copy_text.py` | Shorter copy for the panels; same facts and sources |

```bash
python ui/app/src/build.py                      # writes ui/app/index.html
python ui/app/src/build.py --fragment out.html  # also writes the body for a claude.ai artifact
```

## Sound and pictures

- No recordings are used, so nothing needs a licence:
  - The music, "Night Shift", is an original 16-bar loop in A minor, written for this app.
  - The water, plant hum, steam, clanks and ship's horn are made from oscillators and filtered noise.
- Browsers only allow sound after a click or key press. Sound and music each have a key in the header,
  and the page remembers both choices.
- The lost-flow slider makes the harbour tenser: the lead darkens and the plant hums louder.
- All pixel art is drawn in code; there are no image files.

## Gemini panels (optional)

- **What is it?** In Sources, every material and ingredient has a button that asks Gemini for:
  - a short description;
  - a pixel-art picture in the app's style, made by Gemini's image model.
- **Profile.** In a country's pop-up and panel:
  - its main export and biggest production role in our tables;
  - its rank in every production and export table we hold;
  - its exposure numbers and where its key inputs come from.

  "Summarise with Gemini" writes a few lines from those facts only. Each number in the summary cites the
  fact it came from, and a reference to a fact that doesn't exist is flagged.
- **Labelling.** Both answers are labelled AI-written, with the model and time. They never feed the maps
  or the numbers.
- **The service.** Both call the local service in `experiments/country_brief.py`, at
  `http://127.0.0.1:8787` (or `?ai=<url>`). It needs `GEMINI_API_KEY` in the environment or in the repo's
  `.env` (git-ignored). `BRIEF_FAKE=1` serves labelled test answers for UI work. Details:
  `docs/country-briefs.md`.

## Bundled third-party code

- Inherited from the industry page:
  - globe.gl 2.41.4 (MIT);
  - flag-icons 7.6.0 (MIT);
  - Natural Earth (public domain).
- Bundled by this build, instead of loading from cdnjs:
  - d3 7.9.0 (ISC);
  - topojson 3.0.2 (BSD-3-Clause).
- Fonts: Pixelify Sans and VT323 (SIL Open Font License 1.1).
- Licences are in `vendor/`.
