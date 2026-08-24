# ⚓ BrokerBrief — Maritime Commercial Decision Support

https://brokerbrief-agyxesfh7xqqqxqqdqnyfx.streamlit.app/

> Most existing systems tell operators what's happening.
> **BrokerBrief helps them decide what to do next.**

BrokerBrief is a decision support platform for shipbrokers, charterers, and bunker traders. It evaluates a vessel's commercial scenario against live market intelligence, generates the commercially feasible options, removes those that violate hard operational constraints, scores the rest transparently, and presents the trade-offs — with confidence levels, assumptions, and data gaps clearly exposed.

**The GPS analogy:** A GPS doesn't force a route. It identifies viable routes, ranks them, explains trade-offs, and leaves the driver in control. BrokerBrief works the same way — the final commercial decision always belongs to the professional.

---

## First decision module: Bunkering Strategy

**Scenario:** A vessel must determine where and when to bunker between Singapore and Fujairah.

The user enters a minimal vessel scenario (fuel remaining, consumption, ETAs, required stem, schedule flexibility). BrokerBrief:

1. **Generates** the realistic bunkering strategies automatically (full Singapore, partial + top-up, delay to Fujairah)
2. **Removes** infeasible options via the deterministic **Constraint Engine** — with the exact rule and reason shown
3. **Scores** feasible options via the transparent **Commercial Evaluation Engine** (weights visible, configurable by risk profile)
4. **Quantifies** certainty via the **Confidence Model** (Data Quality / Signal Agreement / Scenario Completeness)
5. **Presents** everything in a **Decision Workspace**: recommended option, alternatives, trade-off table, reasoning, assumptions, and data provenance

---

## Architecture

```
User Scenario
      │
      ▼
Constraint Engine        deterministic feasibility rules (fuel safety,
      │                  schedule, availability, stem limits, ECA/regulatory)
      ▼
Option Generator         creates only commercially realistic alternatives
      │
      ▼
Commercial Evaluation    weighted transparent scoring
      │                  (expected cost / operational risk / schedule risk)
      ▼
Confidence Model         Data Quality + Signal Agreement + Scenario Completeness
      │
      ▼
Decision Workspace       recommendation · trade-offs · evidence · assumptions
```

There is **no AI in the decision pipeline**. The commercial logic is rules-based, explicit, and traceable — every recommendation can be traced to a named rule, a visible weight, or an attributed data source.

## Data principles

**No source, no certainty.** Every input is labelled by provenance:

| Label | Meaning |
|-------|---------|
| `LIVE` | EIA Brent spot + forecast (API) · IMF Portwatch congestion (API) |
| `MANUAL` | Bunker/freight prices from curated CSV |
| `USER-PROVIDED` | Scenario inputs |
| `MISSING` | Flagged openly — never invented |

Missing data **lowers confidence but does not remove physically feasible options** — exactly how professionals actually work.

---

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Optional: paste a free [EIA API key](https://www.eia.gov/opendata/) in the sidebar for live Brent data. Portwatch needs no key.

## Demo scenarios (built in)

| | Setup | Expected behaviour |
|--|-------|-------------------|
| **1** | Fuel 900 MT, both ports reachable | All options ranked; High confidence |
| **2** | Fuel 280 MT, Fujairah 8 days away | Fujairah removed — Rule F1 with explicit fuel shortfall shown |
| **3** | Fujairah price simulated missing | Fujairah retained (physically feasible), confidence drops to Medium, gap shown |

Load them from the "📌 Load a demo scenario" expander on the Bunkering Strategy page.

## Project structure

```
app.py                          entry point: homepage → decision module → market intelligence
modules/
  data.py · signals.py · brief.py · bunker.py · report.py · pdf_export.py
  eia.py · portwatch.py         live data feeds
  decision/
    scenario.py                 scenario dataclass + completeness scoring
    options.py                  option generator
    constraint_engine.py        Layer 1 — feasibility rules (F1–F3, S1–S2, P1–P2, C1, R1)
    evaluation_engine.py        Layer 2 — weighted commercial scoring
    confidence_model.py         Layer 3 — three-component confidence
    market_data.py              provenance-labelled data assembly
```

## Roadmap

- [ ] Supplier Quote Evaluation module
- [ ] Port Selection Analysis module
- [ ] Live bunker price feed (currently manual CSV)
- [ ] Port database (draft limits, berth data, stem sizes, bunkering windows)
- [ ] Scoring weight validation via expert interviews

---

*BrokerBrief is a student-stage project. Recommendations are indicative, built on transparent rules and source-backed data, and support — never replace — professional judgement.*
