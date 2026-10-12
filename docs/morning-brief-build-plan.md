Status (12/10/2026): Step 0, Step 1 and Phase 0 complete. Work continues on branch `feature/morning-brief`. Next: Phase 1. Phase 0 results and decisions (below) supersede the candidate-source notes where they conflict.

# BrokerBrief Morning Brief — Claude Code build prompt

Paste everything below the line into Claude Code, started from your home folder (`cd ~` then `claude`). It begins by settling which copy of BrokerBrief is current, then builds in phases and stops for your review after each one.

---

I'm adding a public morning brief to BrokerBrief, my Python/Streamlit maritime decision-support project. Read this whole message before doing anything. Then do **Step 0 only** and stop for my confirmation.

## How to work with me

- I'm a second-year maritime studies student with a data analytics second major. Explain the mechanism and why you chose an approach, not just the code. Name failure modes, edge cases, and what breaks as data grows.
- I'm on macOS/zsh. Before any terminal command that changes something (install, move, git, delete), explain what it does step by step and wait for my "yes". Read-only commands (`ls`, `git log`, `diff`) are fine to run directly.
- Never delete anything. If a file should go, move it to an `_archive/` folder and tell me.
- Ask before substantial work if my answer would change what you build. Don't over-engineer before scope is confirmed.
- British/Singapore spelling, metric units, day-month-year dates.
- Stop at the end of every phase, show me what changed and how to test it, and wait.

## Step 0 — Establish which copy of BrokerBrief is current

There are several copies and I'm not sure which is the latest. Here is what was found by inspecting my Mac on 12 October 2026. Verify it yourself rather than trusting it.

| Location | What it is |
|---|---|
| `~/Downloads/brokerbrief` | `app.py` 28 KB, dated 9 May 2026. No `modules/decision/`. Has a `.venv`. Looks like an early version. |
| `~/Downloads/brokerbrief 2` | Appears identical to the above (same `app.py` size and date), without `.venv`. Likely a duplicate. |
| `~/Downloads/brokerbrief_v2` | `app.py` 45 KB, dated 18 July 2026. Has `modules/decision/` (constraint, evaluation and confidence engines), `eia.py`, `portwatch.py`. Newest local copy. |
| `~/Downloads/*.zip` | `brokerbrief_v2.zip` (14 July 2026), `brokerbrief_mvp.zip`, `brokerbrief_mvp_1.zip`, `brokerbrief_demo.zip`. Probably older snapshots. |
| GitHub `linusteo-hub/BrokerBrief` | Public, branch `main`, only 2 commits. Its README matches `brokerbrief_v2`'s (same structure, same 9 constraint rules, same roadmap). |

Important: **none of the local folders is a git repository**, so there's no history linking them to GitHub.

One discrepancy: my notes say the engine has 13 feasibility rules across six categories, but both the v2 README and the GitHub README list 9 (F1–F3, S1–S2, P1–P2, C1, R1). Either a newer version exists somewhere, or my notes describe planned rules. Tell me which, based on the code.

Do this:

1. Clone `linusteo-hub/BrokerBrief` into a new folder, `~/Projects/BrokerBrief` (explain first, wait for my yes).
2. Diff the clone against `~/Downloads/brokerbrief_v2`, ignoring `.venv`, `.DS_Store` and `__pycache__`. Also check the zips' contents and dates without extracting them into my folders. Count the constraint rules actually implemented in `constraint_engine.py` in each candidate.
3. Ask me for my Streamlit Community Cloud app URL, and help me check in the Streamlit dashboard which repo and branch it deploys from. The deployed source is the strongest evidence of what's current.
4. Report: which copy is current, what differs between the candidates, and anything that exists only in a non-GitHub copy and would be lost.
5. Recommend making `~/Projects/BrokerBrief` (the git clone) the single working copy, with any newer local-only changes committed into it. Wait for my decision before moving or merging anything.

## Step 1 — Read the existing code before proposing anything

