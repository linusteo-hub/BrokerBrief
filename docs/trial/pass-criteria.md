# Morning brief trial: pass criteria (draft for Linus to approve)

**Status: draft, not yet approved.** The trial starts on the first scheduled run after Decision Batch 3. It runs unattended for at least **14 consecutive days**, and at most 28. Linus only reviews, using `docs/trial/review-log.md`. Nothing is rolled out (email, wider sharing, removing the "trial — under review" label) until every criterion below is met.

Each criterion says how it is measured, so the result can be checked rather than judged.

| # | Criterion | Pass if | Measured from |
|---|---|---|---|
| 1 | **Out on time** | A brief is published by 08:00 Singapore time on at least 13 of 14 days (or the same share over a longer trial) | Archive page dates, and the workflow run times in the Actions tab |
| 2 | **No silent failure** | Every day without a published brief, and every failed run, has a `brief-alert` issue or comment | Actions tab compared with the issue's history |
| 3 | **Figures exactly right** | **Zero** wrong figures in the spot checks: each review day, three figures checked against the source's own site (one EIA price when present, one MPA bunker figure, one PortWatch figure) | Review log, "Figures checked" column |
| 4 | **Licensing clean** | **Zero** banned source names or licensed figures in any published brief or in the `briefs` branch | Verify skill's licence scan run on the `briefs` branch at the end of each week |
| 5 | **Summaries faithful** | At most one summary per week states something the linked article does not support; no summary contains a number (the gate makes this impossible, so any occurrence fails the trial) | Review log, "Summary errors" column (check two summaries a day against their articles) |
| 6 | **Sections right** | At least 90% of reviewed news items are in the right section (S&P, Events, freight rate direction) | Review log, "Misfiled items" column |
| 7 | **Empty sections explained** | No section is empty for more than three days running without a known outside cause (e.g. a publisher's feed down) | `briefs/health.json`, alerts, and the reasons printed in the brief |
| 8 | **Alerts trustworthy** | No more than two false alerts over the trial; every alert closes on the first clean run after its cause is fixed | Issue history |
| 9 | **Cost** | Actual model cost at most USD 5 for any month of the trial | `total_cost_usd` in each day's `validation.json`; Anthropic Console |
| 10 | **Failure test** | One deliberate failure test during the trial (manual run, one feed broken) gives the expected empty section and alert | Run link and issue, noted in the review log |

**Restart rule.** A failure of criterion 3 (a wrong figure) or 4 (a licensing breach) stops the trial. The cause is fixed with a test that would have caught it, and the 14-day count restarts. Other criteria are judged over the whole trial.

**What the trial cannot show.** Whether readers find the brief useful. That needs readers, which is the rollout's question, not the trial's.

**Approval.** Linus: approved / changed on ____ (day-month-year).
