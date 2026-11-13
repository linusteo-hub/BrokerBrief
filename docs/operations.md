# BrokerBrief operations

How BrokerBrief runs without anyone, how to tell it is healthy, what each alert means and what to do about it. Every statement here is checkable against the files named.

## What runs, and when

| What | Where | When | Writes to |
|---|---|---|---|
| Morning brief | `.github/workflows/morning-brief.yml` | **Manual only until Decision Batch 3.** Then 06:15 Singapore time, with a fallback at 06:50 that does nothing if the day's brief already exists | `briefs` branch (archive); GitHub Pages (`/brief/`); the `brief-alert` issue |
| Tests | `.github/workflows/tests.yml` | Every push, and Mondays 09:40 Singapore time | Nothing (pass or fail only) |
| Decision tool | Streamlit Community Cloud, from `main` | When someone visits | Nothing |

The Streamlit app needs no scheduled refresh: it fetches EIA and PortWatch itself when visited, shares each result between visitors for 3 hours, and retries a failed fetch after 5 minutes (`app.py`, `LIVE_TTL_SECONDS`, `FAILURE_RETRY_SECONDS`).

### One run of the morning brief

Five jobs, each holding only the permissions it needs:

| Job | Permissions | What it does |
|---|---|---|
| keepalive | re-enable workflows | Calls GitHub's "enable workflow" API for both scheduled workflows (see "The 60-day rule"). |
| build | read only | Reads the archive; skips if today's brief already exists (this makes the fallback run safe); builds the payload; writes and checks the brief. Holds the EIA key (and the model key, only if the model is switched on) and cannot push. A feed that fails leaves its section marked "No verified data today" with the reason; it never stops the run. If the final checks fail, nothing is published (the gate's exit code 3). |
| archive | write to the repository | Commits the day to `briefs/YYYY/MM/DD/` on the `briefs` branch. A rejected push is retried four times; if all fail, the job fails. |
| site | deploy Pages | Builds the site from the archive and deploys it. If the archive cannot be read, the job fails rather than deploying an empty site. |
| alert | write issues | Runs last, whatever happened, and sees every other job's result; each of its steps runs even after a cancellation. Opens, comments on or closes the alert issue. A run that skipped because today's brief already exists reports nothing. If this job itself fails, the run shows as failed in the Actions tab; see "Notifications" below for who is e-mailed. |

Run time on GitHub: **not yet measured** (the workflow has not run there). The scheduled times leave about an hour and three-quarters before 08:00 Singapore time. GitHub can delay or drop scheduled runs at busy times, and says the start of each hour is busiest, so the runs are at :15 and :50 and a dropped primary run is covered by the fallback. Nothing can guarantee a time if GitHub drops both.

## How to tell it is healthy

- **No open issue labelled `brief-alert`.** The workflow opens one whenever a scheduled run needs you and closes it after the next clean scheduled run. Manual runs use a separate label, `brief-alert-test`, so a test never closes a real alert.
- **The brief page's "Last updated" date is today** (Singapore date). If the latest brief is more than two days old (counted from 06:00 Singapore time on its date), the page shows readers a banner saying so, even if nothing could run to report it.
- **The archive page** (`/brief/archive.html`) lists every archived run with its status and any empty sections. A day with no row had no archived run.
- **The Actions tab** shows each run. Any failed, cancelled or timed-out job raises an alert from the alert job. If the alert job itself fails, the run is marked failed, and GitHub's own notification goes to the person described under "Notifications".

## What each alert means