Once the working copy is settled, read at least `app.py`, `modules/brief.py`, `modules/signals.py`, `modules/data.py`, `modules/eia.py`, `modules/portwatch.py` and `modules/decision/market_data.py`. Report:

- **There's already a `modules/brief.py`.** It produces a template brief: fixed sentences chosen by a "market tone" label. Explain how it's used and whether the new brief should replace it, or sit alongside it in the new module.
- **`modules/data.py` contains hard-coded sample rows with made-up values attributed to real sources.** Examples: "Baltic Exchange" for Capesize C5, Panamax P2A and VLCC TD3C, and "Ship & Bunker" for Singapore VLSFO and MGO. This breaks my "no source, no certainty" principle. Invented numbers labelled with real sources' names must never reach the public brief. Check whether the deployed app currently shows them to visitors, tell me plainly, and propose a fix (clear "SAMPLE — not real data" labelling, or removal).
- **The README says bunker and freight prices come from a "manual curated CSV".** Find that CSV and its origin. My Project files include a Platts MOPS scan and an Argus/Bunkerwire PDF, both licensed. If any CSV values came from those or other licensed sources, flag it. They must not ship in a public app or brief.

## What we're building

A daily morning brief for me first, then friends and students who want to keep up with shipping markets. Plain English, not overly technical. Readers should come away understanding the current market better, and it should give me interview talking points.

### Decisions already made (don't re-open these)

- Built inside BrokerBrief, as its own module, e.g. `brief/` or `modules/morning_brief/`. It may read from the ingestion layer (`eia.py`, `portwatch.py`). It must **never import from `modules/decision/`**; the market-intelligence layer stays architecturally separate from the decision engine.
- Content priorities, in order: (1) prices, (2) freight, (3) sale and purchase (S&P), (4) events and why they matter.
- Prices: basic benchmarks only, such as Brent and diesel/gasoil. No Singapore bunker prices.
- Freight: dry bulk, tankers and containers.
- Cadence: prices and events daily; freight and S&P may be weekly.
- If a feed fails, the brief still goes out with that section marked empty, rather than not sending.
- The repo, the brief and the archive are **public**.
- **No licensed and no paid sources.** Freight and S&P come from news summaries with links plus free indicators.
- No social-media scraping (X, Instagram, LinkedIn).
- Rollout: a personal trial I review, then gradual email rollout. **Don't build email yet.**

### Licensing rules (verified 12 October 2026; don't relax them)

- **Baltic Exchange data is out entirely.** That includes the BDI, Capesize/Panamax/Supramax indices, tanker TD/TC routes, and the Freightos Baltic Index (FBX), because Freightos is the Baltic's authorised firm for container data. The Baltic's data policy (version dated Nov 2025, balticexchange.com/en/site-services/data-policy.html) says:
  - anyone who handles Baltic Data accepts its terms;
  - even licensed subscribers may not display it on a public website;
  - data received via media partners may not be copied or redistributed.
  So index levels quoted in news articles are covered too.
- **Worldscale is out.** The flat-rate schedule is subscriber-only, and WS points in the news are usually Baltic route assessments.
- **Clarksons Research and Lloyd's List are out.** My school access is under academic terms that prohibit systematic extraction. They stay offline-only in the gitignored `calibration.yaml`, never in deployed code or output.
- **ICE Low Sulphur Gasoil is exchange data**, so assume it's licensed. Use EIA's public refined-product series instead.
- Enforce this in code, not just in this prompt. Keep a source allowlist where each entry records its licence or terms and a `redistributable: true/false` flag. The payload builder must refuse any source not on the allowlist.

### Candidate sources (Phase 0 confirms terms before use)

**Prices**
- EIA API (already integrated): Brent spot and a US diesel series (e.g. New York Harbor ULSD). Look up the exact series IDs, update schedule and publication lag in EIA's documentation. Don't rely on memory. If daily prices are published with a lag, show the "as of" date next to every price, and set the staleness threshold to match.

