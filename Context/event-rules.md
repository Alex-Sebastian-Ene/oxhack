# OxHack 2026: event rules

From the one published listing we found ([createwith.com](https://createwith.com/event/oxford-oxhack-26-oxford-s-student-hackathon-oct-2026),
a third-party aggregator, read 25 Oct 2026) and our own setup. Check each line against the organisers' brief,
and keep the original PDFs in `Context/Raw/` if their licence allows it. **Ask the organisers** marks what
nothing published told us.

- **Event:** OxHack 26, a free, student-led hackathon in Oxford: hands-on project building (listing).
- **Dates and venue:** 24–25 October 2026, Oxford (listing; no venue named).
- **Hacking ends / submission lock:** ask the organisers, then copy the time into `AGENTS.md` and
  `coord/PROTOCOL.md` rule 9.
- **Code freeze (ours):** two hours before the lock.
- **Track(s):** none published; ask the organisers. If there are tracks, add `Context/track-<name>.md` and
  say which one we enter.
- **Deliverables:** ask the organisers. Ready whichever they want: the public repo; the one-file app
  (`ui/app/index.html`, works offline); the published page (claude.ai artifact); the pitch notes
  (`docs/pitch.md`); a three-minute demo script (`docs/design.md`, section 5).
- **Judging criteria and weights:** none published; ask the organisers. The pitch's framings
  (`docs/pitch.md`) let us lean towards whatever they weigh.
- **Rules on AI tools, provenance, data and licences:** none published; ask the organisers. Ours until then:
  - AI-written text is labelled with its model and date (the Gemini panels), and never feeds a number;
  - commits carry only the humans' names;
  - every number shows its source and date; synthetic and cached data are labelled, and nothing claims
    to be live;
  - data licences: Global Fishing Watch and OpenSanctions are non-commercial (fine for a hackathon; say so
    on screen); bundled code and fonts are listed with their licences in `ui/app/vendor/`.
- **Team size and eligibility:** UK university students aged 18 or over, and graduates within a year of
  finishing; teams of up to four (listing). We are four: Seb, Eileen, Edward and Yasmin (`coord/team.toml`).
