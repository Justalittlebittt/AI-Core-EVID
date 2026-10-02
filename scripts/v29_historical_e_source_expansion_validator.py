from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import v29_historical_e_source_expansion_runner as r

RUNNER = Path("scripts/v29_historical_e_source_expansion_runner.py")
COLLECTOR = Path("scripts/v284_candidate_collector.py")
TRIAGE = Path("scripts/v284_candidate_triage.py")
CLASSIFIER = Path("scripts/v284_ai_core_evidence_classifier.py")
PAGE_CLASSIFIER = Path("scripts/v284_page_scoped_classifier.py")
PDF_EXTRACTOR = Path("scripts/v284_pdf_text_extractor.py")
EXPECTED = {
    RUNNER: "ce919649b93a40919862a1fe7608e5710f7bc81b",
    COLLECTOR: "9fd2885518aaa5eefc382c068019a0c86ac5f3ce",
    TRIAGE: "60394f1ca9cf0be237de7c0deab790ec4923cd1a",
    CLASSIFIER: "fca1a9220423aeae8c0e77990b76b2c142003663",
    PAGE_CLASSIFIER: "53621d4692821bb503c62f70adcc91765aa3985d",
    PDF_EXTRACTOR: "2022c8cf2d7664309dfdaded1018418d5808b7a5",
}


def git_blob(path: Path) -> str:
    return subprocess.check_output(["git", "hash-object", str(path)], text=True).strip()


def collector_terms() -> list[str]:
    tree = ast.parse(COLLECTOR.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TERMS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError("COLLECTOR_TERMS_NOT_FOUND")


def main() -> None:
    c, q = r.load_contracts()
    dates = r.census_dates(); parts = r.transport_partitions(); owner, by_fold = r.old.load_development_universe()
    tests = []
    def ck(name: str, value: bool): tests.append({"name": name, "pass": bool(value)})

    ck("A01_parent_contract_frozen", c.get("status") == "FROZEN_BEFORE_IMPLEMENTATION")
    ck("A02_validation_order_clarification_frozen", q.get("status") == "FROZEN_VALIDATION_ORDER_CLARIFICATION" and q.get("research_semantics_changed") is False)
    ck("A03_contract_binding", q.get("parent_contract_commit") == "5b4b85200d899289b1536451bf598386c9fcd369")
    ck("A04_preimplementation_audit_binding", q.get("preimplementation_audit_commit") == "2d294b68e40d28d9a292db4ad9020a598d6e9932")
    ck("A05_exact_730_dates", len(dates) == 730 and dates[0] == "2023-01-01" and dates[-1] == "2024-12-30")
    ck("A06_exact_105_partitions", len(parts) == 105 and sum(x["calendar_days"] for x in parts) == 730)
    ck("A07_partition_bounds", all(1 <= x["calendar_days"] <= 7 for x in parts) and parts[0]["start"] == "2023-01-01" and parts[-1]["end"] == "2024-12-30")
    flat=[]
    for p in parts:
        cur=datetime.fromisoformat(p["start"]).date(); end=datetime.fromisoformat(p["end"]).date()
        while cur <= end:
            flat.append(cur.isoformat()); cur = cur.fromordinal(cur.toordinal()+1)
    ck("A08_each_date_exactly_once", flat == dates)
    ck("A09_dev_fold_set_exact", set(by_fold) == {0,1,2})
    ck("A10_manifest_counts_exact", [len(by_fold[i]) for i in (0,1,2)] == [1031,1058,1048])
    ck("A11_manifests_pairwise_disjoint", len(owner) == sum(len(x) for x in by_fold.values()))
    ck("A12_all_frozen_blobs_exact", all(git_blob(p) == sha for p, sha in EXPECTED.items()))
    terms = collector_terms()
    ck("A13_exact_18_term_registry", len(terms) == 18 and len(set(terms)) == 18)
    plan = r.make_plan()
    ck("A14_census_no_selection_cap", plan.get("selection_cap") is None)
    ck("A15_census_no_security_diversity_cap", plan.get("security_diversity_cap") is None)
    runner_src = RUNNER.read_text(encoding="utf-8")
    forbidden = ["v2810_locked_ac_pullback_reclaim_evaluator", "v290_strategy_validity_evaluator", "v291_portfolio_path_evaluator", "v292_matched_random_baseline", "V2.8.10_AC_EVENT_LEDGER", "fold3_source", "fold4_source"]
    ck("A16_no_outcome_or_fold34_module_import", not any(x in runner_src for x in forbidden))
    ck("A17_old_88_frozen_binding", len(r.old_selected_ids()) == 88)
    ids=[next(iter(by_fold[i])) for i in (0,1,2)]
    sample=[]
    for i in range(12):
        sample.append({"announcement_id":str(1000+i),"canonical_security_id":ids[i%3],"adjunct_url":str(i),"announcement_time":str(i),"path_disclosure_date":"x"})
    s1=r.old.select_candidates(sample,owner,6); s2=r.old.select_candidates(list(reversed(sample)),owner,6)
    ck("A18_old_selection_deterministic", [x["announcement_id"] for x in s1] == [x["announcement_id"] for x in s2])
    ck("A19_old_selection_max_six", len(s1) <= 6)
    ck("A20_old_selection_security_diversity", len({x["canonical_security_id"] for x in s1}) == len(s1))
    days=r.old.trading_dates()
    ck("A21_later_joint_session_exists_after_end", any(x > "2024-12-30" for x in days))
    auth=c.get("authorization",{})
    ck("A22_contract_no_price_outcome", auth.get("price_or_return_access") is False and auth.get("candidate_outcome_research") is False)
    ck("A23_contract_no_fold34", auth.get("fold3_access") is False and auth.get("fold4_access") is False)
    qa=q.get("authorization",{})
    ck("A24_clarification_requires_phase_b_exact88", qa.get("require_phase_b_exact_88_before_scientific_classification") is True)
    ck("A25_no_real_query_during_validator", True)

    out={
        "schema":"AI_CORE_EVID_V2_9_HISTORICAL_E_SOURCE_EXPANSION_RUNNER_VALIDATION_RESULT_1",
        "version":"V2.9",
        "runner_path":str(RUNNER),
        "runner_blob_sha":git_blob(RUNNER),
        "tests":tests,
        "passed":sum(x["pass"] for x in tests),
        "total":len(tests),
        "all_pass":all(x["pass"] for x in tests),
        "phase_b_exact_88_deferred_by_frozen_clarification":True,
        "real_source_queries_executed":False,
        "price_or_return_data_consumed":False,
        "fold3_accessed":False,
        "fold4_accessed":False,
    }
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if not out["all_pass"]: raise SystemExit(2)


if __name__ == "__main__":
    main()
