"""Tests real preserved issuer identities without inventing trade plans."""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_current_issuer_research_review import SOURCE, build_reviews, assess_private_capital_capacity, render_research_brief


class CurrentIssuerResearchReviewTests(unittest.TestCase):
    def setUp(self):
        self.source_bytes = SOURCE.read_bytes()
        self.source = json.loads(self.source_bytes)

    def test_real_research_review_has_no_synthetic_risk_and_no_buy(self):
        result = build_reviews(self.source_bytes)
        self.assertEqual(result["schema"], "V29_REAL_ISSUER_RESEARCH_REVIEW_V1")
        self.assertEqual(result["research_as_of"], "2026-10-30")
        self.assertFalse(result["trade_authorized"])
        self.assertFalse(result["synthetic_risk_fields_used"])
        self.assertEqual(result["live_buy_eligibility"], "NOT_AUTHORIZED")
        cases = {item["security_id"]: item for item in result["cases"]}
        self.assertEqual(set(cases), {"SZSE:300408", "SSE:688002"})
        self.assertEqual(cases["SZSE:300408"]["observed_reference_price_cny"], 84.54)
        self.assertEqual(cases["SSE:688002"]["observed_reference_price_cny"], 139.03)
        for case in cases.values():
            self.assertEqual(case["quote_session"], "2026-10-29")
            self.assertIsNone(case["human_stop_take_profit_position_size"])
            self.assertIsNone(case["decision_packet"])
            self.assertIsNone(case["contemplated_action"])
            self.assertFalse(case["buy_add_authorized"])
            self.assertFalse(case["strategy_alpha_and_untouched_oos_verified"])
            self.assertTrue(case["source_urls"]["report"].startswith("https://"))

    def test_frozen_122_real_financial_selection_and_quote_timing(self):
        result = build_reviews(self.source_bytes)
        cases = {x["security_id"]: x for x in result["cases"]}
        self.assertEqual(len(result["frozen_cohort_financial_source_hashes"]), 2)
        self.assertTrue(result["frozen_cohort_preoutcome_snapshot_not_current_market"])
        expected = {
            "SZSE:300408": (76.7385401831, 54.824030357, "2026-10-29", True),
            "SSE:688002": (82.2200585456, 72.8372056798, "2026-10-27", False),
        }
        for sid, (revenue_q3, revenue_h1, disclosed, same_day) in expected.items():
            row = cases[sid]
            self.assertEqual(row["frozen_cohort_membership"], "SELECTED_122_RESEARCH_ONLY")
            self.assertAlmostEqual(row["q3_ytd_revenue_yoy_pct"], revenue_q3)
            self.assertAlmostEqual(row["h1_ytd_revenue_yoy_pct"], revenue_h1)
            self.assertAlmostEqual(row["revenue_growth_acceleration_pp"], revenue_q3 - revenue_h1)
            self.assertEqual(row["q3_report_disclosure_date"], disclosed)
            self.assertIs(row["quote_and_report_same_calendar_day_release_order_unverified"], same_day)
            self.assertFalse(row["financial_data_original_publication_vintage_independently_certified"])
            self.assertIsNone(row["decision_packet"])
            self.assertFalse(row["buy_add_authorized"])

    def test_research_only_source_cannot_be_promoted_by_editing_status(self):
        altered = copy.deepcopy(self.source)
        altered["buy_eligibility"] = "AUTHORIZED"
        with self.assertRaisesRegex(ValueError, "SOURCE_RESEARCH_ONLY"):
            build_reviews(json.dumps(altered).encode())
        altered = copy.deepcopy(self.source)
        altered["independent_alpha_evidence"] = True
        with self.assertRaisesRegex(ValueError, "SOURCE_RESEARCH_ONLY"):
            build_reviews(json.dumps(altered).encode())

    def test_quote_date_and_duplicate_identity_rejected(self):
        altered = copy.deepcopy(self.source)
        altered["cases"][0]["quote_asof_beijing"] = "2026-11-02 15:00"
        with self.assertRaisesRegex(ValueError, "QUOTE_DATE_SOURCE"):
            build_reviews(json.dumps(altered).encode())
        altered = copy.deepcopy(self.source)
        altered["cases"][1]["security_id"] = "SZSE:300408"
        with self.assertRaisesRegex(ValueError, "UNEXPECTED_OR_DUPLICATED"):
            build_reviews(json.dumps(altered).encode())

    def test_hash_binds_original_bytes_and_is_deterministic(self):
        a = build_reviews(self.source_bytes)
        b = build_reviews(self.source_bytes)
        self.assertEqual(a, b)
        import hashlib
        self.assertEqual(a["financial_research_source_sha256"],
                         hashlib.sha256(self.source_bytes).hexdigest())


    def test_plain_language_brief_uses_only_source_bound_historical_observations(self):
        research = build_reviews(self.source_bytes)
        brief = render_research_brief(research)
        self.assertIn("三环集团", brief)
        self.assertIn("睿创微纳", brief)
        self.assertIn("2026-10-29", brief)
        self.assertIn(research["financial_research_source_sha256"], brief)
        self.assertIn("NO BUY / NO ADD", brief)
        self.assertIn("先后顺序未核实", brief)
        self.assertIn("NOT_AUTHORIZED", brief)
        self.assertIn("非事前盲选", brief)
        self.assertIn("不能替代公告原件核验", brief)
        self.assertIn("V2.9_TWO_ISSUER_ORIGINAL_DISCLOSURE_CHECK_20261107.md", brief)
        self.assertIn("后补来源只能改进证据说明", brief)
        self.assertIn("时序仍未认证", brief)
        self.assertNotIn("建议买入", brief)
        self.assertEqual(brief, render_research_brief(research))

    def test_plain_language_brief_fails_closed_on_trade_promotion(self):
        original = build_reviews(self.source_bytes)
        for field, value in (("trade_authorized", True),
                             ("live_buy_eligibility", "AUTHORIZED")):
            altered = copy.deepcopy(original)
            altered[field] = value
            with self.assertRaisesRegex(ValueError, "RESEARCH_BRIEF_SOURCE"):
                render_research_brief(altered)
        for field, value in (("decision_packet", {"decision": "BUY"}),
                             ("contemplated_action", "BUY"),
                             ("buy_add_authorized", True)):
            altered = copy.deepcopy(original)
            altered["cases"][0][field] = value
            with self.assertRaisesRegex(ValueError, "RESEARCH_BRIEF_CANNOT_PROMOTE"):
                render_research_brief(altered)

    def capacity_fixture(self):
        return {
            "as_of": "2026-11-02T14:12:00+08:00",
            "account_equity_cny": 100000,
            "available_cash_cny": 100000,
            "max_single_name_position_fraction": 0.35,
            "max_single_name_risk_fraction": 0.01,
            "buy_fee_reserve_cny": 300,
            "quotes": [
                {"security_id": "SZSE:300408", "as_of": "2026-11-02T14:10:00+08:00",
                 "price_cny": 80.0, "source": "USER_SUPPLIED_UNVERIFIED"},
                {"security_id": "SSE:688002", "as_of": "2026-11-02T14:10:00+08:00",
                 "price_cny": 140.0, "source": "USER_SUPPLIED_UNVERIFIED"},
            ],
            "stops": [
                {"security_id": "SZSE:300408", "stop_price_cny": 75.0},
                {"security_id": "SSE:688002", "stop_price_cny": 136.0},
            ],
            "permissions": {"chinext": True, "star": True},
        }

    def test_private_capital_sizing_uses_true_chinext_and_star_lots(self):
        # Invented scenario only; these are NOT actual market quotes or orders.
        report = assess_private_capital_capacity(build_reviews(self.source_bytes), self.capacity_fixture())
        by_id = {r["security_id"]: r for r in report["cases"]}
        a, b = by_id["SZSE:300408"], by_id["SSE:688002"]
        self.assertEqual(a["standalone_hypothetical_max_shares_not_order"], 200)
        self.assertEqual(a["minimum_buy_shares"], 100)
        self.assertEqual(a["subsequent_quantity_increment_shares"], 100)
        self.assertEqual(b["standalone_hypothetical_max_shares_not_order"], 250)
        self.assertEqual(b["minimum_buy_shares"], 200)
        self.assertEqual(b["subsequent_quantity_increment_shares"], 1)
        self.assertEqual(b["standalone_hypothetical_notional_cny"], 35000)
        self.assertFalse(report["trade_authorized"])
        self.assertTrue(report["standalone_alternatives_not_an_aggregate_portfolio"])

    def test_private_account_permission_never_inferred(self):
        plan = self.capacity_fixture()
        plan["permissions"]["star"] = False
        report = assess_private_capital_capacity(build_reviews(self.source_bytes), plan)
        b = next(x for x in report["cases"] if x["security_id"] == "SSE:688002")
        self.assertEqual(b["capacity_status"], "TRADING_PERMISSION_UNKNOWN_OR_DISABLED")
        self.assertIsNone(b["standalone_hypothetical_max_shares_not_order"])

    def test_private_cash_or_risk_below_one_lot_blocks(self):
        plan = self.capacity_fixture()
        plan["account_equity_cny"] = 15000
        plan["available_cash_cny"] = 15000
        plan["max_single_name_position_fraction"] = .2
        report = assess_private_capital_capacity(build_reviews(self.source_bytes), plan)
        self.assertTrue(all(x["capacity_status"] == "MINIMUM_ORDER_EXCEEDS_CASH_POSITION_OR_RISK_LIMIT"
                            for x in report["cases"]))
        self.assertTrue(all(x["standalone_hypothetical_max_shares_not_order"] is None
                            for x in report["cases"]))

    def test_old_private_quote_does_not_produce_sizing(self):
        plan = self.capacity_fixture()
        plan["quotes"][0]["as_of"] = "2026-11-01T15:00:00+08:00"
        report = assess_private_capital_capacity(build_reviews(self.source_bytes), plan)
        a = next(x for x in report["cases"] if x["security_id"] == "SZSE:300408")
        self.assertEqual(a["capacity_status"], "QUOTE_STALE_FUTURE_OR_DIFFERENT_SESSION_DAY")
        self.assertIsNone(a["standalone_hypothetical_max_shares_not_order"])

    def test_missing_real_stop_or_quote_does_not_invent_one(self):
        plan = self.capacity_fixture()
        plan["stops"] = []
        plan["quotes"] = []
        report = assess_private_capital_capacity(build_reviews(self.source_bytes), plan)
        self.assertTrue(all(x["capacity_status"] == "NO_USER_SUPPLIED_SAME_DAY_QUOTE"
                            for x in report["cases"]))
        self.assertTrue(all(x["standalone_hypothetical_max_shares_not_order"] is None
                            for x in report["cases"]))

    def test_invalid_private_cash_and_duplicate_quote_rejected_at_boundary(self):
        research = build_reviews(self.source_bytes)
        plan = self.capacity_fixture()
        plan["available_cash_cny"] = True
        with self.assertRaisesRegex(ValueError, "INVALID_PRIVATE_FIELD"):
            assess_private_capital_capacity(research, plan)
        plan = self.capacity_fixture()
        plan["quotes"].append(plan["quotes"][0].copy())
        with self.assertRaisesRegex(ValueError, "DUPLICATED_PRIVATE_QUOTES"):
            assess_private_capital_capacity(research, plan)



if __name__ == "__main__":
    unittest.main()
