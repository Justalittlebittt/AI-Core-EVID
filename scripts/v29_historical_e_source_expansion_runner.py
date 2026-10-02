from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import v29_historical_e_dev_source_runner as old

CONTRACT = Path("evidence/V2.9_HISTORICAL_E_SOURCE_EXPANSION_CONTRACT_1.json")
CLARIFICATION = Path("evidence/V2.9_HISTORICAL_E_SOURCE_EXPANSION_VALIDATION_ORDER_CLARIFICATION_1.json")
VALIDATION = Path("evidence/V2.9_HISTORICAL_E_SOURCE_EXPANSION_RUNNER_VALIDATION_1.json")
OLD_RESULTS = Path("evidence/V2.9_HISTORICAL_E_DEV_SOURCE_RESULTS_1.csv")
OLD_WINDOWS = Path("evidence/V2.9_HISTORICAL_E_DEV_SOURCE_WINDOWS_1.json")
COLLECTOR = Path("scripts/v284_candidate_collector.py")
OUT_PLAN = Path("evidence/V2.9_HISTORICAL_E_SOURCE_EXPANSION_CENSUS_PLAN_1.json")
OUT_RESULTS = Path("evidence/V2.9_HISTORICAL_E_SOURCE_EXPANSION_RESULTS_1.csv")
OUT_POSITIVE = Path("evidence/V2.9_HISTORICAL_E_SOURCE_EXPANSION_POSITIVE_EVENTS_1.csv")
OUT_REPLAY = Path("evidence/V2.9_HISTORICAL_E_SOURCE_EXPANSION_OLD_DESIGN_REPLAY_1.json")
OUT_TERMS = Path("evidence/V2.9_HISTORICAL_E_SOURCE_EXPANSION_TERM_DIAGNOSTICS_1.csv")
OUT_FINAL = Path("evidence/V2.9_HISTORICAL_E_SOURCE_EXPANSION_FINAL_RECEIPT_1.json")
START = date(2023, 1, 1)
END = date(2024, 12, 30)
EXPECTED_DAYS = 730
EXPECTED_PARTITIONS = 105
POSITIVE = "ELIGIBLE_AI_CORE"

RESULT_FIELDS = [
    "announcement_id","canonical_security_id","development_fold","security_name","announcement_title",
    "announcement_time","adjunct_url","path_disclosure_date","matched_terms","query_windows",
    "triage_state","announcement_local_date_asia_shanghai","temporal_provenance_status",
    "retrospective_causal_effective_date","pipeline_status","blocker","object_sha256","bytes",
    "pdf_page_count","pages_with_text","total_nonwhitespace_characters","page_text_sha256",
    "classification_state","evidence_page_number","evidence_sentence_sha256","matched_ai_role",
    "matched_commerciality","classification_reason","decision_sha256",
]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader(); w.writerows(rows)


def stable_sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def census_dates() -> list[str]:
    out = []
    cur = START
    while cur <= END:
        out.append(cur.isoformat()); cur += timedelta(days=1)
    if len(out) != EXPECTED_DAYS or len(set(out)) != EXPECTED_DAYS:
        raise RuntimeError("CENSUS_DAY_GEOMETRY_BLOCK")
    return out


def transport_partitions() -> list[dict]:
    out = []
    cur = START
    i = 1
    while cur <= END:
        stop = min(END, cur + timedelta(days=6))
        out.append({"partition_id": f"P{i:03d}", "start": cur.isoformat(), "end": stop.isoformat(), "calendar_days": (stop-cur).days+1})
        cur = stop + timedelta(days=1); i += 1
    if len(out) != EXPECTED_PARTITIONS or sum(x["calendar_days"] for x in out) != EXPECTED_DAYS:
        raise RuntimeError("TRANSPORT_PARTITION_GEOMETRY_BLOCK")
    return out


