# Portfolio mode — progress log

Updated after each step: what was done, how it was verified, open issues. Dates are day-month-year.

## Step 0 — Survey and Decision Batch 1 (12/11/2026)

### Done

- Read `CLAUDE.md`, `docs/morning-brief-build-plan.md` (both the `main` and `feature/morning-brief` versions), `README.md`, `.claude/skills/verify/SKILL.md`, all of `modules/decision/`, `modules/morning_brief/`, `modules/data.py` and the relevant parts of `app.py`.
- Merged `feature/morning-brief` (Phase 0–1) into the working branch `claude/brokerbrief-portfolio-mode-5ygs8o`. **Not merged to `main`.** The merge was clean; `main`'s newer README was kept.
- Recorded the portfolio-mode decision and the K1 note at the top of the build plan.
- Added `## Design principles` ("No source, no certainty", "Runs unattended") to `CLAUDE.md`, and a matching line to the README (worded as in development, not yet live).
- Fixed `tests/test_ui_congestion_unknown.py`: it passed `"app.py"` as a relative path, which current Streamlit resolves against the test file, so two tests failed on a fresh install. It now passes an absolute path.

### Verified how

- `pytest -q` on the merged branch: 154 passed (Python 3.13, Streamlit 1.67, pandas 3.1). Before the path fix: 152 passed, 2 failed.
- Demo scenarios re-run by script against the unchanged engine (results under "Findings").
- Verify skill: tests PASS; validator NOT YET BUILT (Phase 2); secrets PASS; licensed-source scan PASS.

### Could not be read or checked (open)

- **`ARCHITECTURE.md` does not exist** on any branch. Commit `88ffbb5` is titled "README ARCHITECTURE.md" but changes only `README.md`.
- **The Strategic Operating Plan, the K1 wording, the "approved design" for Phase 2 and the 15/10/2026 note on demo geography are not in the repository.** The Phase 2 design used below is the one stated in the portfolio-mode prompt (code writes the facts, the model writes summaries; retry then withhold; fail closed).
- **This session's network cannot reach** `docs.github.com`, `docs.streamlit.io`, `www.imo.org`, `linusteo-hub.github.io`, `api.eia.gov`, the PortWatch ArcGIS host, the three news feeds or `data.gov.sg`. Consequences: GitHub, Streamlit and IMO facts below come from search-result summaries of those pages, not from reading the pages; the MPA data.gov.sg addendum is not done; live fetches can only be tested on a GitHub Actions runner.

### Findings — decision engine and README

1. **R1 is wrong in law and unreachable in code.** `PORT_IN_ECA` marks Rotterdam and Houston, but options are only ever generated for Singapore and Fujairah, so R1 can never fire. Its wording ("HSFO is not permitted in [port]") misstates MARPOL Annex VI: regulation 14 limits the sulphur content of fuel *used* (and, since 01/03/2020, *carried for use*) on board; regulation 4 allows approved equivalents such as scrubbers. It does not regulate what a port may sell.
2. **Fuel grade is cosmetic.** Whatever grade is selected, prices and availability are read from the VLSFO fields. `IFO380` and `HSFO` are offered as separate grades although IFO380 is a viscosity grade that is normally high-sulphur fuel.
3. **Demo geography.** Form defaults are Colombo → Rotterdam with Singapore 1 day away and Fujairah 8 days away. Colombo → Rotterdam does not pass Singapore, and 7 days Singapore–Fujairah (about 3,300 nautical miles, from general knowledge, not yet checked against a distance table) implies about 19–20 knots on 45 MT/day.
4. **The app is not live for a visitor.** Brent needs an EIA key pasted into the sidebar; there is no server-side key. There is no free, redistributable port bunker price, so on live data both prices are missing. Run by script with no prices and a 6-day-old Brent: confidence **Medium 73**, with Singapore and Fujairah tied at 67.0. The engine ranks, and reports Medium confidence, with its 40 %-weight cost criterion blind.
5. **Confidence under live freshness.** Scenario 1 and 2: High 91 in demo mode, High 85 with a 6-day-old Brent. Scenario 3: High 85 in demo mode, Medium 79 with a 6-day-old Brent.
6. **README claims that do not match the code.**
   - "Each of 10 inputs the user did not supply" lowers completeness: seven of the ten are always supplied by the form, so only three can ever be missing.
   - "Optional, but each one raises confidence … risk profile · preferred supplier": neither affects confidence, and preferred supplier is not in the form.
   - "R1 … Remove (illegal)": see finding 1.
   - "50 tests": true by count on `main`, but two fail on a fresh install (now fixed on this branch).
   - "Live data" in the diagram: see finding 4.
7. **Unpinned dependencies** (`streamlit>=1.32.0` etc.): the two test failures were caused by a Streamlit behaviour change. On Streamlit Community Cloud an unpinned app can break on a rebuild with nobody watching.
8. `confidence_model.py` uses `date.today()` (server-local time) for Brent's age; the brief's code uses explicit UTC.
9. `PORTWATCH_MAX_AGE` is 10 days in `provenance.py` but PortWatch lags 8–10 days (the brief uses 14).

### Findings — automation (from search summaries; to be re-checked against the docs pages)

- **GitHub 60-day rule:** GitHub's docs state that scheduled workflows in a public repository are disabled automatically after 60 days without repository activity. The docs summary did not define "activity"; third-party sources say commits count. Whether a commit pushed by the workflow itself counts is **unconfirmed**. Design must not depend on it.
- **Pages:** the repo's GitHub Pages site is built by the built-in "pages build and deployment" workflow from `main` (9 runs, latest 03/11/2026). The landing page is therefore whatever `main` renders.
- **Streamlit Community Cloud:** docs summary says apps without traffic for 12 hours go to sleep; a visitor then has to wake the app. Forum reports say repository pushes do not reliably prevent this.
- **Feed probe:** the `ci/feed-probe` workflow ran once on a GitHub runner (12/10/2026): gCaptain, Splash247 and The Maritime Executive all returned HTTP 200 with no redirect (12, 10 and 66 items). Splash247's earlier 403 did not recur from the runner. One run is thin evidence.
- **Anthropic pricing (pricing page read 12/11/2026):** Claude Haiku 5.5 USD 0.10 / 0.50 per million input / output tokens (prompts up to 100,000 tokens); Claude Sonnet 5.5 USD 2 / 10; Claude Opus 5.5 USD 4 / 20. Batch API: 50 % off, but asynchronous, so not suited to a brief with a deadline.

### Open issues carried forward

- Decision Batch 1 awaits Linus's answers.
- `CLAUDE.md` "How to work with me" still carries the old approval rules; whether to rewrite them permanently is asked in Batch 1.