**Freight: containers (numbers)**
- Drewry World Container Index (weekly). The public page publishes values, but I found no reproduction terms. Verify before use.
- Shanghai Containerised Freight Index (SCFI). Terms unknown; verify.

**Freight: dry bulk and tankers (direction only)**
- No free redistributable rate source is known. Use news summaries giving direction in words ("Capesize rates fell on Atlantic weakness, per [outlet]"), with no figures.
- IMF PortWatch (already integrated) for physical activity (chokepoint transits, port calls), labelled clearly as activity, not rates.

**News feeds (all checked live on 12 October 2026; RSS works, excerpts only)**

| Source | Feed | Best for | Notes |
|---|---|---|---|
| gCaptain | `https://gcaptain.com/feed/` | Events | Carries Reuters and Bloomberg wire stories |
| Splash247 | `https://splash247.com/feed/` | S&P and deals, all segments | Categories: Dry Cargo, Tankers, Containers, Gas |
| Hellenic Shipping News | `https://www.hellenicshippingnews.com/feed/` | Freight and S&P commentary | Mostly reposted broker and analyst reports; "Weekly Shipbrokers Reports" category |
| The Loadstar | `https://theloadstar.com/feed/` | Containers | Filter out items in "Premium" (paywalled) and "Sponsored Post" categories |
| The Maritime Executive | `https://maritime-executive.com/articles.rss` | Events, tankers, ports | Atom feed; many press releases, so needs filtering |

I haven't yet read each site's terms of use. Phase 0 must do that.

**News attention/tone (optional)**
- GDELT DOC 2.0 API: free, no key. Third-party write-ups say the GDELT Project's datasets allow redistribution with citation and a link, but GDELT Cloud has different terms prohibiting redistribution. Verify on gdeltproject.org, use only the Project's own API, and throttle requests: one third-party note cites about one request per 5 seconds (unverified).

### Design

1. **Fetching is separate from writing.** Deterministic code fetches, validates and assembles a JSON payload. The language model only writes prose from that payload.
2. **The payload does the arithmetic.** For each numeric item, include:
   - the raw value;
   - a pre-formatted display string (e.g. `"USD 84.20/bbl"`);
   - pre-computed absolute and percentage changes, also as display strings;
   - an explicit `direction` (`up` / `down` / `flat`);
   - an `as_of` date, a source ID and a quality tier.
   The model never calculates, converts or rounds anything.
3. **Section status has three states.**
   - `ok`;
   - `missing` (a feed failed today, with a reason);
   - `not_covered` (no clean source exists).
   These are different situations, and readers should be able to tell them apart. Each section also records its cadence (`daily` or `weekly`).
4. **News items are built from the feed title and excerpt only.** Never fetch full article pages. Store the headline, link, publisher, the original author if the excerpt names one (e.g. "broker Gibson"), and published date. Deduplicate stories that appear in several feeds, such as the same Reuters wire on gCaptain and elsewhere.
5. **The validation gate runs before anything is published.**
   - **Number check:** every number in the generated text must match a display string in the payload. Normalise thousands separators, decimals and currency symbols. Whitelist dates and section-heading numbers.
   - **No digits in news summaries.** Feed excerpts already contain licensed figures: Hellenic Shipping News excerpts quote Baltic Capesize time-charter averages and Worldscale points, and Splash quotes Clarksons' ClarkSea Index. Any digit in a news summary fails it, and that item is dropped.
   - **Direction check:** the verb the text uses for each figure ("rose", "fell") must agree with the payload's `direction`. The number check alone can't catch "Brent rose" when it fell.
   - **Range checks** per series, e.g. Brent between USD 10 and 300/bbl.
   - **Staleness checks** with a threshold per series, to suit daily versus weekly data.
   - **Source tags:** every figure carries a source tag that exists in the payload's `sources` list.
   - A section that fails is published marked empty, with the reason, never with unchecked content.
6. **Archive** every brief together with its payload and validation report, so I can audit accuracy during the trial.
7. **Secrets:** the Claude API key goes in a gitignored `.env` locally and in GitHub Actions secrets. Never commit it.