| Alert text begins | What happened | What to do |
|---|---|---|
| "Job "…" failed" or "was cancelled or timed out" | A job crashed, timed out or was cancelled. If it was the build, nothing was archived. If it was the archive job, the push failed. | Open the run link and read that job's log. Fix, then run the workflow manually. |
| "The writer crashed" | Our code raised an error while writing; nothing was published. | A bug: the error text is in the alert. |
| "No run was archived for <date>" | The archive has no entry for yesterday: both scheduled runs were dropped, or failed before archiving. | Check the Actions tab for that day. Nothing else to do: today's brief is out. |
| "The alert job could not read the briefs branch" | A network or permission problem reading the archive; the archive checks were not made. | Usually temporary; check the next run. |
| "The publishing gate refused the brief" | The final brief broke a code-level rule (a number not in the payload, an unknown link, a wrong date…). Nothing was published, by design. | A bug in BrokerBrief. The problem codes are in the alert and in `validation.json` (kept as a run artifact). Fix the code; the next run will clear the alert. |
| "The writer could not use the model" | Only when the model has been switched on (`BRIEF_USE_MODEL`): the key is missing, wrong or revoked, the secret was deleted, credit ran out, the API was down, or the model declined. News went out as headline and link only. | Check the secret, then the provider's console. See "Language model (off)". |
| "Job "Publish to GitHub Pages" failed" | The brief was archived, but the page was not updated. | Open the run and use **Re-run failed jobs**: that re-runs only publishing and the alert. (Running the workflow again from the start would skip, because today's brief already exists.) |
| "Section `x` has been empty on N run dates in a row" | A source has failed or produced nothing on three or more consecutive archived runs. (Run dates, not calendar days; a missing day raises its own alert.) | Read the reason under that section in the latest brief. A changed feed format or a dead URL needs a code fix; an outage needs nothing. |

One or two empty days are normal (EIA publishes weekly; a feed can have a bad morning) and do not raise an alert.

## The 60-day rule

GitHub disables scheduled workflows in a public repository when there has been no repository activity for 60 days. GitHub's documentation does not define "activity" (read on 12/11/2026). Three things work against it, none relied on alone:

1. Every run's keepalive job calls GitHub's "enable workflow" API for both scheduled workflows. Widely used keep-alive tools rely on this resetting the clock; GitHub does not document that it does.
2. Every scheduled run that produces a brief commits to the `briefs` branch (a fallback run that skips does not). Whether a commit made by the workflow's own token counts as activity is also undocumented.
3. If the schedule stops anyway, nothing inside GitHub can report it, so the brief page's staleness banner tells readers, and you will see the old date.

**If it happens:** Actions tab → Morning brief → "Enable workflow". Any push to `main` also counts as activity.

## Streamlit sleep

Streamlit Community Cloud puts an app to sleep after 12 hours without traffic; the next visitor sees a page with a button to wake it (Streamlit documentation, read 12/11/2026). BrokerBrief does **not** ping the app to keep it awake: that may breach Streamlit's terms. The morning brief is on GitHub Pages, which does not sleep, and links to the app.

## Language model (off)

The brief runs **without a language model** (Decision Batch 2, 13/11/2026: no spending). Figures, dates and changes are written by code; headlines are copied from the publishers' feeds; news items are headline, publisher, date and link. Nothing calls a paid API, and no API key is needed apart from the free EIA key.

The model path is kept in the code and tested, so it can be switched on later without code changes:

1. Create an Anthropic API key and set a spend limit in the Anthropic Console (the writer uses the Anthropic SDK; another provider would need code changes).
2. GitHub → repository → Settings → Secrets and variables → Actions → Secrets → `ANTHROPIC_API_KEY`.
3. Same page → Variables → `BRIEF_USE_MODEL` = `true`.
4. Optionally restore the model-trial workflow from `_archive/workflows/` first, to measure cost and quality.

With the variable unset, the workflow passes no key, and `write.py` itself refuses to create a model client, whatever keys are in the environment or `.env`.

## Rotate the EIA key

The EIA key is free, but rotate it if it may have leaked:

1. Register a new key at eia.gov/opendata.
2. GitHub → repository → Settings → Secrets and variables → Actions → `EIA_API_KEY` → Update.
3. Streamlit Community Cloud → the app → Settings → Secrets → replace the `EIA_API_KEY` line, then save.
4. Actions → Morning brief → Run workflow with "force" ticked, and "archive" and "publish" unticked. Then open the run's `brief-output` artifact and check that `validation.json` shows Prices `ok`.

## Archive and retention

- Layout: `briefs/YYYY/MM/DD/` holding `brief.md` (if published), `payload.json` and `validation.json`; `briefs/index.json` lists every run; `briefs/health.json` holds the empty-section streaks the alerts use.
- Size: about 50 KB a day before compression, about 19 MB a year.
- Retention (Decision Batch 1, D7): everything is kept for 12 months, then reviewed. Nothing is deleted automatically.
- The archive is public, including any errors during the trial.

## Notifications

GitHub sends failed-run notifications for a scheduled workflow to the user who created it, or who last changed its cron line, or who last re-enabled it, and only if that user has Actions notifications switched on (GitHub documentation, read 12/11/2026). So that failure e-mails reach Linus: the commit that switches the schedule on (Decision Batch 3) should be made from Linus's own GitHub account, and Linus should check GitHub → Settings → Notifications → Actions. Alerts raised by the workflow itself (the `brief-alert` issue) notify watchers of the repository like any issue.

## GitHub Pages setting (one-off, owner only)

Publishing from the workflow needs the repository's Pages source set to **GitHub Actions** (Settings → Pages → Build and deployment → Source). Today Pages is built from `main` by GitHub's own builder, which renders the README as the landing page. After the switch, the landing page is the README rendered by BrokerBrief's site builder: same text, but the architecture diagram shows as code rather than a picture. This is part of Decision Batch 3.

## Failure tests

Run the workflow manually with **break_feed** set to one source. That source's requests fail on purpose (`BROKERBRIEF_BREAK_FEED`, read only in `modules/morning_brief/guarded_http.py`). A failure-test run is never archived or published, whatever the other boxes say, and always opens a `brief-alert-test` issue naming the broken source, so the alert path is tested too.

- **A data source** (`eia_spot`, `mpa_bunker_sales`, `imf_portwatch`): its section is shown as "No verified data today" with the reason "… deliberately broken for a failure test". This is the clearest test; use `mpa_bunker_sales`.
- **One news feed** (`gcaptain`, `splash247`, `maritime_executive`): the news sections still show the other two publishers' stories. The broken feed is recorded in `validation.json` under `feed_errors`. A news section is marked empty only when every feed fails.

Download the run's `brief-output` artifact to see the brief the test produced. Scheduled runs never set the variable, and only someone with write access can start a manual run.

## Known limits

- If both the primary and the fallback runs are dropped by GitHub, that day has no brief. The next scheduled run's alert job finds the gap in `briefs/index.json` and reports it.
- A refused day is retried by the fallback run. If the cause is a bug, it will be refused again, and the alert gets a second comment.
- The workflow allows one queued run at a time. If three runs were started together, the middle one would be cancelled; the alert job of the run that does go ahead does not see it.
