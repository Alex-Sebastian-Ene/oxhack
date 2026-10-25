# Country briefs: more on a country, with an optional AI write-up

Written 24 Oct 2026. Code: `ui/globe/app.js` (country sheet), `experiments/country_brief.py` (AI proxy),
`tests/test_country_brief.py`.

## What it does

Click a country on the materials globe, then **More**. A sheet opens with:

1. **Everything our tables hold on that country.** For each material where it appears:
   - its share of world output or exports, and its rank among the countries listed;
   - where its ingredients come from, and which countries it supplies;
   - the trade flows to and from it.

   Every row is from `notes/materials/` and cites its source and year. Tapping a partner flag jumps to
   that country.
2. **An AI brief (optional, off by default).** One button asks Gemini for 4 to 6 bullet points on the
   country's role in that material. The brief covers what it makes, imports and exports, how much it
   depends on Hormuz and oil prices, and what changed in 2026. Gemini gets our sourced rows as the
   facts to start from, and uses Google Search grounding for anything else. The cited pages are shown
   under the text.

## In the app (ui/app)

The same service also answers two more requests from `ui/app/index.html`. They use Gemini's newer
Interactions API (`POST /v1beta/interactions`).
- **`/resource`: "What is it?"**, from the Sources key in the app's header.
  - A short description of a material or ingredient (steel, naphtha, urea and so on). It explains what
    the thing is, what it is used for and why oil matters to it. Any number must come from our facts,
    cited as [n].
  - A pixel-art picture in the app's night-shift style, from the image model (`GEMINI_IMAGE_MODEL`,
    default `gemini-nano-banana-2.1`, per Google's gemini-api-dev skill).
  - The picture is captioned "AI-made picture", and the text carries the model name and time.
- **`/country`: Profile.**
  - The page builds the facts itself: main export and production role, its rank in every table we hold,
    exposure score, fuel cost, Hormuz share, and key input origins.
  - Gemini only turns them into a few lines. Every number must cite its fact. A citation to a fact that
    doesn't exist shows as `[n?]`.
- **Test mode.** `BRIEF_FAKE=1` answers both with clearly labelled test text and a striped test picture,
  so the panels can be tried without a key.
- **Written ahead.** `uv run experiments/country_brief.py bake` writes both panels ahead of time for
  every resource and every country, from the facts `node ui/app/src/ai_facts.cjs` reads off the built
  app at the 2026-closure setting. They go into `ui/app/data/ai-panels.json`, which the app build puts in the
  page. Each panel names the model that wrote it, as Gemini's response names it.
- **The bake of 25 Oct 2026** (free-tier key) covers every panel: the 16 resources and the 175 countries
  you can select on the World map, at the 2026-closure setting (Hong Kong, Malta, Mauritius, Northern Cyprus,
  Somaliland, Antarctica and the French Southern Lands have no shape to click, so no summary).
  - The free tier allows 20 requests a day for each full-size flash model; `gemini-3.5-flash-lite` allowed 15 a
    minute and was not used up by about 200. Requests to `gemini-3.5-flash` counted against
    `gemini-3.6-flash`'s quota, and `gemini-3.7-flash` and `gemini-flash-latest` against `gemini-3.8-flash`'s.
    The pro models have no free quota (limit 0). `gemini-3.8-flash` also returned "high demand" errors and
    120 s timeouts.
  - Resources: all 16 from `gemini-3.5-flash`, written before `bake` recorded the model that answered, so they
    name the model asked for (Google may have served them from `gemini-3.6-flash`, whose quota they used).
  - Countries: main's new country data (fuel pass-through, partner-reported oil trade and IMF cost of living,
    merged the same morning) changed every country's facts, so all 175 were asked again after the flash
    models' quotas had run out: 146 are from `gemini-3.5-flash-lite` and 29 from `gemini-3.1-flash-lite`. Answers
    `gemini-3.5-flash-lite` gave too thinly (two bullets, or a doubled dash) were dropped and asked again of
    `gemini-3.1-flash-lite`, as were Lebanon and Suriname (each has one fact over 400 characters, which `bake`
    failed to match until it compared the facts as cut). The 9 countries whose fuel cost changed in #71 were
    asked again after it merged, and the 164 whose cost-of-living forecasts changed with Seb's cross-country model
    after that; the counts above are after both. El Salvador keeps a two-line answer: its facts hold little beyond
    its oil imports. To replace any answer with a stronger model's, delete its entry from
    `ai-panels.json` and run `bake` with that `GEMINI_MODEL` on a day its quota is free.
  - Pictures: `bake --images` asks `IMAGE_MODEL` for each resource's picture. On 25 Oct 2026 every image model
    this key lists (`gemini-nano-banana-2.1`, `gemini-3-pro-image`, `gemini-3.1-flash-image`,
    `gemini-3.1-flash-lite-image` and their previews) answered HTTP 429 with a free-tier limit of 0, so no picture is
    baked; `bake` stops at the first such answer instead of waiting. A key with billing fills them in on a rerun.
  - Checked: every `[n]` points to a fact that exists; spot checks of the US, Netherlands and Iran summaries against
    their facts found no wrong numbers. Not checked line by line by the team, and each panel says so.