**Public-archive caveat:** the repo is public, so the archive is public from the first scheduled run, including any errors during my trial. I've accepted that, but make the Streamlit brief page clearly say "trial — under review" until Phase 4 passes.

## Phases (stop after each one)

- **Phase 0 — Source audit.** For each section, produce a table: source, licence/redistribution terms (with a link to the terms page you read), update frequency, access method, reliability. Then give a go/no-go for each section. If a priority has no clean source, say so plainly. Don't write fetch code yet.
- **Phase 1 — Payload.** Fetchers, the allowlist, validation of fetched values, and JSON output with provenance. Runs locally from the command line. Include pytest tests that feed fixture data: a stale value, an out-of-range value, a missing feed, a non-allowlisted source.
- **Phase 2 — Writer.** A Claude API call using the runtime prompt below, plus the full validation gate. Check Anthropic's current documentation for model names and pricing rather than assuming them, and estimate cost per brief and per month. Write pytest tests for the checker, including cases that should fail:
  - a number not in the payload;
  - "1,234.5" against a payload value of "1234.50", which should pass after normalisation;
  - a digit inside a news summary;
  - a "rose" that should be "fell".
- **Phase 3 — Schedule and page.** A daily GitHub Actions job that finishes before 08:00 SGT (cron runs in UTC, and GitHub can delay scheduled jobs, so leave margin). Archive output to the repo, and add a Streamlit page showing the latest brief and the archive.
- **Phase 4 — Trial.** Help me set up a review log (errors, missing sections, corrections) and agree pass criteria before any rollout.
- **Phase 5 — Email.** Not now.

## Phase 0 results — source audit (12 October 2026)

Terms pages were read on 12 October 2026. Baltic Exchange, Worldscale and the licensed sources were not re-researched (already verified above). The five RSS feeds were checked live the same day.

### 1. Prices

