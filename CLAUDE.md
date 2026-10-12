# BrokerBrief — standing instructions for Claude Code

BrokerBrief is my (Linus's) Python/Streamlit maritime decision-support project, deployed on Streamlit Community Cloud from the public repo `linusteo-hub/BrokerBrief`. I'm currently adding a public daily **morning brief**. These rules apply in every session.

## Working copy

- The only working copy is this repository (`~/Projects/BrokerBrief`).
- Older copies are archived in `~/Downloads/_archive/` (`brokerbrief`, `brokerbrief 2`, `brokerbrief_v2`, the zips, and other superseded files). Don't edit them.

## How to work with me

- I'm a second-year maritime studies student with a data analytics second major. Explain the mechanism and why you chose an approach. Name failure modes, edge cases, and what breaks as data grows.
- macOS/zsh. Before any state-changing command (install, git, move, delete, push), explain it step by step and wait for my "yes". Read-only commands are fine.
- Never delete files. Move them to `_archive/` and tell me.
- Ask before substantial work if my answer would change the output. Don't over-engineer before scope is confirmed.
- Stop at the end of each build phase, show what changed and how to test it, and wait.
- British/Singapore spelling, metric units, day-month-year dates.

## Architecture boundaries

- The decision engine lives in `modules/decision/`: Constraint Engine → Option Generator → Commercial Evaluation → Confidence Model → Decision Workspace. It contains no AI and is fully rules-based. Don't change it unless I ask.
- The morning brief lives in its own module and **must never import from `modules/decision/`**. It may read from the ingestion layer (`modules/eia.py`, `modules/portwatch.py`).
- The brief separates fetching from writing:
  - deterministic code builds a JSON payload;
  - the language model only writes prose from that payload;
  - the payload carries pre-formatted display strings, pre-computed changes and an explicit `direction` for every figure, so the model never calculates anything.

## Data rules ("no source, no certainty")

- Every value carries source name, URL, retrieval timestamp, licence and quality tier. Missing data is flagged, never invented.
- `modules/data.py` contains hard-coded sample rows with invented values. They must be clearly labelled as sample data, and must never reach the brief or be presented under a real source's name.
- **Banned in any deployed code, payload, brief or archive** (the repo and archive are public):
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

<!-- Fill in once Step 0 and Phase 1 are done, e.g.: -->
<!-- Run the app:       streamlit run app.py -->
<!-- Build the payload: python -m <brief_module>.build_payload -->
<!-- Run the tests:     pytest -q -->
