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
# then open ui/globe/index.html?brief=1
```

A `GEMINI_API_KEY` already set in the environment wins over `.env`.

Without `?brief=1` the page shows no AI button, so the published demo is unchanged. Optional
settings: `GEMINI_MODEL` (default `gemini-3.8-flash`; Google's `gemini-api-dev` skill lists
`gemini-2.5-*` as deprecated) and `BRIEF_PORT`. `?brief=<url>` points the
page at another proxy.

## Not done yet / open questions

- **Untested against the live API.** Our sandbox can't reach `generativelanguage.googleapis.com`,
  and no one has shared a key yet. The tests cover the prompt, the response parsing, the cache and
  the origin check offline. The first live run should confirm that `generateContent` with the
  `google_search` tool still answers for `gemini-3.8-flash`. Google now steers new code to the
  Interactions API (`POST /v1beta/interactions`), where search results arrive as
  `google_search_result` steps; moving there is the fallback if `generateContent` is refused.
- **Event rules on AI use.** AGENTS.md still has a TODO for the hackathon's AI-use and provenance
  rules. If they restrict generated content in the demo, keep the button off.
- **The published artifact** is a page on claude.ai, so it can't reach a localhost proxy. If we
  want briefs there, the artifact runtime can ask Claude directly, with no key in the page. That
  would be a separate, labelled path.
- **Fact checking.** A next step is to flag any number in the brief that disagrees with our tables.
