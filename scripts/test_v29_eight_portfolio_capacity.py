"""Synthetic-only tests for shared portfolio cash and risk; never real quotes."""
import unittest
from v29_eight_portfolio_capacity import assess

IDS = ["SZSE:300199","SZSE:002636","SZSE:301536","SZSE:000408",
       "SZSE:002463","SSE:603256","SZSE:002552","SZSE:300223"]

def example():
    account = {"equity_cny":100000,"cash_cny":100000,"fee_reserve_cny":300,
               "max_name_fraction":0.15,"max_name_loss_fraction":0.01,
               "max_portfolio_loss_fraction":0.05,
               "permissions":{"main":True,"chinext":True,"star":True}}
    positions = [{"security_id":s,"shares":100,"reference_price_cny":50,"stop_price_cny":45}
                 for s in IDS]
    return account, positions

class Tests(unittest.TestCase):
    def test_paper_only(self):
        a,p=example()
        r=assess(IDS,a,p)
        self.assertTrue(r["paper_capacity_feasible"])
        self.assertFalse(r["trade_authorized"])
        self.assertEqual(r["gross_reference_notional_cny"],"40000")
        self.assertEqual(r["gross_stop_distance_loss_cny"],"4000")

    def test_shared_cash_not_reusable_eight_times(self):
        a,p=example()
        a["cash_cny"]=30000
        self.assertIn("SHARED_CASH_EXCEEDED",assess(IDS,a,p)["basket_issues"])

    def test_portfolio_risk_cap(self):
        a,p=example()
        a["max_portfolio_loss_fraction"]=0.02
        self.assertIn("PORTFOLIO_STOP_RISK_EXCEEDED",assess(IDS,a,p)["basket_issues"])

    def test_permission_required(self):
        a,p=example()
        a["permissions"]["chinext"]=False
        r=assess(IDS,a,p)
        self.assertFalse(r["paper_capacity_feasible"])
        self.assertIn("BOARD_PERMISSION_NOT_GRANTED",r["positions"][0]["issues"])

    def test_lot_and_stop(self):
        a,p=example()
        p[0]["shares"]=150
        with self.assertRaisesRegex(ValueError,"INVALID_EXCHANGE_LOT"):
            assess(IDS,a,p)
        a,p=example()
        p[0]["stop_price_cny"]=51
        with self.assertRaisesRegex(ValueError,"STOP_NOT_BELOW"):
            assess(IDS,a,p)

    def test_exact_eight(self):
        a,p=example()
        p[1]["security_id"]=p[0]["security_id"]
        with self.assertRaisesRegex(ValueError,"POSITIONS_MUST_MATCH"):
            assess(IDS,a,p)

    def test_per_stock_risk(self):
        a,p=example()
        p[0]["stop_price_cny"]=30
        self.assertIn("SINGLE_NAME_STOP_RISK_LIMIT",assess(IDS,a,p)["positions"][0]["issues"])

    def test_invalid_numbers(self):
        a,p=example()
        a["cash_cny"]=110000
        with self.assertRaisesRegex(ValueError,"INVALID_ACCOUNT_LIMITS"):
            assess(IDS,a,p)
        a,p=example()
        p[0]["reference_price_cny"]=float("nan")
        with self.assertRaisesRegex(ValueError,"INVALID_PRICE"):
            assess(IDS,a,p)

if __name__=="__main__":
    unittest.main()
