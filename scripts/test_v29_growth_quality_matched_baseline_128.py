"""Offline regression of frozen 2025 cohort factor screening and matched-random tests.

Outcomes used in all screening tests below are FAKE, not historic realized returns.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_growth_quality_matched_baseline_128 import (
    PRICE, SPEC, SCREENS, SEED, REPLICATES, _ranking_by_entry_day,
    compare, feature_source_join,
)

SAMPLE=json.loads(PRICE.read_text(encoding="utf-8"))
SPEC_DOC=json.loads(SPEC.read_text(encoding="utf-8"))
SIDS=[x["security_id"] for x in SAMPLE["rows"]]


def pretend_features():
    result=[]
    for i, r in enumerate(SAMPLE["rows"]):
        result.append({
            "security_id":r["security_id"],
            "revenue_growth_yoy_pct":float((i*7)%127)-45.,
            "weighted_roe_pct":float((i*11)%93)-32.,
            "historical_annual_report_notice_day":r["original_report_publication_day"],
            "frozen_source_row_sha256":"fictional_unit_test_sha",
        })
    return result


def pretend_outcomes():
    outcomes=copy.deepcopy(SAMPLE["rows"])
    for i, row in enumerate(outcomes):
        if not row["comparison_eligible"]:
            continue
        raw=0.02+(i%41)*.0005
        benchmark=.01
        row["stock_price_only_return"]=raw
        row["csi300_price_index_return"]=benchmark
        row["price_only_excess_after_30bps_vs_zero_cost_index"]=raw-.003-benchmark
    return outcomes


def synthetic_vendor_and_coverage():
    source=[]
    archived=[]
    for sid in SIDS:
        exch,code=sid.split(":")
        row={
            "SECUCODE":code + (".SH" if exch=="SSE" else ".SZ"),
            "SECURITY_CODE":code,
            "REPORTDATE":"2024-12-31 00:00:00",
            "NOTICE_DATE":"2025-04-20 00:00:00",
            "UPDATE_DATE":"2026-04-20 00:00:00",
            "TOTAL_OPERATE_INCOME":100000000.0,
            "PARENT_NETPROFIT":10000000.0,
            "YSTZ":20.0,
            "WEIGHTAVG_ROE":12.0,
        }
        raw=json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
        source.append(row)
        archived.append({
            "security_id":sid,
            "source_row_hashes":[hashlib.sha256(raw).hexdigest()],
            "vendor_announcement_dates":["2025-04-20"],
            "vendor_update_dates":["2026-04-20"],
            "vendor_revenue_yuan":100000000.0,
            "vendor_parent_profit_yuan":10000000.0,
        })
    return source,{"rows":archived}


class ExploratoryScreenTests(unittest.TestCase):
    def test_128_issuer_vendor_record_and_replay_hash_identical(self):
        sources,archived=synthetic_vendor_and_coverage()
        got=feature_source_join(sources,archived,SIDS)
        self.assertEqual(len(got),128)
        self.assertEqual([x["security_id"] for x in got],SIDS)
        self.assertEqual(got[0]["revenue_growth_yoy_pct"],20)
        self.assertEqual(got[0]["weighted_roe_pct"],12)
        self.assertFalse(got[0]["original_asof_financial_field_certified"])

    def test_changed_retro_vendor_feature_never_slips_past_source_hash(self):
        sources,archived=synthetic_vendor_and_coverage()
        sources[0]["YSTZ"]=999
        with self.assertRaisesRegex(ValueError,"RETRIEVED_VENDOR_SOURCE_ROW_HAS_CHANGED"):
            feature_source_join(sources,archived,SIDS)

    def test_duplicates_missing_issuer_and_changed_revenue_block(self):
        sources,archived=synthetic_vendor_and_coverage()
        with self.assertRaisesRegex(ValueError,"DUPLICATE_2024_FINANCIAL_SOURCE_ISSUER"):
            feature_source_join(sources+[sources[0]],archived,SIDS)
        with self.assertRaisesRegex(ValueError,"MISSING_FROZEN_VENDOR_FINANCIAL_ROWS"):
            feature_source_join(sources[:-1],archived,SIDS)

    def test_primary_rank_selection_does_not_access_future_returns(self):
        features=pretend_features()
        base=pretend_outcomes()
        scored=_ranking_by_entry_day(features,base)
        altered=copy.deepcopy(base)
        for i,r in enumerate(altered):
            if r["comparison_eligible"]:
                r["stock_price_only_return"]=((-1)**i)*.45
                r["price_only_excess_after_30bps_vs_zero_cost_index"]=((-1)**i)*.45
        after=_ranking_by_entry_day(features,altered)
        for flag in ("selected_by_primary","selected_by_revenue","selected_by_roe"):
            self.assertEqual([r[flag] for r in scored],[r[flag] for r in after])
        self.assertEqual(len(scored),128)
        self.assertEqual(sum(r["market_price_comparison_eligible"] for r in scored),120)
        self.assertEqual(sum(not r["market_price_comparison_eligible"] for r in scored),8)

    def test_exact_entry_day_group_selection_and_stable_ties(self):
        features=pretend_features()
        outcomes=pretend_outcomes()
        groups={}
        rows=_ranking_by_entry_day(features,outcomes)
        for row in rows:
            if row["factor_candidate_eligible"]:
                groups.setdefault(row["entry_session"],[]).append(row)
        for day,g in groups.items():
            selected=sum(x["selected_by_primary"] for x in g)
            if len(g)<5:
                self.assertEqual(selected,0)
            else:
                self.assertEqual(selected,math.ceil(len(g)/3))
        tied=copy.deepcopy(features)
        for row in tied:
            row["revenue_growth_yoy_pct"]=8.0
            row["weighted_roe_pct"]=8.0
        scores=_ranking_by_entry_day(tied,outcomes)
        for day,g in groups.items():
            if len(g)>=5:
                chosen=sorted(x["security_id"] for x in scores
                              if x["entry_session"]==day and x["selected_by_primary"])
                self.assertEqual(chosen,sorted(x["security_id"] for x in g)[:math.ceil(len(g)/3)])

    def test_original_notice_and_feature_asof_identity_can_never_conflict(self):
        features=pretend_features()
        features[0]["historical_annual_report_notice_day"]="2025-02-01"
        with self.assertRaisesRegex(ValueError,"FINANCIAL_AND_ORIGINAL_REPORT_NOTICE_MISMATCH"):
            _ranking_by_entry_day(features,pretend_outcomes())

    def test_no_untouched_oos_claim_and_random_controls_are_reused(self):
        result=compare(pretend_features(),pretend_outcomes(),SPEC_DOC)
        self.assertEqual(len(result["rows"]),128)
        self.assertEqual(result["market_price_comparison_eligible_count"],120)
        self.assertEqual(result["multiple_factor_diagnostics_not_strategy_search"],3)
        self.assertTrue(result["primary_selected_count"]>0)
        self.assertFalse(result["independent_untouched_oos_validated"])
        self.assertEqual(result["evidence_strength"],"INSUFFICIENT")
        self.assertEqual(result["live_buy_eligibility"],"NOT_AUTHORIZED")
        for name in SCREENS:
            m=result["screens"][name]["same_day_random_net_stock_return"]
            self.assertEqual(m["replicate_count"],REPLICATES)
            self.assertEqual(m["seed"],SEED)
            self.assertEqual(m["baseline_scope"],"CONDITIONAL_SELECTION_ONLY")
            self.assertFalse(result["screens"][name]["random_not_a_pristine_p_value"] is False)

    def test_cannot_change_screen_config_after_fixed_source(self):
        doc=copy.deepcopy(SPEC_DOC)
        doc["minimum_tradeable_companies_per_same_entry_session"]=1
        with self.assertRaisesRegex(ValueError,"EXPLORATORY_RULES_OR_CONFIG_DRIFT"):
            compare(pretend_features(),pretend_outcomes(),doc)

    def test_missing_factor_and_ST_are_kept_with_separate_reasons(self):
        features=pretend_features()
        features[0]["weighted_roe_pct"]=None
        result=_ranking_by_entry_day(features,pretend_outcomes())
        self.assertEqual(len(result),128)
        self.assertFalse(result[0]["factor_candidate_eligible"])
        self.assertFalse(result[0]["selected_by_primary"])
        self.assertEqual(sum(not r["market_price_comparison_eligible"] for r in result),8)


if __name__=="__main__":
    unittest.main()
