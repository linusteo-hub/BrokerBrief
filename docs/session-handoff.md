# Session handoff — BrokerBrief portfolio mode (13/11/2026)

Paste the prompt below into a new Claude Code session on the repository `linusteo-hub/BrokerBrief`.

---

I'm continuing BrokerBrief portfolio-mode work from a previous session. Read these before doing anything, in this order:

1. `CLAUDE.md` — standing rules. It overrides defaults. It already holds the batched-approval rules (minimal approvals; big decisions batched with recommendation, alternatives and trade-off).
2. `docs/portfolio-mode-progress.md` — step-by-step log of what was done, how it was verified, and open issues.
3. `docs/morning-brief-build-plan.md` — decisions (Decision Batch 1 and Batch 2 tables, Source policy, Phase 0–3 results, parked decisions).
4. `docs/operations.md` — how the brief runs, alerts, the 60-day rule, keys, failure tests, known limits.
5. `docs/trial/pass-criteria.md` and `docs/trial/review-log.md` — trial set-up (criteria are a DRAFT awaiting my approval).
6. `.claude/skills/verify/SKILL.md` — run before every commit.

## Goal (unchanged)

Portfolio mode, decided 12/11/2026. The aim is a finished, accurate, self-running public project to show shipbroking and bunker-trading employers in Singapore. Customer discovery is paused; K1 fired and I chose portfolio mode.

Design principles:
- **No source, no certainty.**
- **Runs unattended.** Fail safe; every failure is detected and reported; no manual step in routine operation.

## Where things stand

- **Working branch:** `claude/brokerbrief-portfolio-mode-5ygs8o`. Latest commit `356f9e9` (plus this handoff file). It contains:
  - Phases 0–4: credibility fixes, the morning-brief writer and gate, the automation, the trial docs;
  - all Decision Batch 2 work.
- **PR open:** https://github.com/linusteo-hub/BrokerBrief/pull/4 (branch → `main`). **Waiting for me to review and merge.**
- **Checks at the last commit:**
  - `pytest -q`: 323 passed;
  - validator (`python -m modules.morning_brief.validate --cases tests/fixtures/validator`): 22 of 22, all 18 must-fail cases caught;
  - actionlint clean;
  - licence and secrets scans clean.
- **Never run on GitHub yet.** `workflow_dispatch` needs the workflow file on `main`.

### What I still have to do (owner-only)

1. Merge PR #4.
2. Add the GitHub Actions secret `EIA_API_KEY` (free EIA key).
3. Add `EIA_API_KEY = "…"` to the Streamlit app's secrets (share.streamlit.io → app → Settings → Secrets).
4. GitHub → Settings → Notifications → Actions → "Only notify for failed workflows". GitHub e-mails failed scheduled runs only to whoever created or last edited the cron line, or re-enabled the workflow, so **I** should make the Batch 3 schedule commit.
5. Send the scope of Drewry's permission reply: which values, how often, what credit line. Until then container rates stay `not_covered`.

## Decisions already made (don't re-open)

### Decision Batch 1 (12/11/2026), all recommended

| # | Decision |
|---|---|
| D1 | R1 is a MARPOL Annex VI scrubber rule (regulations 14.1 and 4.1); R2 open-loop scrubber warning (Singapore and Fujairah ban discharge); R3 ECA warning (regulation 14.4); IFO380 merged into HSFO; prices follow the selected grade. |
| D2 | Demo voyage: Zhoushan (ballast) → Ras Tanura, 1 day to Singapore, 11.5 days to Fujairah. |
| D3 | Per-source freshness (PortWatch limit 14 days); confidence capped at Medium when one scored port has no price, at Low when none has. |
| D4 | EIA key server-side in Streamlit secrets; fetches cached 3 hours; failures held 5 minutes. |
| D5 | Brief on GitHub Pages; archive on a `briefs` branch; Pages deployed from Actions. |
| D6 | Keep-alive call plus backstops. |
| D7 | Archive `briefs/YYYY/MM/DD/`; keep 12 months, then review. |
| D8 | Daily brief. |
| D10 | gCaptain, Splash247, The Maritime Executive and Drewry replied yes to my permission emails. |
| D11 | `CLAUDE.md` approval rules rewritten. |

