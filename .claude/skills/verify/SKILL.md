---
name: verify
description: Run BrokerBrief's checks (tests, morning-brief validator, secrets and licensed-source scan) before every commit, or when asked to verify a change. Do not commit if any check fails.
---

# Verify BrokerBrief before committing

Run every step in order and report each one as PASS, FAIL or NOT YET BUILT. Don't skip a step because an earlier one passed. Never report overall success if any step failed. If a step can't run because the code it tests doesn't exist yet (e.g. before Phase 1), say NOT YET BUILT. Don't count that as a pass, and don't invent a substitute check.

## 1. Tests

Run `pytest -q` from the repo root. Report the number passed, failed and skipped. Any failure means FAIL.

## 2. Morning-brief validator

Run the validator against the test fixture payloads in `tests/fixtures/`. Use the validator command listed under Commands in CLAUDE.md; if it isn't listed, report NOT YET BUILT.

It must confirm all of these:
- every number in the generated text matches a payload display string, after normalising separators and currency symbols;
- no news summary contains a digit;
- each figure's direction word agrees with the payload's `direction` field;
- every source tag exists in the payload's `sources` list;
- staleness and range checks behave as designed.

The fixtures include cases that are meant to fail. Those must be caught. Report any failing case the validator did **not** catch as FAIL.

## 3. Secrets

Check the staged changes (`git diff --cached --name-only` and `git diff --cached`):
- `.env` and `calibration.yaml` must not be staged;
- both must be listed in `.gitignore`;
- the staged diff must not contain anything resembling an API key (e.g. strings starting `sk-ant-`, or `ANTHROPIC_API_KEY=` followed by a value).

Report the file and line if you find one, but never print the key itself.

## 4. Licensed-source scan

Search the **whole repo**: every tracked file (`git ls-files`) plus every staged file (`git diff --cached --name-only`), including the brief archive folder (generated payloads and briefs). Gitignored files such as `calibration.yaml` and `.env` are not scanned, because they never reach the public repo. Look case-insensitively for: Baltic Exchange, BDI, FBX, Freightos, Worldscale, Clarksons, ClarkSea, Lloyd's List, Platts, Argus, ICE Gasoil. Match BDI, FBX and Argus as whole words, so ordinary words that happen to contain those letters don't count as hits.

Only these places are allowed to contain these names:
- the allowlist/denylist definition file;
- test fixtures that deliberately test that a banned source is rejected;
- `docs/`;
- `CLAUDE.md`;
- this file (`.claude/skills/verify/SKILL.md`), which has to list the names to search for them.

Also confirm the morning-brief module has no import from `modules.decision`.

Any other hit means FAIL. List each one with its path and line.

## 5. Report

End with a short table of the four checks and their status. Then state one of:
- **"Safe to commit"**: only if every step is PASS, or NOT YET BUILT for parts that genuinely don't exist yet;
- **"Do not commit"**: with the reasons.

If any step is NOT YET BUILT, say plainly which protections are therefore not active yet.
