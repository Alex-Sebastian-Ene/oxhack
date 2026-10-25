"""Shorter copy for the app (copy_text, not copy: that name is a stdlib module), applied after world.SWAPS in build.py. Same facts and sources, fewer words.

Each entry is (old, new, count) like build.SWAPS: old must appear exactly count times.
"""

SWAPS = [
    # World: the shock summary
    ('out.push(`With <b>${st.lost}%</b> of Hormuz oil lost, Brent averages about <b>$${st.brent}</b> over the next year, <b>${f0(pct)}% more</b> than before the war.`);\n'
     '      out.push(`Within a year that pushes diesel at the pump <b>up about ${f0(dsl)}%</b> and overall inflation <b>up about ${f1(cpi)} points</b> (US figures, against no disruption).`);',
     'out.push(`<b>${st.lost}%</b> lost: Brent about <b>$${st.brent}</b> over the year (<b>+${f0(pct)}%</b>).`);\n'
     '      out.push(`US diesel <b>+${f0(dsl)}%</b>, inflation <b>+${f1(cpi)} pts</b>.`);', 1),
    ('if (!st.lost) out.push("With Hormuz flowing normally, Seb\'s chain adds nothing to oil, diesel or inflation.");',
     'if (!st.lost) out.push("Hormuz flowing normally: no change to oil, diesel or inflation.");', 1),
    ('if (k.kind === "gulf") out.push(`${nm} is a Gulf producer: what hurts it is oil it can\'t ship, not the price.`);',
     'if (k.kind === "gulf") out.push(`${nm}: hurt by oil it can\'t ship, not by price.`);', 1),
    ('else if (k.kind === "exp") out.push(`${nm} sells oil abroad, so a higher price helps it.`);',
     'else if (k.kind === "exp") out.push(`${nm} exports oil: a higher price helps.`);', 1),
    ('out.push(`For ${nm}, fuel would cost about <b>${f0(k.fuel * 100)}% ${k.fuel > 0 ? "more" : "less"}</b> than before the war${inDisruption(k.s) ? ", with fuel moving about 1.5 times its usual link, as in past supply disruptions" : ""}.`);',
     'out.push(`${nm}: fuel <b>${k.fuel > 0 ? "+" : "−"}${f0(k.fuel * 100)}%</b>${k.hz > 0.01 ? `, ${f0(k.hz * 100)}% of its oil came via Hormuz` : ""}.`);', 1),
    ('$("w-src").textContent = `Change against no disruption, 12 months on (US). Ranges cover 90% of outcomes. ${chainSrc()}; energy bills from US price data (FRED).`;',
     '$("w-src").textContent = `12 months on, vs no disruption, US. 90% ranges. ${chainSrc()}; energy bills: FRED.`;', 1),
    ('$("e-src").textContent = `Change against no disruption. The range covers 90% of outcomes. ${chainSrc()}.`;',
     '$("e-src").textContent = `Vs no disruption. 90% range. ${chainSrc()}.`;', 1),
    # World: country card
    ("sub = `Before the war it took about ${(d.h / 1000).toFixed(d.h >= 1000 ? 1 : 2)} mb/d through Hormuz. At today's estimated flow that is roughly ${(d.h * Math.min(st.flow / PREWAR, 1) / 1000).toFixed(2)} mb/d.`;",
     "sub = `Via Hormuz: ${(d.h / 1000).toFixed(d.h >= 1000 ? 1 : 2)} mb/d pre-war, about ${(d.h * Math.min(st.flow / PREWAR, 1) / 1000).toFixed(2)} now.`;", 1),
    # Strait panel
    ('$("est-when").textContent = `Scenario: ${sc.label}. Simulated ships, calibrated to that published figure.${lastReal ? ` Real PortWatch counts run to',
     '$("est-when").textContent = `${sc.label}. Simulated ships, set to that published figure.${lastReal ? ` PortWatch counts to', 1),
    ("$(\"link-text\").innerHTML = `About <b>${fmt(flow)}</b> of the pre-war 20 million barrels a day get through, so <b>${lost}%</b> of the flow is lost. ` +\n"
     "      (brent ? `In the World view, that sets Brent at about <b>${brent}</b> a barrel and drives fuel, food and product prices and each country's exposure.` : `The World view turns that into a Brent price and its knock-ons.`);",
     "$(\"link-text\").innerHTML = `<b>${fmt(flow)}</b> of 20 mb/d gets through: <b>${lost}%</b> lost. ` +\n"
     "      (brent ? `That sets Brent near <b>${brent}</b> in the World view.` : `The World view turns that into a Brent price.`);", 1),
    ('$("pw-note").textContent = `Data to ${longDate(PW.dates.at(-1))}, collected ${PW.collected_at.slice(0, 10)}. Counts are real; positions on the map are illustrative.`;',
     '$("pw-note").textContent = `To ${longDate(PW.dates.at(-1))}, collected ${PW.collected_at.slice(0, 10)}. Real counts, illustrative positions.`;', 1),
    ('<p class="faint">Deadweight of tankers that crossed with AIS on, both directions: what they <b>could</b> carry, not what they carried. PortWatch doesn\'t know if a tanker was loaded, or with what.</p>',
     '<p class="faint">Deadweight of tankers crossing with AIS on, both ways: what they <b>could</b> carry, not cargo.</p>', 1),
    ('<p class="faint">Published figures as reported, with the period each covers; check before quoting. "Ours" is our estimate on simulated ships, not a measurement.</p>',
     '<p class="faint">Published figures and their periods; check before quoting. "Ours" is our estimate on simulated ships.</p>', 1),
]