Source policy: prefer official and primary sources. Licensed sources (the Baltic Exchange, Worldscale, Clarksons, Lloyd's List, Platts, Argus, ICE) stay banned: their own terms forbid public display.

### Decision Batch 2 (13/11/2026), all recommended

| # | Decision |
|---|---|
| E1 | Merge via PR (PR #4). |
| E2 | Engine: F4 (split stem's second leg keeps the reserve), P1 checks the top-up port, a thin-reserve warning under 3 days (BrokerBrief's own threshold, stated as such), and congestion wording (traffic, not waiting time). |
| E3 | Cruise and leisure stories dropped, in the leisure sense only. |
| E4 | Drewry pending the scope of the reply. |
| E5 | **No spending: the brief runs with NO language model.** News is headline, publisher, date and link. The model code stays, off unless the repository variable `BRIEF_USE_MODEL=true`; `write.py` also enforces this in code. The model-trial workflow is in `_archive/workflows/`. GitHub Models was retired by GitHub on 30/07/2026. Future free options to revisit: a small open model on the runner, or other providers' free tiers (I said "look at alternatives in the future"). |

## Next steps for you (Claude)

Do these after I confirm the merge and the secrets.

1. **Trigger `.github/workflows/morning-brief.yml` twice with `workflow_dispatch`**, using the GitHub MCP tool `actions_run_trigger`:
   - **(a) a normal run:** defaults, so archive and publish are off;
   - **(b) a failure test:** `break_feed=mpa_bunker_sales`.
2. **Show me:**
   - each run's `brief-output` artifact (brief.md and validation.json);
   - the `brief-alert-test` issue that run (b) opens, with the MPA section marked "No verified data today: … deliberately broken for a failure test".
   - Check every job's result, and that the keep-alive enable call worked with `GITHUB_TOKEN`.
   - Fix anything that breaks.
3. **Then Decision Batch 3**, for me to answer in one go:
   - **Enable the schedule:** `cron "15 6 * * *"` and `"50 6 * * *"` with `timezone: "Asia/Singapore"`. The 06:50 fallback differs from D8's original 07:00 because GitHub names the top of the hour as busiest. I should make that commit myself, for notifications.
   - **Switch Pages** Source to "GitHub Actions" (owner setting). The landing page becomes the README rendered by `modules/morning_brief/site.py`; the mermaid diagram shows as code.
   - **Approve** `docs/trial/pass-criteria.md`. Criteria 5 and 9 are marked not applicable while there is no model.
   - **Engine items left over** from the Batch 2 review (changes to `modules/decision/`, so they need my approval):
     - the split option's description can contradict F4 when the 60 % cap binds;
     - F2 doesn't check the top-up quantity at Fujairah: for stems under about 500 MT the top-up is below Fujairah's 200 MT minimum, and for stems under 200 MT the split exceeds the whole stem;
     - an HSFO-without-scrubber split shows F4 or P1 instead of R1 (cosmetic: it is removed either way).
   - **Optional:** add a link from the Streamlit app to the brief page once Pages is live (D5 said the app links to it; not done yet, because the page isn't live).
4. **Then the trial (Phase 4).** At least 14 days unattended; I only review, using `docs/trial/review-log.md`.

## How to work (from the previous session)

- **Before every commit:** the verify skill — tests, validator, secrets scan, and the licence scan over `git ls-files`.
  - Banned names may appear only in `docs/`, `CLAUDE.md`, the verify `SKILL.md`, `modules/morning_brief/allowlist.py`, and `tests/fixtures/**/banned*`. Tests that need a banned name read it from `tests/fixtures/banned_sources.json`.
  - Also check that `modules/morning_brief` never imports `modules.decision`.
- **After each step:** a fresh-context subagent reviews the change against `CLAUDE.md`, the build plan and the decisions. Fix what it finds, and log it in `docs/portfolio-mode-progress.md`. Every review so far found real bugs; keep doing it.
- **Commit attribution:** end messages with the Co-Authored-By and Claude-Session lines the harness gives. Push only to the working branch; never push to `main`.
- **Report honestly:** never say something is done unless it was run. Mark estimates as estimates.

## Environment notes

- **Python:** recreate a venv each session:
  ```bash
  python3 -m venv <scratchpad>/venv
  <scratchpad>/venv/bin/pip install -r requirements-brief.txt pytest
  ```
  `requirements-brief.txt` includes the app's requirements, plus `anthropic` (used only by a test) and `markdown-it-py`. The `httpx2` used by the SDK test arrives with `anthropic`.
- **actionlint** is not installed. Download release 1.7.12 into the scratchpad to lint workflows.
- **Network:** a personal cloud environment named "BrokerBrief" allows docs.github.com, docs.streamlit.io, imo.org, data.gov.sg, api.eia.gov, the PortWatch ArcGIS host, the three news feeds and others.
  - **WebFetch cannot resolve some of these hosts; use `curl` through the proxy instead.**
  - `api.anthropic.com` bypasses the proxy, so credentials can't be injected for it. That doesn't matter now (no model).
- **Workflow gotchas:**
  - `env` is not allowed in a job-level `if:`.
  - `inputs.*` is null on schedule events.
  - Every alert-job step needs `if: always()`, because GitHub re-evaluates step conditions after a cancellation.
  - A fallback run that skips must decide `"none"`, never alert or clear.

## Facts verified against primary sources (don't re-research)

- **MARPOL Annex VI (MEPC.305(73), in force 01/03/2020):**
  - 14.1: "The sulphur content of fuel oil used or carried for use on board a ship shall not exceed 0.50% m/m."
  - 14.4: 0.10% m/m "while a ship is operating within an emission control area".
  - 4.1: equivalents (scrubbers).
  - The open-loop bans at Singapore (from 01/01/2020) and Fujairah (Notice to Mariners 252) come from trade press only.
- **GitHub:**
  - Scheduled workflows in public repositories are disabled after 60 days without repository activity; "activity" is undefined.
  - Schedules run on the default branch only, may be delayed or dropped at busy times, and the top of the hour is busiest.
  - Cron supports `timezone:`.
  - The enable-workflow API needs Actions: write; `GITHUB_TOKEN` qualifies.
  - Events caused by `GITHUB_TOKEN` don't trigger new workflow runs.
  - Pages from Actions needs `pages: write` and `id-token: write`.
- **Streamlit Community Cloud:** apps sleep after 12 hours without traffic. Don't build a keep-alive pinger (possible breach of terms).
- **MPA bunker sales (data.gov.sg dataset `d_4f5abbf4486bf8e52bbed3be56dde562`):**
  - Singapore Open Data Licence 1.0: use and redistribute with attribution and a link to the licence.
  - Values are in thousand tonnes; each month is published about three weeks after it ends; the latest month is preliminary.