| Source | Terms (page read) | Update frequency | Access | Reliability |
|---|---|---|---|---|
| EIA Brent spot (`RBRTE`) | [EIA copyright and reuse](https://www.eia.gov/about/copyrights_reuse.php): public domain; credit "Source: U.S. Energy Information Administration (<publication date>)". **Caveat:** the spot prices come from **Refinitiv, an LSEG business** ([definitions](https://www.eia.gov/dnav/pet/TblDefs/pet_pri_spt_tbldef2.asp)). EIA's policy says privately licensed material "may be protected", but EIA puts no restriction on these tables, and [FRED](https://fred.stlouisfed.org/series/DCOILBRENTEU) tags the series "Public Domain: Citation Requested". | Daily values, **released weekly** (release 07-10-2026 held data to 06-10; next release 15-10, moved for Columbus Day). [Table](https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm) | API v2 with key (already in `modules/eia.py`) | High; lag up to about 9 days |
| EIA NY Harbor ULSD (`EER_EPD2DXL0_PF4_Y35NY_DPG`) | Same as Brent | Same | Same | Same |

Series IDs were read from EIA's own table. Confirm the exact API v2 route against EIA's documentation in Phase 1.

### 2. Freight — containers (numbers)

| Source | Terms | Update frequency | Access | Reliability |
|---|---|---|---|---|
| Drewry WCI | [Drewry terms](https://www.drewry.co.uk/terms): "User may not copy, reproduce, republish, distribute…"; downloads for "personal, internal use" only; commercial use needs a licence. The WCI page grants nothing extra. | Weekly, Thursdays (latest 08-10-2026) | HTML page, no API | High as data; **republishing prohibited** |
| SCFI | No reuse terms found; "All Rights Reserved" ([en.sse.net.cn](https://en.sse.net.cn/)). English index page asks for username and password. Publisher changed to Shanghai Shipping Exchange Institute (Prep.) on 18-06-2026 ([notice](https://www.sse.net.cn/announcement/business)). | Weekly, Fridays (secondary sources) | Login-walled | Unknown |

### 3. Freight — physical activity

| Source | Terms | Update frequency | Access | Reliability |
|---|---|---|---|---|
| IMF PortWatch | Dataset licence field points to the [IMF terms](https://www.imf.org/en/about/copyright-and-terms): reuse and publication allowed with credit "Source: International Monetary Fund, PortWatch, <link>". **Commercial reuse needs permission**; **automated bulk download prohibited** without permission. | Weekly batches; on 12-10-2026 latest data was 02-10 (ports) and 04-10 (chokepoints), a lag of about 8–10 days | ArcGIS FeatureServer (already in `modules/portwatch.py`), no key | Good; AIS draft fields are crew-entered and can be wrong |

PortWatch credit (Linus, 12/10/2026):
- Link chosen: `https://portwatch.imf.org`.
- IMF terms require stating any material transformation alongside the citation. Everything BrokerBrief shows from PortWatch is transformed (Market Intelligence's Rising/Easing/Stable labels and majority "Congestion" pill; the brief's 7-day totals and week-on-week changes), so the credit used everywhere is: "BrokerBrief calculations based on data from International Monetary Fund, PortWatch, https://portwatch.imf.org" (`PORTWATCH_CREDIT` in `modules/portwatch.py`).
- Commercial reuse requires permission from copyright@imf.org (see Pending permission).

### 4. News feeds

| Source | Terms | Frequency | Access | Reliability | Verdict |
|---|---|---|---|---|---|
| gCaptain | No terms of use published; only [privacy policy](https://gcaptain.com/about/privacy-policy/) and [editorial standards](https://gcaptain.com/editorial-standards/). Default copyright. Carries Reuters and Bloomberg wires. | Many per day | RSS | Good | Conditional GO |
| Splash247 | `/terms-of-service/` and `/legal-agreement/` exist but are **empty** (last edited 2014). © Splash Maritime Group, all rights reserved. | Many per day | RSS | Fair: 403 to one fetcher, one timeout | Conditional GO |
| Hellenic Shipping News | [Disclaimer](https://www.hellenicshippingnews.com/disclaimer/): "STRICTLY PROHIBITS the republication, the reproduction, total, partial or at paraphrase… without previous written authorisation" | Many per day | RSS | Blocks bots (403) | **NO-GO** |
| The Loadstar | [Licensing and copyright](https://theloadstar.com/licencing-and-copyright): RSS only "to create links back"; free use max 2 articles/week, 150 words; use in "operating artificial intelligence systems… or ingestion into large language models" not permitted | Many per day | RSS | Good | **NO-GO** |
| The Maritime Executive | No terms page; footer "All rights reserved" ([privacy policy](https://maritime-executive.com/privacy-policy)) | Many per day | Atom | Good; many press releases | Conditional GO |

### 5. GDELT (optional)

| Terms | Frequency | Access | Reliability |
|---|---|---|---|
| [gdeltproject.org/about.html](https://www.gdeltproject.org/about.html): "unlimited and unrestricted use… academic, commercial, or governmental"; may "redistribute, rehost, republish"; must cite the GDELT Project and link to gdeltproject.org | Near real-time; last 3 months searchable ([DOC 2.0](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)) | `api.gdeltproject.org/api/v2/doc/doc`, no key | **Poor on 12-10-2026:** every request, including the first, returned HTTP 429 "limit requests to one every 5 seconds" |

### Go/no-go

| Section | Verdict |
|---|---|
| 1. Prices | **GO** — EIA, latest available with as-of date |
| 2. Freight: container numbers | **NO-GO** → `not_covered` |
| 2. Freight: dry bulk, tanker and container direction | **Conditional GO** — from news, words only, no figures |
| 2. Freight: physical activity | **GO** — PortWatch, weekly, labelled as activity not rates |
| 3. S&P | **Conditional GO, weekly** — thin (mainly Splash247) now that Hellenic Shipping News is out |
| 4. Events | **Conditional GO** — gCaptain, Splash247, Maritime Executive |
| GDELT | GO on terms; **deferred** for reliability |

### Decisions (Linus, 12 October 2026)

1. Hellenic Shipping News and The Loadstar are dropped entirely for v1.
2. gCaptain, Splash247 and The Maritime Executive are conditional GO: headline, link and our own no-digit summary. **Wire items** (feed author Reuters or Bloomberg) are headline and link only. This is enforced in code from the feed's author field, not left to the model. Linus is emailing these three publishers and Drewry for permission separately.
3. Prices are "latest available, with as-of date" (replaces "prices daily"). Staleness threshold about 10 days for EIA; PortWatch threshold set to suit its 8–10 day lag.
4. Container numbers are `not_covered`; container rate **direction** from news is included, as for dry bulk and tankers.
5. Add the IMF PortWatch credit line ("Source: International Monetary Fund, PortWatch, <link>") to the existing Market Intelligence page as well. (To do; not yet implemented.)
6. Daily vs weekly brief is parked until after the personal trial (see Parked decisions).
7. Phase 3: before the first scheduled run, test that the Splash247 feed works from a GitHub Actions runner (it blocked one fetcher with 403).

### Pending permission

| Who | What | Status |
|---|---|---|
| gCaptain, Splash247, The Maritime Executive | Use of headlines, links and our own summaries in the public brief | Linus emailing (decision 2) |
| Drewry | Republishing WCI values | Linus emailing (decision 2); `not_covered` until granted |
| IMF (copyright@imf.org) | Commercial reuse of PortWatch data | **Conditional:** only if BrokerBrief becomes commercial |

## Runtime prompt v1 (for the writer in Phase 2; refine once Phase 0 is done)

System prompt:

> You write the BrokerBrief Morning Brief for students and early-career readers interested in shipping markets. You receive a JSON payload of verified market data and news items. Explain it clearly. You do not find or add data.
>
> Rules:
> 1. Use only numbers that appear in the payload's display strings, exactly as written. Never estimate, convert, round, recalculate or infer a figure. If a point needs a number that isn't in the payload, leave the point out.
> 2. Follow every figure with its source tag, e.g. [S2], matching the payload's `sources` list.
> 3. Describe movement using the item's `direction` field only.
> 4. If a section's status is `missing`, print the heading followed by "No verified data today: <reason>". If it's `not_covered`, print the heading followed by "Not covered: <reason>". Do not fill the gap with general commentary.
> 5. News summaries contain no numbers at all. At most two sentences each, in your own words, with no quotes longer than 10 words, crediting the publisher (and the original author if named), always with the link.
> 6. Keep fact and interpretation apart. Interpretation goes only under "Why it matters", phrased as interpretation ("this suggests…"), never as fact.
> 7. Plain English. Define each technical term in brackets the first time it appears, e.g. "VLCC (very large crude carrier)".
> 8. For weekly sections, say "this week" and give the week's date.
> 9. No trading or investment advice.
> 10. Length about 400 words, in this structure and order:
>
> ```
> # BrokerBrief Morning Brief: <DD Month YYYY>
> ## 1. Prices
> ## 2. Freight
> ## 3. Sale & Purchase
> ## 4. Events and why they matter
> ## Sources
> ```

## Do not

- Use any Baltic, Worldscale, Clarksons, Lloyd's List, Platts, Argus or ICE data, or any paid source.
- Scrape social media, or fetch full article pages.
- Import from `modules/decision/`, or change the decision engine.
- Build email delivery.
- Delete files, or run state-changing commands without my confirmation.

Start with Step 0.

## Parked decisions

- Confidence model: a missing price on a feasible option drops confidence by only 6 points (Scenario 3 stays High at 85). Options: raise the penalty, or cap confidence at Medium when any feasible option lacks a price. Decide after the morning brief.
- Brief cadence: daily or weekly. EIA prices are released weekly and PortWatch lags 8–10 days, so a daily brief may repeat figures. Decide after the personal trial.