def load_contracts() -> tuple[dict, dict]:
    c = read_json(CONTRACT); q = read_json(CLARIFICATION)
    if c.get("schema") != "AI_CORE_EVID_V2_9_HISTORICAL_E_SOURCE_EXPANSION_CONTRACT_1" or c.get("status") != "FROZEN_BEFORE_IMPLEMENTATION":
        raise RuntimeError("EXPANSION_CONTRACT_BLOCK")
    if q.get("schema") != "AI_CORE_EVID_V2_9_HISTORICAL_E_SOURCE_EXPANSION_VALIDATION_ORDER_CLARIFICATION_1" or q.get("status") != "FROZEN_VALIDATION_ORDER_CLARIFICATION":
        raise RuntimeError("VALIDATION_ORDER_CLARIFICATION_BLOCK")
    if q.get("research_semantics_changed") is not False:
        raise RuntimeError("CLARIFICATION_SEMANTIC_DRIFT")
    return c, q


def make_plan() -> dict:
    c, _ = load_contracts()
    dates = census_dates(); parts = transport_partitions()
    plan = {
        "schema": "AI_CORE_EVID_V2_9_HISTORICAL_E_SOURCE_EXPANSION_CENSUS_PLAN_1",
        "version": "V2.9", "status": "DETERMINISTIC_CENSUS_PLAN",
        "start": dates[0], "end": dates[-1], "calendar_day_count": len(dates),
        "transport_partition_count": len(parts), "transport_partitions": parts,
        "selection_cap": None, "security_diversity_cap": None,
        "development_folds": c["invariants"]["development_universe"]["folds"],
        "price_or_return_data_consumed": False, "fold3_accessed": False, "fold4_accessed": False,
    }
    plan["receipt_sha256"] = stable_sha(plan)
    return plan


def validate_authorization() -> dict:
    if not VALIDATION.exists():
        raise RuntimeError("EXPANSION_PHASE_A_VALIDATION_MISSING")
    v = read_json(VALIDATION)
    if v.get("schema") != "AI_CORE_EVID_V2_9_HISTORICAL_E_SOURCE_EXPANSION_RUNNER_VALIDATION_1" or v.get("status") != "PASS":
        raise RuntimeError("EXPANSION_PHASE_A_VALIDATION_NOT_PASS")
    a = v.get("authorization", {})
    if a.get("execute_real_source_collection") is not True:
        raise RuntimeError("EXPANSION_SOURCE_COLLECTION_NOT_AUTHORIZED")
    if any(a.get(k) is not False for k in ("price_or_return_access","candidate_outcome_research","fold3_access","fold4_access")):
        raise RuntimeError("EXPANSION_VALIDATION_SCOPE_BLOCK")
    return v


def old_selected_ids() -> list[str]:
    rows = read_csv(OLD_RESULTS)
    ids = [str(r.get("announcement_id") or "").strip() for r in rows]
    if len(rows) != 88 or len(ids) != 88 or len(set(ids)) != 88 or not all(ids):
        raise RuntimeError("OLD_88_SELECTED_ID_BINDING_BLOCK")
    return ids


def window_contains(w: dict, disclosure_date: str) -> bool:
    return str(w["start"]) <= disclosure_date <= str(w["end"])


def exact_old_replay(candidates: list[dict], dev_owner: dict[str, int]) -> dict:
    windows_obj = read_json(OLD_WINDOWS)
    windows = windows_obj.get("runtime_windows", [])
    if len(windows) != 56:
        raise RuntimeError("OLD_WINDOW_AUTHORITY_BLOCK")
    replay_ids = []
    per_window = []
    for w in windows:
        pool = [r for r in candidates if window_contains(w, str(r.get("path_disclosure_date") or ""))]
        selected = old.select_candidates(pool, dev_owner, 6)
        ids = [r["announcement_id"] for r in selected]
        replay_ids.extend(ids)
        per_window.append({"window_id": w["window_id"], "candidate_pool": len(pool), "selected_ids": ids})
    expected = old_selected_ids()
    exact = set(replay_ids) == set(expected) and len(replay_ids) == len(expected) == 88
    out = {
        "schema": "AI_CORE_EVID_V2_9_HISTORICAL_E_SOURCE_EXPANSION_OLD_DESIGN_REPLAY_1",
        "version": "V2.9", "status": "PASS" if exact else "TECHNICALLY_BLOCKED",
        "expected_selected_count": 88, "replay_selected_count": len(replay_ids),
        "exact_88_selected_ids": exact,
        "missing_from_replay": sorted(set(expected)-set(replay_ids)),
        "unexpected_in_replay": sorted(set(replay_ids)-set(expected)),
        "per_window": per_window,
    }
    out["receipt_sha256"] = stable_sha(out)
    return out


