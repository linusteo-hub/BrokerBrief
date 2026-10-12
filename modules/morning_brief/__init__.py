"""
modules/morning_brief

The public daily morning brief. Deterministic code fetches, validates and
assembles a JSON payload; a language model (Phase 2) only writes prose from it.

Architecture rule: nothing in this package may import from modules.decision.
It may read from the ingestion layer (modules.eia, modules.portwatch).
"""
