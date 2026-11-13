"""
modules/morning_brief

The public daily morning brief. Deterministic code fetches, validates and
assembles a JSON payload and writes the brief from it. A language model can
add news summaries, but is off by default (Decision Batch 2: no spending).

Architecture rule: nothing in this package may import from modules.decision.
It may read from the ingestion layer (modules.eia, modules.portwatch).
"""
