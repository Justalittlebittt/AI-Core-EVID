import unittest
from v32_candidate_tradeability import evaluate,board_lot

ACCOUNT={'cash_cny':100000,'slot_cap_cny':10000,'fee_reserve_cny':100,
         'permissions':{'main':True,'chinext':True,'star':True}}
def candidate(sid, price):
    return {'security_id':sid,'reference_price_cny':price,'reference_session':'2026-05-29'}

class TestTradeability(unittest.TestCase):
    def test_board_minimum_and_star_one_share_increments(self):
        self.assertEqual(board_lot('SSE:688122'),('star',200))
        self.assertEqual(board_lot('SZSE:300199'),('chinext',100))
        self.assertEqual(board_lot('SSE:603256'),('main',100))
        self.assertEqual(board_lot('SZSE:002463'),('main',100))
    def test_unaffordable_star_is_blocked_without_replacement(self):
        rows=[candidate('SSE:688122','60'), candidate('SSE:603256','20')]
        result=evaluate(rows,ACCOUNT)
        self.assertEqual([r['security_id'] for r in result['original_candidates_in_original_order']],['SSE:688122','SSE:603256'])
        self.assertEqual(result['original_candidates_in_original_order'][0]['gate'],'BLOCKED_PAPER_BUY')
        self.assertEqual(result['original_candidates_in_original_order'][1]['gate'],'PAPER_MIN_LOT_AFFORDABLE_ONLY')
        self.assertFalse(result['trade_authorized'])
    def test_cash_and_permissions(self):
        a=dict(ACCOUNT,cash_cny=500,permissions={'main':True,'chinext':False,'star':False})
        x=evaluate([candidate('SZSE:300199',10)],a)['original_candidates_in_original_order'][0]
        self.assertIn('BOARD_PERMISSION_NOT_CONFIRMED',x['reasons'])
        self.assertIn('MIN_LOT_OVER_AVAILABLE_CASH',x['reasons'])
    def test_no_account_fiction(self):
        a=dict(ACCOUNT);del a['permissions']
        with self.assertRaises(KeyError):evaluate([candidate('SSE:600118',10)],a)
    def test_no_invalid_instruments(self):
        with self.assertRaisesRegex(ValueError,'NOT_SUPPORTED_A_SHARE_STOCK_ID'):
            evaluate([candidate('SSE:510050',2)],ACCOUNT)
    def test_duplicate_member_fails(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):
            evaluate([candidate('SSE:600118',10),candidate('SSE:600118',10)],ACCOUNT)

if __name__=='__main__':unittest.main()
