"""
modules/decision/scenario.py

Data structures for vessel bunkering scenarios.
Keeps scenario representation clean and separate from UI and engine logic.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class FuelGrade(str, Enum):
    VLSFO = "VLSFO"
    MGO   = "MGO"
    IFO380 = "IFO380"
    HSFO  = "HSFO"


class RiskProfile(str, Enum):
    CONSERVATIVE = "Conservative"
    BALANCED     = "Balanced"
    COST_FOCUSED = "Cost-focused"


class FuelAvailability(str, Enum):
    AVAILABLE   = "Available"
    UNAVAILABLE = "Unavailable"
    UNKNOWN     = "Unknown"


@dataclass
class BunkeringScenario:
    """
    Minimum required inputs to evaluate a bunkering decision.
    Optional fields improve confidence but are not required to run.
    """
    # ── Core inputs (required) ────────────────────────────────────────────────
    vessel_name: str                        # For display purposes
    current_location: str                   # Starting port or position
    destination: str                        # Final destination port
    fuel_remaining_mt: float                # MT of fuel currently on board
    daily_consumption_mt: float             # Estimated MT/day consumption
    required_quantity_mt: float             # MT needed to bunker
    fuel_grade: FuelGrade                   # VLSFO / MGO / IFO380 / HSFO
    eta_singapore_days: float               # Days until Singapore arrival
    eta_fujairah_days: float                # Days until Fujairah arrival
    schedule_flexibility_hours: float       # Hours of acceptable delay

    # ── Safety reserve ────────────────────────────────────────────────────────
    # Default: 10% of remaining voyage consumption or 24h of fuel (whichever larger)
    # User may override. No universal industry standard — reflects company SMS.
    safety_reserve_mt: Optional[float] = None   # If None, calculated from default

    # ── Port availability (manual for POC) ───────────────────────────────────
    singapore_vlsfo_available: FuelAvailability = FuelAvailability.UNKNOWN
    fujairah_vlsfo_available: FuelAvailability  = FuelAvailability.UNKNOWN

    # ── Optional inputs (increase confidence when provided) ──────────────────
    risk_profile: RiskProfile = RiskProfile.BALANCED
    preferred_supplier: Optional[str] = None
    notes: Optional[str] = None

    def effective_safety_reserve_mt(self) -> float:
        """
        Returns the effective safety reserve in MT.
        If user-defined, use that. Otherwise apply default:
        max(10% of remaining voyage fuel, 24h of consumption).
        """
        if self.safety_reserve_mt is not None:
            return self.safety_reserve_mt
        reserve_10pct = self.fuel_remaining_mt * 0.10
        reserve_24h   = self.daily_consumption_mt
        return max(reserve_10pct, reserve_24h)

    def fuel_to_reach_singapore_mt(self) -> float:
        """Estimated fuel needed to reach Singapore (MT)."""
        return self.eta_singapore_days * self.daily_consumption_mt

    def fuel_to_reach_fujairah_mt(self) -> float:
        """Estimated fuel needed to reach Fujairah (MT)."""
        return self.eta_fujairah_days * self.daily_consumption_mt

    def can_reach_singapore_with_reserve(self) -> bool:
        required = self.fuel_to_reach_singapore_mt() + self.effective_safety_reserve_mt()
        return self.fuel_remaining_mt >= required

    def can_reach_fujairah_with_reserve(self) -> bool:
        required = self.fuel_to_reach_fujairah_mt() + self.effective_safety_reserve_mt()
        return self.fuel_remaining_mt >= required

    def completeness_score(self) -> dict:
        """
        Returns which fields are provided vs missing.
        Used by the Confidence Model (Scenario Completeness component).
        """
        fields = {
            "Fuel remaining (MT)":      self.fuel_remaining_mt is not None,
            "Daily consumption":        self.daily_consumption_mt is not None,
            "Required quantity":        self.required_quantity_mt is not None,
            "Fuel grade":               self.fuel_grade is not None,
            "ETA Singapore":            self.eta_singapore_days is not None,
            "ETA Fujairah":             self.eta_fujairah_days is not None,
            "Schedule flexibility":     self.schedule_flexibility_hours is not None,
            "Safety reserve":           self.safety_reserve_mt is not None,
            "Singapore fuel availability": self.singapore_vlsfo_available != FuelAvailability.UNKNOWN,
            "Fujairah fuel availability":  self.fujairah_vlsfo_available != FuelAvailability.UNKNOWN,
        }
        provided = sum(fields.values())
        total    = len(fields)
        score    = round((provided / total) * 100)
        return {
            "score":    score,
            "fields":   fields,
            "provided": provided,
            "total":    total,
        }
