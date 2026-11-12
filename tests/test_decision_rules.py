"""
tests/test_decision_rules.py

Portfolio-mode credibility fixes to the decision engine (12-11-2026):

- R1 is a scrubber rule from MARPOL Annex VI regulations 14.1 and 4.1, not a
  rule about the port; R2 and R3 are warnings that remove nothing.
- Prices follow the selected fuel grade; another grade's price is never used.
- Freshness is judged against each source's own limit, so a weekly EIA
  release is not penalised for being a few days old.
- A missing price caps confidence at Medium; no price at all caps it at Low.
"""

import unittest
from datetime import datetime, timedelta, timezone

from modules.data import demo_eia_data, demo_portwatch_data, load_data
from modules.decision.confidence_model import (
    LOW_CAP, MEDIUM_CAP, STALE_DEDUCTION, compute_confidence, compute_data_quality,
)
from modules.decision.constraint_engine import run_constraint_engine
from modules.decision.evaluation_engine import score_options
from modules.decision.market_data import assemble_market_data
from modules.decision.options import generate_options
from modules.decision.scenario import BunkeringScenario, FuelGrade, Scrubber
from modules.eia import EIA_SPOT
from modules.portwatch import PORTWATCH
from modules.provenance import EIA_SPOT_MAX_AGE, PORTWATCH_MAX_AGE, stamp

NOW = datetime(2026, 11, 12, 6, 0, tzinfo=timezone.utc)
BOTH = {"Singapore", "Fujairah"}


def scenario(**overrides) -> BunkeringScenario:
    base = dict(
        vessel_name="MT Test", current_location="Zhoushan", destination="Ras Tanura",
        fuel_remaining_mt=900.0, daily_consumption_mt=45.0, required_quantity_mt=1000.0,
        fuel_grade=FuelGrade.VLSFO, eta_singapore_days=1.0, eta_fujairah_days=11.5,
        schedule_flexibility_hours=36.0,
    )
    base.update(overrides)
    return BunkeringScenario(**base)


def constrained(sc: BunkeringScenario):
    return run_constraint_engine(generate_options(sc), sc, {"Singapore": "Stable", "Fujairah": "Stable"})


def live_market(*, brent_age_days=0, portwatch_age_days=0, df=None, **kwargs) -> dict:
    """Market data shaped like a live run: EIA and PortWatch provenance with a
    chosen age, and whatever price rows `df` holds (none by default)."""
    eia, portwatch = demo_eia_data(), demo_portwatch_data()
    eia["spot"]["provenance"] = stamp(EIA_SPOT, as_of=NOW - timedelta(days=brent_age_days))
    portwatch["provenance"] = stamp(PORTWATCH, as_of=NOW - timedelta(days=portwatch_age_days))
    return assemble_market_data(df if df is not None else load_data("none"), eia, portwatch, **kwargs)


class SulphurRuleR1(unittest.TestCase):
    def test_hsfo_without_scrubber_removes_every_option_at_every_port(self):
        options = constrained(scenario(fuel_grade=FuelGrade.HSFO, scrubber=Scrubber.NONE))
        self.assertTrue(options)
        for option in options:
            self.assertFalse(option.is_feasible, option.id)
            self.assertEqual(option.infeasible_rule, "R1")
            self.assertIn("regulation 14.1", option.infeasible_reason)
            self.assertIn("regulation 4.1", option.infeasible_reason)

    def test_reason_is_about_the_ship_not_the_port(self):
        option = constrained(scenario(fuel_grade=FuelGrade.HSFO))[0]
        self.assertNotIn("is not permitted in", option.infeasible_reason)
        self.assertIn("carrying it for use", option.infeasible_reason)

    def test_hsfo_with_a_scrubber_is_feasible(self):
        for fitted in (Scrubber.OPEN_LOOP, Scrubber.CLOSED_OR_HYBRID):
            with self.subTest(scrubber=fitted):
                options = constrained(scenario(fuel_grade=FuelGrade.HSFO, scrubber=fitted))
                self.assertTrue(all(o.is_feasible for o in options))

    def test_compliant_grades_never_trigger_r1(self):
        for grade in (FuelGrade.VLSFO, FuelGrade.MGO):
            with self.subTest(grade=grade):
                self.assertTrue(all(o.infeasible_rule != "R1" for o in constrained(scenario(fuel_grade=grade))))

    def test_ifo380_is_not_a_separate_grade(self):
        self.assertEqual([g.value for g in FuelGrade], ["VLSFO", "MGO", "HSFO"])


