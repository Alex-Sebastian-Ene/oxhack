# Hormuz Flow: the app

One page that holds everything: the World view (exposure map, flat or 3D globe, the five materials),
the Strait view (simulated ships, real IMF PortWatch counts), the stats (Seb's chain, the Economy and Trends tabs)
the Households view (Seb's household cost-of-living data) and the Models view (what each of Seb's models does and how
it was tested). It opens on a pixel-art landing page and keeps one night-shift theme throughout. Open `index.html` in
a browser; it needs no server and no network. `#app`, `#mandeb`, `#households` or `#models` at the end of the address
skips the landing page.

The page is built from Eileen's integrated industry view (`ui/industry/index.html`), unchanged except
for the colours, with these layers added (`src/`):

| File | What it adds |
|---|---|
| `theme.css` | The night-shift theme for every view: steel panels with rivets, chunky keys, a pipe-and-valve slider, Pixelify Sans and VT323 type |
| `landing.html`, `landing.css`, `landing.js` | The landing page: three headline numbers with their sources, sound, and "Open the valve" |
| `pixel.js` | The landing scene, drawn in code as pixel art: refinery, flare, tankers (one running dark), water, the pipeline and its valve |
| `sound.js` | Sound, all synthesised in the browser: "Night Shift" (an original chiptune loop), harbour ambience and interface sounds |
| `shell.js` | The pipe strip under the header (its oil runs at the share of Hormuz flow getting through), the home, sound and music keys |
| `ai.js`, `ai.css` | Sources (every material and ingredient with its datasets) and country Profiles, each with an optional Gemini panel; answers written ahead come from `data/ai-panels.json` (`ai_facts.cjs` reads the facts each panel sends) |
| `info.css` | The blue info keys on every view (World, Strait, Households, Models), and the info panel's sections and source rows |
| `infokey.js` | One behaviour for every info key: the panel opens beside its key (below, above or to the side, inside the window; a bottom sheet on phones), the same key closes it again, and ×, Escape or a click outside close it and return focus to the key |
| `strait.py`, `strait.js` | Strait view: the map fits the window and opens on the strait; each card's dates and notes move into its info panel |
| `build.py` | Puts it together; each colour swap in Eileen's page must match exactly, so the build stops if her page changes |
| `world.py` | World view: Made and Shipped together (front layer fills, back layer stands as columns, faint arcs), flags in every tooltip |
| `copy_text.py` | Shorter copy for the panels; same facts and sources |
| `gas.py` | Gas on the World view: LNG lanes (dashed violet, beside the oil lanes) and pipelines, from `ui/app/data/gas.json` (`uv run experiments/gas_routes.py`) |
| `mandeb.py`, `mandeb.js` | Bab el-Mandeb in the Strait view: the Hormuz / Bab el-Mandeb switch reloads on `#mandeb`; data from `ui/strait/data/mandeb-scenarios.js` (`uv run experiments/strait_flow.py --strait mandeb`) |
| `households.py`, `households.js` | The Households view (OXH-8): real pay against 2019 by region, essentials against pay, UK household costs by group, and two model-output cards (real pay by lost flow, each UK group's costs under a closure) that follow the lost-flow slider; also a households step in "The shock" card. Data cut at build time from `notes/household-*.csv` (`uv run experiments/household.py report`); every real series shows its source, code and fetch date |
| `models.py`, `models.js`, `models.css` | The Models view: one card per model (oil-price distribution, lost flow → Brent, the knock-on links, the Bayesian and global network models with their Fed and SPF comparison, cost of living, industries by country, margins, metals, the first neural ensemble, HDI, the independent check), each with what it answers and two to four headline numbers on the card; how it was tested, what it can't do and each number's context sit behind the card's blue info key. The numbers are read at build time from `notes/` and `docs/` by table cell or phrase, each shown with its note and the date that note was generated; a card whose numbers can't be found is left out with a warning (`python ui/app/src/models.py` lists them) |
| `flags.py`, `flags_extra.py` | A flag beside every country title (Most exposed, the country card, the economy picks). `flags_extra.py` draws the flags the page leaves out for size (Spain, Sri Lanka and 20 more) into `ui/app/data/flags-extra.json`; the EU flag stands for the euro area |

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
- **Written ahead (baked).** Answers written ahead of time are built into the page from
  `ui/app/data/ai-panels.json`, so the panels work offline and in the claude.ai artifact. Each shows
  "AI-written by Gemini", the model and the date it was written. A country summary also says it was written at
  the 2026-closure setting, and warns when your setting differs. To refresh them:

  ```bash
  python3 ui/app/src/build.py && node ui/app/src/ai_facts.cjs   # the facts each panel sends, at the 2026 closure
  uv run experiments/country_brief.py bake                      # Gemini answers -> ui/app/data/ai-panels.json
  python3 ui/app/src/build.py                                   # bake them into the page
  ```

  `bake` keeps any answer whose facts haven't changed, and asks about the countries we hold most facts on
  first. It stops cleanly when the key's daily quota runs out (20 requests per model on the free tier) and
  lists what is still missing, so run it again the next day, or with another `GEMINI_MODEL`. Pictures are
  not baked, since they would add megabytes to the page.
- **The service.** Anything not baked calls the local service in `experiments/country_brief.py`, at
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
