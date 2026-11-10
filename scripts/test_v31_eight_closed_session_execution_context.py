"""Offline current-session reality checks: stop before order execution."""
import unittest
from copy import deepcopy

from v29_eight_portfolio_capacity import sealed_readiness
from v31_eight_closed_session_execution_context import evaluate,security_code


def fixture():
    original=sealed_readiness()
    quotes={}
    for x in original["names_in_original_registered_order"]:
        sid=x["security_id"]
        quotes[sid]=[{
            "date":"2026-11-10","code":security_code(sid),
            "open":"10","high":"11","low":"9.50","close":"10",
            "preclose":"9.60","volume":"50000","amount":"500000",
            "adjustflag":"3","tradestatus":"1","pctChg":"4.17","isST":"0"}]
    return original,quotes


class RealEightSessionTests(unittest.TestCase):
    def test_complete_eod_proxy_is_not_buy_or_fill(self):
        baseline,quotes=fixture()
        r=evaluate(baseline,quotes)
        self.assertEqual(r["sample_count"],8)
        self.assertEqual(r["nonst_positive_volume_quote_count"],8)
        self.assertEqual(r["basket_min_lot_eod_notional_cny_if_complete"],8000)
        self.assertEqual(r["live_buy_eligibility"],"NOT_AUTHORIZED")
        self.assertFalse(r["trade_authorized"])
        self.assertFalse(r["buyer_side_order_limit_or_halt_tradability_certified"])
        self.assertFalse(r["personal_account_and_permissions_available"])
        self.assertTrue(all(not x["buy_fill_certified"] for x in r["rows"]))

    def test_st_suspension_and_missing_current_day_never_mark_usable(self):
        baseline,q=fixture()
        q[baseline["names_in_original_registered_order"][0]["security_id"]][0]["isST"]="1"
        q[baseline["names_in_original_registered_order"][1]["security_id"]][0]["tradestatus"]="0"
        q[baseline["names_in_original_registered_order"][2]["security_id"]][0]["date"]="2026-11-09"
        r=evaluate(baseline,q)
        self.assertEqual(r["nonst_positive_volume_quote_count"],5)
        self.assertIsNone(r["basket_min_lot_eod_notional_cny_if_complete"])
        self.assertEqual(r["rows"][0]["status"],"VENDOR_ST_FLAG")
        self.assertEqual(r["rows"][1]["status"],"VENDOR_SUSPENSION_OR_NOT_ACTIVE")
        self.assertEqual(r["rows"][2]["status"],"EOD_VENDOR_BAR_MISSING")
        self.assertEqual(r["rows"][2]["latest_vendor_bar_date"],"2026-11-09")

    def test_source_identity_or_adjustflag_mismatch_fails(self):
        base,q=fixture()
        changed=deepcopy(q)
        sid=base["names_in_original_registered_order"][0]["security_id"]
        changed[sid][0]["adjustflag"]="2"
        with self.assertRaisesRegex(ValueError,"BAR_NOT_UNADJUSTED"):
            evaluate(base,changed)
        changed=deepcopy(q)
        changed[sid][0]["code"]="sz.000000"
        with self.assertRaisesRegex(ValueError,"BAR_ID_DATE_OR_DUPLICATE"):
            evaluate(base,changed)
        changed=deepcopy(q)
        changed[sid].append(deepcopy(changed[sid][0]))
        with self.assertRaisesRegex(ValueError,"BAR_ID_DATE_OR_DUPLICATE"):
            evaluate(base,changed)


if __name__=="__main__":
    unittest.main()
