# BrokerBrief operations

How BrokerBrief runs without anyone, how to tell it is healthy, what each alert means and what to do about it. Every statement here is checkable against the files named.

## What runs, and when

| What | Where | When | Writes to |
|---|---|---|---|
| Morning brief | `.github/workflows/morning-brief.yml` | **Manual only until Decision Batch 3.** Then 06:15 Singapore time, with a fallback at 06:50 that does nothing if the day's brief already exists | `briefs` branch (archive); GitHub Pages (`/brief/`); the `brief-alert` issue |
| Tests | `.github/workflows/tests.yml` | Every push, and Mondays 09:40 Singapore time | Nothing (pass or fail only) |
| Decision tool | Streamlit Community Cloud, from `main` | When someone visits | Nothing |

The Streamlit app needs no scheduled refresh: it fetches EIA and PortWatch itself when visited, shares each result between visitors for 3 hours, and retries a failed fetch after 5 minutes (`app.py`, `LIVE_TTL_SECONDS`, `FAILURE_RETRY_SECONDS`).

### One run of the morning brief, step by step

1. **Keep the schedule alive** (see "The 60-day rule").
2. **Check out the archive** (`briefs` branch) and work out today's Singapore date.
3. **Skip** if today's brief already exists (this is what makes the fallback run safe).
4. **Build the payload** (`python -m modules.morning_brief`): EIA prices, MPA bunker sales, IMF PortWatch activity, three news feeds. A feed that fails leaves its section marked "No verified data today" with the reason; it never stops the run.
5. **Write and check the brief** (`python -m modules.morning_brief.write`). The model writes news summaries only; each is checked, retried once, then withheld if it still fails. The whole brief is then checked; if that fails, nothing is published (exit code 3).
6. **Archive** to `briefs/YYYY/MM/DD/` with the payload and the validation report.
7. **Decide on the alert** and open, update or close the issue.
8. **Build and deploy the site** to GitHub Pages from the archive.

Typical run time: one to two minutes. GitHub can delay scheduled runs at busy times, and at the start of each hour most of all, which is why the runs are at :15 and :50. Even a run delayed by more than an hour finishes before 08:00.

## How to tell it is healthy

- **No open issue labelled `brief-alert`.** The workflow opens one whenever something needs you and closes it after the next clean run.
- **The brief page's "Last updated" date is today** (Singapore date). If the page is more than two days old, readers see a banner saying so, even if nothing could run to report it.
- **The archive page** (`/brief/archive.html`) lists every run with its status and any empty sections.
- **The Actions tab** shows each run. A run marked failed always has a matching alert.

## What each alert means

| Alert text begins | What happened | What to do |
|---|---|---|
| "The run failed at step: …" | Our code crashed or the runner had a problem. Nothing was archived. | Open the run link, read the failing step's log, fix, then run the workflow manually. |
| "The publishing gate refused the brief" | The final brief broke a code-level rule (a number not in the payload, an unknown link, a wrong date…). Nothing was published, by design. | A bug in BrokerBrief. The problem codes are in the alert and in `validation.json` (kept as a run artifact). Fix the code; the next run will clear the alert. |
| "The writer could not use the model" | The API key is missing, wrong or revoked, credit or the spend limit ran out, the API was down, or the model declined. The brief went out with news as headline and link only. | Check the Anthropic Console: key, credit, spend limit. See "Rotate the API key". |
| "Publishing the site to GitHub Pages failed" | The brief may be archived, but the page was not updated. | Open the run link; usually a temporary Pages problem. Re-run the workflow with "publish" ticked. |
| "Section `x` has been empty for N days running" | A source has failed or produced nothing for three or more consecutive runs. | Read the reason under that section in the latest brief. A changed feed format or a dead URL needs a code fix; an outage needs nothing. |

One or two empty days are normal (EIA publishes weekly; a feed can have a bad morning) and do not raise an alert.

## The 60-day rule

GitHub disables scheduled workflows in a public repository when there has been no repository activity for 60 days. GitHub's documentation does not define "activity" (read on 12/11/2026). Three things work against it, none relied on alone:

1. Every run calls GitHub's "enable workflow" API for both scheduled workflows. Widely used keep-alive tools rely on this resetting the clock; GitHub does not document that it does.
2. Every scheduled run commits to the `briefs` branch. Whether a commit made by the workflow's own token counts as activity is also undocumented.
3. If the schedule stops anyway, nothing inside GitHub can report it, so the brief page's staleness banner tells readers, and you will see the old date.

**If it happens:** Actions tab → Morning brief → "Enable workflow". Any push to `main` also counts as activity.

## Streamlit sleep

Streamlit Community Cloud puts an app to sleep after 12 hours without traffic; the next visitor sees a page with a button to wake it (Streamlit documentation, read 12/11/2026). BrokerBrief does **not** ping the app to keep it awake: that may breach Streamlit's terms. The morning brief is on GitHub Pages, which does not sleep, and links to the app.

## Rotate the API key

Do this if the key may have leaked, or once a year.

1. Anthropic Console → API keys → create a new key, named `brokerbrief-github-actions`. Check the workspace spend limit (USD 5 a month was agreed in Decision Batch 1).
2. GitHub → repository → Settings → Secrets and variables → Actions → `ANTHROPIC_API_KEY` → Update, paste the new key, save. Never paste it anywhere else.
3. Actions → Morning brief → Run workflow, with "archive" and "publish" unticked. The run's validation report should show writer status `ok`.
4. Back in the Console, delete the old key.

The EIA key is rotated the same way: the secret is `EIA_API_KEY` in GitHub, and `EIA_API_KEY` in the Streamlit app's secrets (Streamlit Community Cloud → app → Settings → Secrets).

## Archive and retention

- Layout: `briefs/YYYY/MM/DD/` holding `brief.md` (if published), `payload.json` and `validation.json`; `briefs/index.json` lists every run; `briefs/health.json` holds the empty-section streaks the alerts use.
- Size: about 50 KB a day before compression, about 19 MB a year.
- Retention (Decision Batch 1, D7): everything is kept for 12 months, then reviewed. Nothing is deleted automatically.
- The archive is public, including any errors during the trial.

## Failure tests

Run the workflow manually with **break_feed** set to one source. That source's requests fail on purpose (`BROKERBRIEF_BREAK_FEED`, read only by `modules/morning_brief/guarded_http.py`), its section is published as "No verified data today" with the reason "deliberately broken for a failure test", and the rest of the brief is unaffected. Scheduled runs never set it.
