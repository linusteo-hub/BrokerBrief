"""
modules/decision/options.py

Option Generator — Layer 2 of the BrokerBrief decision pipeline.
Generates commercially realistic bunkering alternatives from the vessel scenario.
Does NOT evaluate or score — that is the Evaluation Engine's job.
Does NOT filter feasibility — that is the Constraint Engine's job.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from modules.decision.scenario import BunkeringScenario


@dataclass
class BunkeringOption:
    """
    A single candidate bunkering strategy.
    Generated before feasibility filtering.
    """
    id: str                         # e.g. "SGP_FULL", "SGP_PARTIAL", "FUJ_FULL"
    label: str                      # Short name: "Full bunker — Singapore"
    description: str                # One sentence explanation of the strategy
    port: str                       # Primary bunkering port
    quantity_mt: float              # Proposed bunker quantity in MT
    is_partial: bool = False        # True if vessel tops up later
    top_up_port: Optional[str] = None  # Port for second stem if partial

    # Set by Constraint Engine — not generated here
    is_feasible: bool = True
    infeasible_reason: Optional[str] = None
    infeasible_rule: Optional[str] = None
    is_warning: bool = False
    warning_message: Optional[str] = None

    # Set by Evaluation Engine
    score: Optional[float] = None
    rank: Optional[int] = None

    # Set by Confidence Model
    confidence: Optional[float] = None


def generate_options(scenario: BunkeringScenario) -> List[BunkeringOption]:
    """
    Generates the candidate bunkering strategies for a given scenario.

    BrokerBrief generates the options — the user does not define them.
    This ensures even junior users see all commercially realistic alternatives.

    For the Singapore–Fujairah corridor, standard options are:
    1. Full bunker in Singapore
    2. Partial bunker in Singapore, top up at Fujairah
    3. Minimum safety bunker in Singapore, full stem at Fujairah
    4. Full bunker in Fujairah (delay)
    """
    options: List[BunkeringOption] = []

    qty = scenario.required_quantity_mt
    # Partial stem: bunker enough to comfortably reach Fujairah plus working margin.
    # Floor at 200 MT (typical port minimum stem) so the option is commercially
    # executable — a partial below the port minimum would always fail Rule F2.
    MIN_PARTIAL_STEM = 200.0
    partial_need = round(
        (scenario.fuel_to_reach_fujairah_mt() - scenario.fuel_remaining_mt
         + scenario.effective_safety_reserve_mt() * 1.2), 1
    )
    partial_qty = max(MIN_PARTIAL_STEM, min(max(partial_need, 0.0), qty * 0.6))

    # ── Option 1: Full bunker — Singapore ────────────────────────────────────
    options.append(BunkeringOption(
        id          = "SGP_FULL",
        label       = "Full bunker — Singapore",
        description = (
            f"Bunker the full required quantity ({qty:,.0f} MT) in Singapore. "
            "Avoids any fuel uncertainty on the Fujairah leg."
        ),
        port        = "Singapore",
        quantity_mt = qty,
    ))

    # ── Option 2: Partial bunker — Singapore, top up at Fujairah ────────────
    if partial_qty > 50:  # Only offer if top-up is commercially meaningful
        options.append(BunkeringOption(
            id          = "SGP_PARTIAL",
            label       = "Partial bunker — Singapore, top up Fujairah",
            description = (
                f"Bunker {partial_qty:,.0f} MT in Singapore to cover the Fujairah leg safely, "
                f"then take the remaining stem ({qty - partial_qty:,.0f} MT) at Fujairah."
            ),
            port         = "Singapore",
            quantity_mt  = partial_qty,
            is_partial   = True,
            top_up_port  = "Fujairah",
        ))

    # ── Option 3: Full bunker — Fujairah ────────────────────────────────────
    options.append(BunkeringOption(
        id          = "FUJ_FULL",
        label       = "Full bunker — Fujairah",
        description = (
            f"Delay bunkering and take the full stem ({qty:,.0f} MT) at Fujairah. "
            "May offer price advantage if market conditions are favourable."
        ),
        port        = "Fujairah",
        quantity_mt = qty,
    ))

    return options