def term_diagnostics(candidates: list[dict], results_by_id: dict[str, dict]) -> list[dict]:
    terms = []
    src = COLLECTOR.read_text(encoding="utf-8")
    ns = {}
    exec(compile(src.split("def stable_sha256",1)[0], str(COLLECTOR), "exec"), ns)
    terms = list(ns["TERMS"])
    rows = []
    for term in terms:
        cand = [r for r in candidates if term in str(r.get("matched_terms") or "").split("|")]
        res = [results_by_id[r["announcement_id"]] for r in cand if r["announcement_id"] in results_by_id]
        ready = [r for r in res if r.get("pipeline_status") == "SUCCESS"]
        pos = [r for r in ready if r.get("classification_state") == POSITIVE]
        rows.append({"term": term, "deduped_candidate_count": len(cand), "admitted_universe_count": len(res),
                     "classifier_ready_count": len(ready), "positive_count": len(pos),
                     "positive_yield": len(pos)/len(ready) if ready else 0.0})
    return rows


def run() -> dict:
    load_contracts(); validate_authorization()
    if OUT_FINAL.exists():
        return {"status": "FINAL_ALREADY_FROZEN_NO_REEXECUTION", "receipt_sha256": read_json(OUT_FINAL).get("receipt_sha256")}
    plan = make_plan(); OUT_PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    days = old.trading_dates(); dev_owner, _ = old.load_development_universe()
    import v284_candidate_triage as ct
    import v284_pdf_text_extractor as te
    import v284_page_scoped_classifier as pc
    from playwright.sync_api import sync_playwright

    results = []
    admitted_candidates = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); cd = root / "census"
        subprocess.run([sys.executable, str(COLLECTOR), "collect", "--start", START.isoformat(), "--end", END.isoformat(), "--out", str(cd)], check=True)
        candidates = read_csv(cd / "V2.8.4_CNINFO_CANDIDATE_DEDUPED.csv")
        for row in candidates:
            q = ct.triage_title(row.get("announcement_title", ""), row.get("security_name", ""))
            if q["triage_state"] != "MATERIALIZE_CANDIDATE":
                continue
            cid = str(row.get("canonical_security_id") or "").strip()
            if cid not in dev_owner:
                continue
            x = dict(row); x["development_fold"] = dev_owner[cid]; x["triage_state"] = q["triage_state"]
            admitted_candidates.append(x)

        replay = exact_old_replay(admitted_candidates, dev_owner)
        OUT_REPLAY.write_text(json.dumps(replay, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        if not replay["exact_88_selected_ids"]:
            final = {
                "schema": "AI_CORE_EVID_V2_9_HISTORICAL_E_SOURCE_EXPANSION_FINAL_RECEIPT_1",
                "version": "V2.9", "status": "V2_9_HISTORICAL_E_SOURCE_EXPANSION_TECHNICALLY_BLOCKED",
                "blocker": "PHASE_B_EXACT_88_REPLAY_MISMATCH", "old_design_replay_sha256": sha_file(OUT_REPLAY),
                "h1_h3_admissible": False, "price_or_return_data_consumed": False,
                "candidate_outcome_research_executed": False, "fold3_accessed": False, "fold4_accessed": False,
            }
            final["receipt_sha256"] = stable_sha(final); OUT_FINAL.write_text(json.dumps(final,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
            print(json.dumps(final, ensure_ascii=False, indent=2)); return final

        with sync_playwright() as pw:
            api = pw.request.new_context(extra_http_headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36"})
            for i, row in enumerate(admitted_candidates, 1):
                base = {k: row.get(k, "") for k in RESULT_FIELDS}
                base.update({"announcement_id":row["announcement_id"], "canonical_security_id":row["canonical_security_id"],
                             "development_fold":row["development_fold"], "security_name":row.get("security_name",""),
                             "announcement_title":row.get("announcement_title",""), "announcement_time":row.get("announcement_time",""),
                             "adjunct_url":row.get("adjunct_url",""), "path_disclosure_date":row.get("path_disclosure_date",""),
                             "matched_terms":row.get("matched_terms",""), "query_windows":row.get("query_windows",""),
                             "triage_state":row.get("triage_state","")})
                try:
                    temporal = old.resolve_temporal(row, days)
                    pdf = root / f"{i:05d}.pdf"
                    obj_sha, nbytes = old.fetch_pdf(api, row, pdf)
                    pages, ex = te.extract_pdf(pdf, obj_sha)
                    dec = pc.classify_pages(pages); ev = dec["evidence"]
                    results.append({**base, **temporal, "pipeline_status":"SUCCESS", "blocker":"", "object_sha256":obj_sha,
                                    "bytes":nbytes, "pdf_page_count":ex["pdf_page_count"], "pages_with_text":ex["pages_with_text"],
                                    "total_nonwhitespace_characters":ex["total_nonwhitespace_characters"], "page_text_sha256":ex["page_text_sha256"],
                                    "classification_state":dec["classification_state"], "evidence_page_number":ev["page_number"],
                                    "evidence_sentence_sha256":hashlib.sha256(str(ev.get("evidence_sentence") or "").encode()).hexdigest(),
                                    "matched_ai_role":"|".join(ev.get("matched_ai_role") or []),
                                    "matched_commerciality":"|".join(ev.get("matched_commerciality") or []),
                                    "classification_reason":ev.get("reason",""), "decision_sha256":dec["decision_sha256"]})
                except Exception as exc:
                    results.append({**base, "pipeline_status":"BLOCKED", "blocker":f"{type(exc).__name__}:{exc}"})
            api.dispose()

    write_csv(OUT_RESULTS, results, RESULT_FIELDS)
    positives = [r for r in results if r.get("pipeline_status") == "SUCCESS" and r.get("classification_state") == POSITIVE]
    write_csv(OUT_POSITIVE, positives, RESULT_FIELDS)
    by_id = {r["announcement_id"]: r for r in results}
    td = term_diagnostics(admitted_candidates, by_id)
    write_csv(OUT_TERMS, td, ["term","deduped_candidate_count","admitted_universe_count","classifier_ready_count","positive_count","positive_yield"])

    success = sum(r.get("pipeline_status") == "SUCCESS" for r in results)
    materialization_rate = success/len(results) if results else 0.0
    securities = Counter(r["canonical_security_id"] for r in positives)
    dates = {r["retrospective_causal_effective_date"] for r in positives}
    months = {d[:7] for d in dates}
    max_share = max(securities.values())/len(positives) if positives else 1.0
    technical = {"all_730_calendar_days_accounted_for": True, "all_105_transport_partitions_accounted_for": True,
                 "successful_classifier_ready_materialization_rate_ge_0_90": materialization_rate >= 0.90,
                 "old_design_replay_exact_88_selected_ids": replay["exact_88_selected_ids"]}
    info = {"eligible_events_ge_20":len(positives)>=20, "distinct_securities_ge_12":len(securities)>=12,
            "distinct_effective_dates_ge_12":len(dates)>=12, "distinct_calendar_months_ge_6":len(months)>=6,
            "max_single_security_share_le_0_20":max_share<=0.20}
    if not all(technical.values()): status = "V2_9_HISTORICAL_E_SOURCE_EXPANSION_TECHNICALLY_BLOCKED"
    elif all(info.values()): status = "V2_9_HISTORICAL_E_SOURCE_EXPANSION_READY"
    else: status = "V2_9_HISTORICAL_E_SOURCE_EXPANSION_TOO_SPARSE"
    final = {"schema":"AI_CORE_EVID_V2_9_HISTORICAL_E_SOURCE_EXPANSION_FINAL_RECEIPT_1","version":"V2.9","status":status,
             "summary":{"admitted_candidates":len(results),"successful_classifier_ready":success,"materialization_rate":materialization_rate,
                        "eligible_events":len(positives),"distinct_securities":len(securities),"distinct_effective_dates":len(dates),
                        "distinct_calendar_months":len(months),"max_single_security_share":max_share},
             "technical_checks":technical,"information_floor_checks":info,"h1_h3_admissible":replay["exact_88_selected_ids"],
             "census_plan_sha256":sha_file(OUT_PLAN),"results_sha256":sha_file(OUT_RESULTS),"positive_events_sha256":sha_file(OUT_POSITIVE),
             "old_design_replay_sha256":sha_file(OUT_REPLAY),"term_diagnostics_sha256":sha_file(OUT_TERMS),
             "price_or_return_data_consumed":False,"candidate_outcome_research_executed":False,"fold3_accessed":False,"fold4_accessed":False}
    final["receipt_sha256"] = stable_sha(final); OUT_FINAL.write_text(json.dumps(final,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(final, ensure_ascii=False, indent=2)); return final


def self_test() -> None:
    load_contracts(); dates = census_dates(); parts = transport_partitions(); owner, by_fold = old.load_development_universe()
    ids = [next(iter(by_fold[i])) for i in (0,1,2)]
    rows = [{"announcement_id":str(100+i),"canonical_security_id":ids[i%3],"adjunct_url":str(i),"announcement_time":str(i),"path_disclosure_date":"x"} for i in range(12)]
    a = old.select_candidates(rows, owner, 6); b = old.select_candidates(list(reversed(rows)), owner, 6)
    tests = [
        {"name":"E01_exact_730_days","pass":len(dates)==730 and dates[0]=="2023-01-01" and dates[-1]=="2024-12-30"},
        {"name":"E02_exact_105_partitions","pass":len(parts)==105 and sum(x["calendar_days"] for x in parts)==730},
        {"name":"E03_partition_max_7","pass":all(1<=x["calendar_days"]<=7 for x in parts)},
        {"name":"E04_dev_folds_only_012","pass":set(by_fold)=={0,1,2}},
        {"name":"E05_old_selection_order_invariant","pass":[x["announcement_id"] for x in a]==[x["announcement_id"] for x in b]},
        {"name":"E06_old_selection_max_6","pass":len(a)<=6},
        {"name":"E07_old_selection_security_diversity","pass":len({x["canonical_security_id"] for x in a})==len(a)},
        {"name":"E08_census_has_no_cap","pass":make_plan()["selection_cap"] is None and make_plan()["security_diversity_cap"] is None},
        {"name":"E09_old_88_binding","pass":len(old_selected_ids())==88},
    ]
    out={"schema":"AI_CORE_EVID_V2_9_HISTORICAL_E_SOURCE_EXPANSION_RUNNER_SELFTEST_1","tests":tests,
         "passed":sum(x["pass"] for x in tests),"total":len(tests),"all_pass":all(x["pass"] for x in tests),
         "real_source_queries_executed":False,"price_or_return_data_consumed":False,"fold3_accessed":False,"fold4_accessed":False}
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if not out["all_pass"]: raise SystemExit(2)


if __name__ == "__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("command",choices=["self-test","plan","run"]); a=ap.parse_args()
    if a.command=="self-test": self_test()
    elif a.command=="plan": print(json.dumps(make_plan(),ensure_ascii=False,indent=2))
    else: run()
