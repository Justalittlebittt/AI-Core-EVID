"""Real-source end-to-end regression of unified blocked-BUY decision gate.

Private account and packet values below are synthetically constructed only.
"""
from __future__ import annotations

import copy
import json
import unittest

from v29_decision_case_demo import build_case
from v31_unified_eight_decision_gate import build, load_archived_market, validate_market_by_identity, render, render_one, select_one


class V31UnifiedDecisionGateTests(unittest.TestCase):
    def test_current_real_archived_eight_all_blocked(self):
        result=build()
        self.assertEqual(result["stock_count"],8)
        self.assertEqual(result["last_available_vendor_close_date"],"2026-11-09")
        self.assertEqual(result["market_evidence"]["current_session_eod_count"],0)
        self.assertEqual(result["market_evidence"]["min_lot_notional_at_20261109_vendor_closes_cny"],53060)
        self.assertEqual(result["strategy_evidence"]["grade"],"INSUFFICIENT")
        self.assertEqual(result["private_account_and_stop_gate"]["status"],"NOT_EVALUATED_NO_PRIVATE_ACCOUNT_INPUT")
        self.assertFalse(result["trade_authorized"])
        self.assertEqual(result["live_buy_eligibility"],"NOT_AUTHORIZED")
        self.assertEqual(len({x["security_id"] for x in result["stocks"]}),8)
        self.assertTrue(all(x["decision"]=="BLOCK_BUY" for x in result["stocks"]))
        self.assertIn("NOT_AUTHORIZED / NO BUY",render(result))

    def test_single_security_card_is_reproducible_and_exposes_provenance(self):
        report=build()
        sid=report["stocks"][0]["security_id"]
        card=render_one(report,sid)
        self.assertEqual(card,render_one(report,sid))
        self.assertIn(sid,card)
        self.assertIn(report["source_sha256"]["sealed_122_nov02_entry"],card)
        self.assertIn(report["source_sha256"]["latest_saved_vendor_daily_bars"],card)
        self.assertIn("2026-11-09",card)
        self.assertIn("INSUFFICIENT",card)
        self.assertIn("BLOCK_BUY",card)
        self.assertIn("NOT_AUTHORIZED / NO BUY",card)
        self.assertIn("NO_INDEPENDENTLY_VALIDATED_PREDICTIVE_EDGE",card)
        self.assertNotIn("建议买入",card)
        self.assertNotIn(report["stocks"][1]["security_id"],card)

    def test_single_security_card_unknown_or_promoted_fails_closed(self):
        report=build()
        with self.assertRaisesRegex(ValueError,"UNKNOWN_OR_DUPLICATE_RESEARCH_SECURITY"):
            render_one(report,"SSE:999999")
        altered=copy.deepcopy(report)
        altered["stocks"][0]["decision"]="BUY"
        with self.assertRaisesRegex(ValueError,"INTEGRATED_GATE_UNSAFE_TO_RENDER"):
            render_one(altered,altered["stocks"][0]["security_id"])

    def test_one_stock_json_projection_is_source_bound_and_no_buy(self):
        full=build()
        sid=full["stocks"][0]["security_id"]
        case=select_one(full,sid)
        encoded=json.dumps(case,ensure_ascii=False)
        self.assertEqual(case["security_id"],sid)
        self.assertEqual(case["source_sha256"],full["source_sha256"])
        self.assertEqual(case["market_reference"]["latest_available_close_date"],"2026-11-09")
        self.assertEqual(case["strategy_evidence"]["grade"],"INSUFFICIENT")
        self.assertIn("NO_INDEPENDENTLY_VALIDATED_PREDICTIVE_EDGE",case["blocking_reasons"])
        self.assertEqual(case["decision"],"BLOCK_BUY")
        self.assertFalse(case["trade_authorized"])
        self.assertEqual(case["live_buy_eligibility"],"NOT_AUTHORIZED")
        self.assertNotIn(full["stocks"][1]["security_id"],encoded)
        self.assertEqual(case,select_one(full,sid))
        with self.assertRaisesRegex(ValueError,"UNKNOWN_OR_DUPLICATE_RESEARCH_SECURITY"):
            select_one(full,"SZSE:999999")
        tampered=copy.deepcopy(full)
        tampered["stocks"][0]["decision"]="BUY"
        with self.assertRaisesRegex(ValueError,"INTEGRATED_GATE_UNSAFE_TO_RENDER"):
            select_one(tampered,sid)

    def test_one_stock_json_local_private_account_only_shows_selected_name(self):
        base=build()
        positions=[]
        for x in base["stocks"]:
            price=x["quote_reference"]["latest_available_close_cny"]
            positions.append({"security_id":x["security_id"],
                              "shares":100,
                              "reference_price_cny":price,
                              "stop_price_cny":round(price*.8,2)})
        data={"account":{
                  "equity_cny":300000,"cash_cny":300000,
                  "fee_reserve_cny":300,"max_name_fraction":.2,
                  "max_name_loss_fraction":.02,
                  "max_portfolio_loss_fraction":.08,
                  "permissions":{"main":True,"chinext":True,"star":False},
              },"positions":positions}
        r=build(private=data)
        selected=select_one(r,r["stocks"][0]["security_id"])
        self.assertTrue(selected["private_account_and_stop_gate"]["paper_capacity_feasible"])
        self.assertEqual(selected["account_paper_capacity"]["user_reference_price_cny"],"23.55")
        self.assertEqual(selected["account_paper_capacity"]["user_stop_price_cny"],"18.84")
        self.assertNotIn("per_name",selected["private_account_and_stop_gate"])
        other=r["stocks"][1]["security_id"]
        self.assertNotIn(other,json.dumps(selected,ensure_ascii=False))
        self.assertFalse(selected["trade_authorized"])

    def test_wrong_saved_quote_does_not_get_promoted(self):
        source,eod,latest,seal=load_archived_market(__import__("pathlib").Path(__file__).resolve().parents[1])
        ids=[x["security_id"] for x in latest["rows"]]
        source=copy.deepcopy(source)
        first=ids[0]
        newest=max(source["raw"][first],key=lambda x:x["date"])
        newest["close"]=str(float(newest["close"])+1)
        with self.assertRaisesRegex(ValueError,"DERIVED_1109_BAR_OR_LOT"):
            validate_market_by_identity(source,eod,latest,ids)

    def test_original_selected_identity_change_fails(self):
        source,eod,latest,seal=load_archived_market(__import__("pathlib").Path(__file__).resolve().parents[1])
        ids=[x["security_id"] for x in latest["rows"]]
        with self.assertRaisesRegex(ValueError,"EIGHT_ARCHIVE_IDENTITY_DRIFT"):
            validate_market_by_identity(source,eod,latest,list(reversed(ids)))

    def test_fake_real_funding_can_only_make_paper_capacity_pass(self):
        baseline=build()
        rows=baseline["stocks"]
        positions=[]
        for x in rows:
            q=x["quote_reference"]
            px=q["latest_available_close_cny"]
            positions.append({
                "security_id":x["security_id"],
                "shares":q["minimum_lot_shares"],
                "reference_price_cny":px,
                "stop_price_cny":round(px*.8,2)})
        data={
            "account":{
                "equity_cny":300000,"cash_cny":300000,"fee_reserve_cny":300,
                "max_name_fraction":.2,
                "max_name_loss_fraction":.02,
                "max_portfolio_loss_fraction":.08,
                "permissions":{"main":True,"chinext":True,"star":False},
            },
            "positions":positions,
        }
        result=build(private=data)
        self.assertTrue(result["private_account_and_stop_gate"]["paper_capacity_feasible"])
        self.assertFalse(result["trade_authorized"])
        self.assertEqual(result["live_buy_eligibility"],"NOT_AUTHORIZED")
        self.assertTrue(all(x["decision"]=="BLOCK_BUY" for x in result["stocks"]))
        data["account"]["cash_cny"]=500
        result=build(private=data)
        self.assertFalse(result["private_account_and_stop_gate"]["paper_capacity_feasible"])
        self.assertIn("CALLER_SUPPLIED_CAPACITY_CHECK_FAILED",result["blocking_reasons"])

    def test_single_card_shows_local_per_name_and_shared_cash_failure(self):
        base=build()
        positions=[]
        for r in base["stocks"]:
            price=r["quote_reference"]["latest_available_close_cny"]
            positions.append({
                "security_id":r["security_id"],
                "shares":100,
                "reference_price_cny":price,
                "stop_price_cny":round(price*.8,2),
            })
        private={
            "account":{
                "equity_cny":300000,
                "cash_cny":500,
                "fee_reserve_cny":300,
                "max_name_fraction":.2,
                "max_name_loss_fraction":.02,
                "max_portfolio_loss_fraction":.08,
                "permissions":{"main":True,"chinext":False,"star":False},
            },
            "positions":positions,
        }
        result=build(private=private)
        sid=result["stocks"][0]["security_id"]
        card=render_one(result,sid)
        self.assertIn("纸面风险核算",card)
        self.assertIn("¥2355",card)
        self.assertIn("BOARD_PERMISSION_NOT_GRANTED",card)
        self.assertIn("SHARED_CASH_EXCEEDED",card)
        self.assertIn("用户指定参考价：¥23.55",card)
        self.assertIn("用户指定止损价：¥18.84",card)
        self.assertIn("（用户参考价－用户止损价）×100股",card)
        self.assertIn("组合层面纸面容量是否通过：**未通过**",card)
        self.assertIn("NOT_AUTHORIZED / NO BUY",card)
        self.assertFalse(result["trade_authorized"])
        # Positive paper capital only clears the *synthetic* capacity check.
        private["account"]["cash_cny"]=300000
        private["account"]["permissions"]["chinext"]=True
        passing=build(private=private)
        passing_card=render_one(passing,sid)
        self.assertIn("组合层面纸面容量是否通过：**通过**",passing_card)
        self.assertIn("未触发纸面个股限制",passing_card)
        self.assertIn("未触发纸面组合限制",passing_card)
        self.assertIn("NOT_AUTHORIZED / NO BUY",passing_card)
        self.assertIn("纸面容量计算只采用用户指定参考价",passing_card)
        self.assertFalse(passing["trade_authorized"])

    def test_user_supplied_fake_strong_decision_packet_is_source_downgraded(self):
        base=build()
        name=base["stocks"][0]["security_id"]
        pkt=build_case()["packet"]
        pkt["validity"]["evidence_strength"]="STRONG"
        result=build(private={"decision_packets":[{"security_id":name,"packet":pkt}]})
        p=result["stocks"][0]["discipline_packet_preview"]
        self.assertEqual(p["claimed_user_evidence_strength"],"STRONG")
        self.assertEqual(p["effective_source_bound_evidence_strength"],"INSUFFICIENT")
        self.assertTrue(p["source_overrode_unverified_reported_strength"])
        self.assertEqual(p["discipline_decision"]["decision"],"NO_ACTION_INSUFFICIENT_EVIDENCE")
        self.assertFalse(result["trade_authorized"])

    def test_private_input_required_in_complete_pairs(self):
        with self.assertRaisesRegex(ValueError,"ACCOUNT_AND_POSITIONS_MUST_BE_TOGETHER"):
            build(private={"account":{}})


if __name__=="__main__":
    unittest.main()