class OpenLoopWarningR2(unittest.TestCase):
    def test_open_loop_scrubber_warns_at_both_ports_and_removes_nothing(self):
        options = constrained(scenario(fuel_grade=FuelGrade.HSFO, scrubber=Scrubber.OPEN_LOOP))
        for option in options:
            self.assertTrue(option.is_feasible)
            self.assertTrue(option.is_warning)
            self.assertIn("open-loop scrubber wash-water discharge", option.warning_message)
        partial = next(o for o in options if o.is_partial)
        self.assertIn("Singapore and Fujairah prohibit open-loop", partial.warning_message)

    def test_closed_loop_scrubber_gets_no_open_loop_warning(self):
        options = constrained(scenario(fuel_grade=FuelGrade.HSFO, scrubber=Scrubber.CLOSED_OR_HYBRID))
        self.assertFalse(any("open-loop" in (o.warning_message or "") for o in options))


class EcaWarningR3(unittest.TestCase):
    def test_no_eca_no_warning(self):
        self.assertFalse(any("emission control area" in (o.warning_message or "")
                             for o in constrained(scenario())))

    def test_vlsfo_into_an_eca_warns_and_removes_nothing(self):
        options = constrained(scenario(voyage_enters_eca=True))
        for option in options:
            self.assertTrue(option.is_feasible)
            self.assertIn("regulation 14.4", option.warning_message)
            self.assertIn("0.10% sulphur", option.warning_message)

    def test_each_grade_gets_its_own_wording(self):
        vlsfo = constrained(scenario(voyage_enters_eca=True))[0].warning_message
        hsfo = constrained(scenario(voyage_enters_eca=True, fuel_grade=FuelGrade.HSFO,
                                    scrubber=Scrubber.CLOSED_OR_HYBRID))[0].warning_message
        mgo = constrained(scenario(voyage_enters_eca=True, fuel_grade=FuelGrade.MGO))[0].warning_message
        self.assertIn("cannot be burned there", vlsfo)
        self.assertIn("scrubber is approved as equivalent", hsfo)
        self.assertIn("bunker delivery note", mgo)


class PricesFollowTheGrade(unittest.TestCase):
    def test_each_grade_reads_its_own_demo_rows(self):
        expected = {"VLSFO": (615.0, 598.0), "MGO": (855.0, 872.0), "HSFO": (482.0, 471.0)}
        for grade, (singapore, fujairah) in expected.items():
            with self.subTest(grade=grade):
                market = assemble_market_data(load_data("sample"), None, None, fuel_grade=grade)
                self.assertEqual(market["bunker_prices"]["Singapore"]["price"], singapore)
                self.assertEqual(market["bunker_prices"]["Fujairah"]["price"], fujairah)
                self.assertIn(f"Singapore {grade}", market["provenance"])

    def test_another_grades_price_is_never_substituted(self):
        df = load_data("sample")
        df = df[df["market_segment"] != "MGO"]
        market = assemble_market_data(df, None, None, fuel_grade="MGO")
        self.assertEqual(market["bunker_prices"], {"Singapore": {}, "Fujairah": {}})
        self.assertIsNone(market["provenance"]["Singapore MGO"])

    def test_user_entered_prices_are_used_and_labelled(self):
        market = assemble_market_data(load_data("none"), None, None,
                                      singapore_price_override=600.0, fujairah_price_override=590.0)
        self.assertEqual(market["bunker_prices"]["Singapore"], {"price": 600.0})
        self.assertEqual(market["provenance"]["Fujairah VLSFO"].source_name, "User override")

    def test_cost_note_names_the_selected_grade(self):
        sc = scenario(fuel_grade=FuelGrade.MGO)
        market = assemble_market_data(load_data("sample"), demo_eia_data(), demo_portwatch_data(), fuel_grade="MGO")
        options = score_options(constrained(sc), sc, market)
        note = options[0]._score_breakdown["expected_cost"]["note"]
        self.assertIn("MGO", note)
        self.assertNotIn("VLSFO", note)