## Why an LLM, and why Gemini

- **Coverage.** Our tables cover about 40 countries and five materials. A judge will click a country
  we have little on, and a grounded brief fills that gap in seconds.
- **Grounding with citations.** Gemini's Google Search tool returns the pages it used
  (`groundingMetadata`). That fits our rule that every number says where it came from.
- **Cost and setup.** One API key and a few lines of standard-library Python. No SDK and no new
  dependency.

## Rules it keeps (AGENTS.md ground rules)

- **The key stays in an environment variable** (`GEMINI_API_KEY`) on the laptop that runs the
  proxy. It is never put in the page, git or Linear: the repo is public.
- **The page never calls Google directly.** It posts to `http://127.0.0.1:8787/brief`. That service
  listens on localhost only, and answers only pages opened from disk or from localhost, so another
  website cannot spend the key.
- **AI text is labelled as AI text.** Each brief carries the model name, when it was written, and
  "Not checked by the team: verify before quoting". It never goes into the sourced tables, the
  globe colours or the price numbers.
- **Cached is never shown as live.** Answers are cached in `data/raw/briefs/` (git-ignored) so the
  demo works on bad Wi-Fi. A cached answer says "cached, written <date>".
- **Prompt rules:** a year with every number; mark our facts `[data]`; no unsourced numbers; say
  "unclear" rather than guess.

## Run it

```sh
echo 'GEMINI_API_KEY=<your key>' >> .env   # repo root; .env is git-ignored
uv run experiments/country_brief.py      # serves http://127.0.0.1:8787
uv run experiments/country_brief.py check  # before a demo: one tiny live call per model, the models the key can use
# then open ui/globe/index.html?brief=1
```

A `GEMINI_API_KEY` already set in the environment wins over `.env`.

Without `?brief=1` the page shows no AI button, so the published demo is unchanged. Optional
settings: `GEMINI_MODEL` (default `gemini-3.8-flash`; Google's `gemini-api-dev` skill lists
`gemini-2.5-*` as deprecated) and `BRIEF_PORT`. `?brief=<url>` points the
page at another proxy.

## Not done yet / open questions

- **Live check, 25 Oct 2026** (`country_brief.py check`, free-tier key): the key lists 60 models,
  including `gemini-3.8-flash` and `gemini-nano-banana-2.1`. Text through the Interactions API works. The
  picture fails: the free tier has no quota for the image model (HTTP 429, limit 0), so "What is it?" now
  returns the text without a picture rather than failing. The `generateContent` call timed out at 60 s,
  so `/brief` (the globe's grounded brief) is still unconfirmed.
- **Event rules on AI use.** AGENTS.md still has a TODO for the hackathon's AI-use and provenance
  rules. If they restrict generated content in the demo, keep the button off.
- **The published artifact** is a page on claude.ai, so it can't reach a localhost proxy. If we
  want briefs there, the artifact runtime can ask Claude directly, with no key in the page. That
  would be a separate, labelled path.
- **Fact checking.** A next step is to flag any number in the brief that disagrees with our tables.
