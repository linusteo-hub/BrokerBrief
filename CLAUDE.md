# BrokerBrief — standing instructions for Claude Code

BrokerBrief is my (Linus's) Python/Streamlit maritime decision-support project, deployed on Streamlit Community Cloud from the public repo `linusteo-hub/BrokerBrief`. I'm currently adding a public daily **morning brief**. Since 12/11/2026 the project is in **portfolio mode** (see `docs/morning-brief-build-plan.md`): a finished, accurate, self-running public project. These rules apply in every session.

## Working copy

- The only working copy is this repository (`~/Projects/BrokerBrief`).
- Older copies are archived in `~/Downloads/_archive/` (`brokerbrief`, `brokerbrief 2`, `brokerbrief_v2`, the zips, and other superseded files). Don't edit them.

## How to work with me

- I'm a second-year maritime studies student with a data analytics second major. Explain the mechanism and why you chose an approach. Name failure modes, edge cases, and what breaks as data grows.
- macOS/zsh on my laptop; cloud sessions run Linux.
- **Minimal approvals (since 12/11/2026).** Check your own work and ask me only about big decisions, batched: collect them and ask together, each with your recommendation, the alternatives and the trade-off.
  - **Do without asking, then report in the next summary:** editing and creating files; running tests and the verify skill; creating branches and committing to non-main branches; adding a dependency to `requirements.txt` (say why); moving files to `_archive/`.
  - **Big decisions (ask, batched):** anything that changes what the public sees (merging to `main`, enabling a scheduled workflow, publishing the brief page); any change to `modules/decision/`; spending money or anything needing a secret; adding or dropping a data source, or changing the licensing rules; hard-to-reverse architecture choices; deleting anything, force-pushing or rewriting history; anything sent outside the repo (you only draft these).
  - **Only I can do:** creating API keys and spend limits, adding GitHub or Streamlit secrets, changing repository settings. Give me exact steps and carry on with other work.
- Never delete files. Move them to `_archive/` and tell me.
- Don't over-engineer before scope is confirmed.
- After each step: run the verify skill, then have a fresh-context reviewer check the change against this file and the build plan, and fix what it finds. Never report something as done that you haven't run.
- Every claim in the README, the brief page, `docs/operations.md` and any external draft must be checkable against code or a test. If it can't be, cut it or flag it.
- British/Singapore spelling, metric units, day-month-year dates.

## Architecture boundaries

- The decision engine lives in `modules/decision/`: Option Generator → Constraint Engine → Commercial Evaluation → Confidence Model → Decision Workspace. It contains no AI and is fully rules-based. Don't change it unless I ask.
- The morning brief lives in its own module and **must never import from `modules/decision/`**. It may read from the ingestion layer (`modules/eia.py`, `modules/portwatch.py`).
- The brief separates fetching from writing:
  - deterministic code builds a JSON payload;
  - the language model only writes prose from that payload;
  - the payload carries pre-formatted display strings, pre-computed changes and an explicit `direction` for every figure, so the model never calculates anything.

## Design principles

- **No source, no certainty.** Every value shown carries its source and date; missing data is flagged, never invented (rules below).
- **Runs unattended.** The finished BrokerBrief operates without Linus. On a schedule, it fetches, validates, writes, publishes and archives on its own. It fails safe: a broken feed produces a section marked empty with the reason, never unchecked content and never a silent gap. It notices its own failures and tells Linus (e.g. a GitHub issue opened by the workflow). Routine operation needs no manual step. Manual steps are allowed only for one-off setup (secrets, accounts), legal permissions, and decisions.
  - This covers the data refresh and the morning brief. The decision engine stays user-driven (someone enters a scenario), but it must work on live data with no manual refresh.
  - It is a requirement for every phase, not a final step. For each piece of automation, name its failure modes and how each is detected.

## Data rules ("no source, no certainty")

- Every value carries source name, URL, retrieval timestamp, licence and quality tier. Missing data is flagged, never invented.
- `modules/data.py` contains hard-coded sample rows with invented values. They must be clearly labelled as sample data, and must never reach the brief or be presented under a real source's name.
- **Prefer official and primary sources** (government statistics, regulators, intergovernmental bodies) whose licence allows publication with credit. News feeds are secondary.
- **Banned in any deployed code, payload, brief or archive** (the repo and archive are public). These are the sources' own licence terms, not a project preference, so they are not ours to relax:
  - Baltic Exchange data (BDI, all dry and tanker indices and routes, and the FBX container index);
  - Worldscale;
  - Clarksons / Clarksons Research;
  - Lloyd's List;
  - Platts;
  - Argus;
  - ICE exchange prices;
  - any paid source.
- Clarksons and Lloyd's List figures may only appear in the gitignored `calibration.yaml`, for offline calibration.
- Sources must be on the brief's allowlist, which records each source's terms and a `redistributable` flag. The payload builder refuses anything not on it.
- News items are built from the RSS title and excerpt only; never fetch full article pages.
  - **News summaries contain no digits.** Feed excerpts often quote licensed figures.
  - Credit the publisher, and the original author if the excerpt names one.
- No social-media scraping. Don't use the Bright Data plugin for this project.

## Secrets

- The Claude API key lives in `.env` (gitignored) locally, and in GitHub Actions secrets in CI. Never print it, log it or commit it.
- `.env` and `calibration.yaml` must always be in `.gitignore`.

## Checks

- A project skill at `.claude/skills/verify/` runs the tests, the validator and the secrets/licence scan. Run it before every commit; don't commit if it fails.
- Tests use pytest and live in `tests/`.

## Commands

- Run the app: `streamlit run app.py`
- Run the tests: `pytest -q` (no network; fetchers use recorded fixtures in `tests/fixtures/`)
- Build the morning-brief payload from live sources: `python -m modules.morning_brief --out <file>` (needs `EIA_API_KEY` in `.env` or the environment; without it Prices is marked missing)
- Regenerate the example payload after a deliberate change: `UPDATE_PAYLOAD_FIXTURE=1 pytest tests/test_morning_brief_payload.py`
- Write the brief from a payload: `python -m modules.morning_brief.write --payload <payload.json> --out-dir <dir>` (uses `ANTHROPIC_API_KEY` if set; without it, or with `--no-model`, news is published as headline and link only). Exit 0 published, 3 refused by the gate.
- **Validator** (used by the verify skill): `python -m modules.morning_brief.validate --cases tests/fixtures/validator` (exit 0 only if every good case passes and every must-fail case is caught). Check one real brief: `python -m modules.morning_brief.validate --payload <payload.json> --brief <brief.md>`.
- Compare writer models on the fixture payload (needs the API key; spends a few cents): `python -m modules.morning_brief.model_trial --runs 3`