class FreshnessUsesEachSourcesLimit(unittest.TestCase):
    def test_week_old_brent_is_not_penalised(self):
        # EIA releases daily prices weekly, so 4–9 days old is normal.
        for age in (0, 3, 6, EIA_SPOT_MAX_AGE.days):
            with self.subTest(age=age):
                quality = compute_data_quality(live_market(brent_age_days=age), NOW)
                self.assertFalse(any("Brent spot" in f and "stale" in f for f in quality["factors"]))

    def test_brent_past_its_limit_is_stale(self):
        fresh = compute_data_quality(live_market(brent_age_days=3), NOW)["score"]
        stale = compute_data_quality(live_market(brent_age_days=EIA_SPOT_MAX_AGE.days + 1), NOW)
        self.assertEqual(stale["score"], fresh - STALE_DEDUCTION)
        self.assertTrue(any("EIA Brent spot is 11 days old" in f for f in stale["factors"]))

    def test_portwatch_has_an_age_check_with_a_14_day_limit(self):
        self.assertEqual(PORTWATCH_MAX_AGE.days, 14)
        ok = compute_data_quality(live_market(portwatch_age_days=10), NOW)
        stale = compute_data_quality(live_market(portwatch_age_days=15), NOW)
        self.assertEqual(stale["score"], ok["score"] - STALE_DEDUCTION)
        self.assertTrue(any("PortWatch" in f and "stale" in f for f in stale["factors"]))

    def test_user_entered_price_has_no_age_to_judge(self):
        market = live_market(singapore_price_override=600.0, fujairah_price_override=590.0)
        quality = compute_data_quality(market, NOW)
        self.assertFalse(any("price" in f for f in quality["factors"]))


class MissingPriceCaps(unittest.TestCase):
    def test_all_prices_present_is_not_capped(self):
        market = live_market(df=load_data("sample"))
        conf = compute_confidence(scenario(), market, scored_ports=BOTH, now=NOW)
        self.assertIsNone(conf["cap_reason"])

    def test_one_missing_price_caps_at_medium(self):
        market = live_market(df=load_data("sample"), simulate_fujairah_missing=True)
        conf = compute_confidence(scenario(), market, scored_ports=BOTH, now=NOW)
        self.assertGreaterEqual(conf["uncapped_overall"], 80)
        self.assertEqual((conf["label"], conf["overall"]), ("Medium", MEDIUM_CAP))
        self.assertIn("No VLSFO price for Fujairah", conf["cap_reason"])

    def test_no_prices_at_all_caps_at_low(self):
        # A live run with nothing entered: Brent and PortWatch are fine, but
        # the engine has no price for either port.
        conf = compute_confidence(scenario(), live_market(brent_age_days=6), scored_ports=BOTH, now=NOW)
        self.assertGreaterEqual(conf["uncapped_overall"], 60)       # would have read Medium
        self.assertEqual((conf["label"], conf["overall"]), ("Low", LOW_CAP))
        self.assertIn("cannot weigh cost", conf["cap_reason"])

    def test_missing_price_at_an_unscored_port_does_not_cap(self):
        market = live_market(df=load_data("sample"), simulate_fujairah_missing=True)
        conf = compute_confidence(scenario(), market, scored_ports={"Singapore"}, now=NOW)
        self.assertIsNone(conf["cap_reason"])

    def test_a_low_score_is_left_alone_by_the_caps(self):
        market = live_market(df=load_data("sample"), simulate_fujairah_missing=True)
        market["brent_available"] = market["forecast_available"] = market["portwatch_available"] = False
        market["congestion_signals"] = {}
        conf = compute_confidence(scenario(), market, scored_ports=BOTH, now=NOW)
        self.assertLess(conf["uncapped_overall"], MEDIUM_CAP)
        self.assertEqual(conf["overall"], conf["uncapped_overall"])      # the Medium cap did not bite
        self.assertIsNotNone(conf["cap_reason"])


def csv_rows(*rows):
    """Bunker rows shaped like an uploaded CSV: (port, segment, current, previous, updated_at)."""
    import pandas as pd
    from modules.data import REQUIRED_COLUMNS
    return pd.DataFrame([
        {"date": "2026-11-12", "signal_type": "bunker", "market_segment": segment, "route_or_port": port,
         "current_value": current, "previous_value": previous, "unit": "USD/MT", "source_name": "My quotes",
         "source_url": None, "updated_at": updated, "confidence": 0.9, "notes": ""}
        for port, segment, current, previous, updated in rows], columns=REQUIRED_COLUMNS)


