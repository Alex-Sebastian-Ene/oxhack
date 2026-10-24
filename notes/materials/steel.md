# Steel: production, ingredients, supplier links (research desk, 24 Oct 2026)

Data for the materials globe: `steel.json` (one source per row).

**How collected:** web search on 24 Oct 2026. The proxy blocked worldsteel, USGS, IEA, Comtrade,
OEC and FRED, so **every figure is from search-result snippets**. Check the headline numbers
against the primary PDFs before the pitch.

## Production (2025)

worldsteel puts world crude steel at 1,849.4 Mt.
- **China** 960.8 Mt (52%), **India** 164.9 (8.9%), **US** 82.0 (4.4%), **Japan** 80.7 (4.4%).
- **Russia** 67.8 (estimate), **South Korea** 61.9, **Türkiye** 38.1, **Germany** 34.1, **Brazil** 33.3.
- **Iran** 31.8 (estimate), **Viet Nam** 24.7, **Italy** 20.7.

**Route split:** globally 69% blast furnace / basic oxygen furnace and 30% electric arc furnace.
- **China:** about 90% blast furnace (CREA/E3G estimate).
- **India:** 41% blast furnace, 38% induction furnace, 21% electric arc.
- **US:** about 72% electric arc.
- **Japan:** 74% basic oxygen furnace.

## Ingredients

- **Iron ore (USGS MCS 2026, 2025 estimates):** Australia 980 Mt, Brazil 420, India 310, China 290, Iran 93, Russia 86, Canada 69, South Africa 66. Shares are of the 17-country named subtotal, because the world total is unconfirmed.
- **Iron ore trade:** 1,708 Mt seaborne in 2025. Australia ~56% and Brazil ~22% of loadings (AXSMarine).
- **Coking coal:** 375 Mt exported in 2024. Australia 45%, US 15%, Mongolia 14%, Russia 11%. Production by country is unconfirmed.
- **Scrap:** the EU exported 16.7 Mt in 2025, of which 10.8 Mt went to Türkiye.

## Where the top producers' ingredients come from

Per-row sources are in the JSON.
- **China:**
  - Iron ore imports of 1.26 Bt (2025): Australia 64%, Brazil 23%.
  - Coking coal imports of 118.6 Mt: Mongolia 51%, Russia 28%, Canada 9%, Australia 8%.
- **India:**
  - Iron ore is about 96% domestic.
  - Coking coal imports of 62.6 Mt: Australia 54%, Russia 16%, US 15%.
- **Japan:**
  - Iron ore (2024): Australia 57%, Brazil 29%, Canada 7%.
  - Coking coal (Q1 2025 only): Australia 69%, Canada 15%.
- **South Korea:** iron ore shares are from January 2024 only: Australia 68%, Brazil 22%. Coking coal shares for 2025 are unconfirmed.
- **Russia and the US:** largely self-sufficient in ore and coal. The US is a big scrap exporter.
- **Türkiye:** scrap imports of 18.7 Mt (2025): US 19%, Netherlands 15%, UK 11%, Belgium 7%, Romania 5%.

## Oil exposure

Oil reaches steel indirectly:
- through freight, since bulk carriers burn bunker fuel to move ore and coal;
- through coal prices;
- through gas and power for electric arc furnaces and DRI plants.

**2026:** hard coking coal hit US$245/t in July, about 30% above 2025 (IEA). Brazil's ore exports to China fell in September as freight rose.

**No published oil → steel pass-through was found.** We asked Seb for a fitted link (OXH-5), and the globe shows "?" until then.

**Gaps to fill:**
- the USGS world iron ore total;
- coking coal production by country;
- South Korea's 2025 import origins;
- freight in $/t;
- steel price moves in 2022 and 2026.