class GradeMatchingIsExact(unittest.TestCase):
    def prices(self, df, grade):
        return assemble_market_data(df, None, None, fuel_grade=grade)["bunker_prices"]

    def test_lookalike_segments_are_never_read_as_another_grade(self):
        df = csv_rows(("Singapore", "ULSFO", 700, 690, "2026-11-12"),          # contains "LSFO"
                      ("Singapore", "VLSFO 380CST", 650, 640, "2026-11-12"),   # contains "380CST"
                      ("Singapore", "VLSFO IFO380", 651, 641, "2026-11-12"),
                      ("Singapore", "LSMGO", 900, 890, "2026-11-12"),          # contains "MGO"
                      ("Singapore", "380CST", 480, 470, "2026-11-12"))         # viscosity only
        for grade in ("VLSFO", "MGO", "HSFO"):
            with self.subTest(grade=grade):
                self.assertEqual(self.prices(df, grade)["Singapore"], {})

    def test_listed_aliases_and_spacing_and_case_are_accepted(self):
        df = csv_rows(("singapore", " vlsfo  0.5% ", 615, 632, "2026-11-12"),
                      ("FUJAIRAH", "Ifo380", 471, 486, "2026-11-12"))
        self.assertEqual(self.prices(df, "VLSFO")["Singapore"]["price"], 615.0)
        self.assertEqual(self.prices(df, "HSFO")["Fujairah"]["price"], 471.0)


class OnlyRealPricesCount(unittest.TestCase):
    def test_zero_blank_negative_and_text_are_not_prices(self):
        for bad in (0, float("nan"), -5, "n/a", None):
            with self.subTest(value=bad):
                df = csv_rows(("Singapore", "VLSFO", bad, 600, "2026-11-12"),
                              ("Fujairah", "VLSFO", 600, 590, "2026-11-12"))
                market = live_market(df=df)
                self.assertEqual(market["bunker_prices"]["Singapore"], {})
                self.assertIsNone(market["provenance"]["Singapore VLSFO"])
                sc = scenario()
                score_options(constrained(sc), sc, market)              # must not raise
                conf = compute_confidence(sc, market, scored_ports=BOTH, now=NOW)
                self.assertIn("No VLSFO price for Singapore", conf["cap_reason"])

    def test_zero_override_is_ignored(self):
        market = assemble_market_data(load_data("none"), None, None, fujairah_price_override=0.0)
        self.assertEqual(market["bunker_prices"]["Fujairah"], {})

    def test_bad_previous_value_keeps_the_price_but_drops_the_comparison(self):
        df = csv_rows(("Singapore", "VLSFO", 615, "", "2026-11-12"))
        self.assertEqual(assemble_market_data(df, None, None)["bunker_prices"]["Singapore"], {"price": 615.0})


class RowChoiceAndOverrides(unittest.TestCase):
    def test_latest_dated_row_wins_whatever_its_position(self):
        df = csv_rows(("Singapore", "VLSFO", 620, 610, "2026-11-12"),
                      ("Singapore", "VLSFO", 580, 570, "2026-10-01"),
                      ("Singapore", "VLSFO", 999, 990, "not a date"))
        self.assertEqual(assemble_market_data(df, None, None)["bunker_prices"]["Singapore"]["price"], 620.0)

    def test_typed_price_beats_csv_and_simulate_flag_beats_both(self):
        df = csv_rows(("Fujairah", "VLSFO", 598, 612, "2026-11-12"))
        typed = assemble_market_data(df, None, None, fujairah_price_override=555.0)
        self.assertEqual(typed["bunker_prices"]["Fujairah"], {"price": 555.0})
        simulated = assemble_market_data(df, None, None, fujairah_price_override=555.0,
                                         simulate_fujairah_missing=True)
        self.assertEqual(simulated["bunker_prices"]["Fujairah"], {})


class ManualPriceFreshness(unittest.TestCase):
    def test_csv_price_older_than_48_hours_is_stale(self):
        from modules.provenance import MANUAL_ENTRY_MAX_AGE
        self.assertEqual(MANUAL_ENTRY_MAX_AGE, timedelta(hours=48))
        fresh = csv_rows(("Singapore", "VLSFO", 615, 632, "2026-11-11"), ("Fujairah", "VLSFO", 598, 612, "2026-11-11"))
        old = csv_rows(("Singapore", "VLSFO", 615, 632, "2026-11-09"), ("Fujairah", "VLSFO", 598, 612, "2026-11-11"))
        fresh_q = compute_data_quality(live_market(df=fresh), NOW)
        old_q = compute_data_quality(live_market(df=old), NOW)
        self.assertEqual(old_q["score"], fresh_q["score"] - STALE_DEDUCTION)
        self.assertTrue(any("Singapore VLSFO price" in f and "stale" in f for f in old_q["factors"]))

    def test_day_month_year_dates_are_read(self):
        from modules.provenance import parse_as_of
        self.assertEqual(parse_as_of("12/11/2026"), datetime(2026, 11, 12, tzinfo=timezone.utc))
        self.assertEqual(parse_as_of("12-11-2026"), datetime(2026, 11, 12, tzinfo=timezone.utc))
        self.assertIsNone(parse_as_of("13/13/2026"))

    def test_naive_now_is_taken_as_utc(self):
        compute_data_quality(live_market(), NOW.replace(tzinfo=None))      # must not raise


class RulePrecedenceAndWording(unittest.TestCase):
    def test_r2_names_one_port_for_a_single_port_option(self):
        options = constrained(scenario(fuel_grade=FuelGrade.HSFO, scrubber=Scrubber.OPEN_LOOP))
        full_sg = next(o for o in options if o.id == "SGP_FULL")
        self.assertIn("Singapore prohibits open-loop", full_sg.warning_message)

    def test_vlsfo_with_a_scrubber_gets_the_conditional_eca_wording(self):
        message = constrained(scenario(voyage_enters_eca=True, scrubber=Scrubber.CLOSED_OR_HYBRID))[0].warning_message
        self.assertIn("only if the scrubber is approved", message)
        self.assertNotIn("cannot be burned there", message)

    def test_fuel_shortfall_is_reported_before_the_sulphur_rule(self):
        # First violated rule is shown: a ship that cannot reach the port gets F1.
        options = constrained(scenario(fuel_grade=FuelGrade.HSFO, fuel_remaining_mt=50.0))
        self.assertEqual({o.infeasible_rule for o in options}, {"F1"})


class ReadmeFiguresMatchCode(unittest.TestCase):
    """Figures the README states, pinned so a code change cannot leave it wrong."""

    def test_weights_waits_and_bunkering_hours(self):
        from modules.decision.constraint_engine import (
            CONGESTION_WAIT_HOURS, PORT_BUNKERING_TIME_HOURS, UNKNOWN_CONGESTION_WAIT_HOURS)
        from modules.decision.evaluation_engine import WEIGHT_SETS
        from modules.decision.scenario import RiskProfile
        self.assertEqual({p.value: tuple(w.values()) for p, w in WEIGHT_SETS.items()}, {
            "Conservative": (0.30, 0.45, 0.25), "Balanced": (0.40, 0.35, 0.25), "Cost-focused": (0.60, 0.25, 0.15)})
        self.assertEqual(CONGESTION_WAIT_HOURS, {"Rising": 18.0, "Stable": 8.0, "Easing": 4.0})
        self.assertEqual(UNKNOWN_CONGESTION_WAIT_HOURS, 8.0)
        self.assertEqual(PORT_BUNKERING_TIME_HOURS, {"Singapore": 8.0, "Fujairah": 10.0})

    def test_caps_thresholds_and_limits(self):
        from modules.provenance import MANUAL_ENTRY_MAX_AGE
        self.assertEqual((MEDIUM_CAP, LOW_CAP, STALE_DEDUCTION), (79.0, 59.0, 15.0))
        self.assertEqual((EIA_SPOT_MAX_AGE.days, PORTWATCH_MAX_AGE.days), (10, 14))
        self.assertEqual(MANUAL_ENTRY_MAX_AGE, timedelta(hours=48))

    def test_rule_counts_six_removals_four_warnings(self):
        import inspect
        from modules.decision import constraint_engine
        source = inspect.getsource(constraint_engine)
        removals = {r for r in ("F1", "F2", "C1", "P1", "R1", "S1") if f'"{r}"' in source}
        self.assertEqual(len(removals), 6)
        warnings = [name for name in ("_schedule_check", "_departure_reserve_warning",
                                      "_open_loop_warning", "_eca_warning") if hasattr(constraint_engine, name)]
        self.assertEqual(len(warnings), 4)

    def test_three_optional_inputs_drive_completeness(self):
        fields = scenario().completeness_score()["fields"]
        always = {k for k, v in fields.items() if v}
        self.assertEqual(set(fields) - always,
                         {"Safety reserve", "Singapore fuel availability", "Fujairah fuel availability"})


if __name__ == "__main__":
    unittest.main()
