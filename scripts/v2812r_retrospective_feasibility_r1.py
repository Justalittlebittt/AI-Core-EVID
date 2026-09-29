from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import v2811_bounded_e_reconstruction_retry1 as base

CONTRACT = Path("evidence/V2.8.12R_RETROSPECTIVE_FEASIBILITY_SAMPLING_AND_OUTCOME_CONTRACT.json")
AMENDMENT = Path("evidence/V2.8.12R_RETROSPECTIVE_FEASIBILITY_CONTRACT_AMENDMENT_1.json")
OLD_FINAL = Path("evidence/V2.8.11_FINAL_RECORD.json")
WINDOWS = Path("evidence/retrospective_feasibility/V2.8.12R_EXPANSION_WINDOWS.json")
VALIDATION = Path("evidence/retrospective_feasibility/V2.8.12R_R1_RUNNER_VALIDATION_RECEIPT.json")
OUT_DIR = Path("evidence/retrospective_feasibility")
OUT_RESULTS = OUT_DIR / "V2.8.12R_EXPANSION_RESULTS.csv"
OUT_COHORT = OUT_DIR / "V2.8.12R_FROZEN_EVENT_COHORT.csv"
OUT_RECEIPT = OUT_DIR / "V2.8.12R_EVENT_COHORT_RECEIPT.json"

SCHEMA = "AI_CORE_EVID_V2_8_12R_RETROSPECTIVE_FEASIBILITY_SAMPLING_AND_OUTCOME_CONTRACT_V1"
AMENDMENT_SCHEMA = "AI_CORE_EVID_V2_8_12R_RETROSPECTIVE_FEASIBILITY_CONTRACT_AMENDMENT_V1"
MAX_PER_WINDOW = 6
MAX_NEW_TOTAL = 96
ANCHOR_SESSIONS = (1, 41)
POSITIVE = "ELIGIBLE_AI_CORE"

RESULT_FIELDS = [
    "quarter", "anchor_session", "window_start", "window_end", "sample_rank", "selection_sha256",
    "announcement_id", "canonical_security_id", "security_name", "announcement_title", "announcement_time",
    "adjunct_url", "path_disclosure_date", "matched_terms", "announcement_local_date_asia_shanghai",
    "temporal_provenance_status", "retrospective_causal_effective_date", "pipeline_status", "blocker",
    "object_sha256", "bytes", "pdf_page_count", "pages_with_text", "total_nonwhitespace_characters",
    "page_text_sha256", "classification_state", "evidence_page_number", "evidence_sentence_sha256",
    "matched_ai_role", "matched_commerciality", "classification_reason", "decision_sha256"
]

COHORT_FIELDS = [
    "cohort_source", "quarter", "announcement_id", "canonical_security_id", "security_name",
    "announcement_title", "disclosure_date", "retrospective_causal_effective_date",
    "classification_state", "matched_ai_role", "matched_commerciality", "object_sha256", "decision_sha256"
]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_contract() -> tuple[dict, dict]:
    c = read_json(CONTRACT)
    a = read_json(AMENDMENT)
    if c.get("schema") != SCHEMA:
        raise RuntimeError("R1_CONTRACT_SCHEMA_BLOCK")
    if c.get("status") != "FROZEN_BEFORE_ADDITIONAL_HISTORICAL_CANDIDATE_QUERY_OR_PRICE_OUTCOME_ACCESS":
        raise RuntimeError("R1_CONTRACT_STATUS_BLOCK")
    if a.get("schema") != AMENDMENT_SCHEMA or a.get("status") != "ACTIVE_PRE_OUTCOME_CLARIFICATION":
        raise RuntimeError("R1_AMENDMENT_BINDING_BLOCK")
    r = c["stage_R1_outcome_blind_event_expansion"]["new_window_rule"]
    s = c["stage_R1_outcome_blind_event_expansion"]["discovery_and_selection"]
    if tuple(r["anchors_per_quarter"]) != ANCHOR_SESSIONS or r["new_window_count"] != 16:
        raise RuntimeError("R1_WINDOW_CONTRACT_BLOCK")
    if s["maximum_selected_per_new_window"] != MAX_PER_WINDOW or s["maximum_new_selected_total"] != MAX_NEW_TOTAL:
        raise RuntimeError("R1_SELECTION_CAP_CONTRACT_BLOCK")
    if c["stage_R1_outcome_blind_event_expansion"]["price_or_return_data_access_during_R1"] is not False:
        raise RuntimeError("R1_PRICE_FIREWALL_BLOCK")
    if a["clarification"]["issuer_grouping_key"] != "canonical_security_id":
        raise RuntimeError("R1_GROUPING_KEY_BLOCK")
    return c, a


def quarter_days(days: list[str]) -> dict[str, list[str]]:
    q: dict[str, list[str]] = {}
    for d in days:
        y, m = map(int, d.split("-")[:2])
        if y not in (2023, 2024):
            continue
        key = f"{y}Q{(m - 1) // 3 + 1}"
        q.setdefault(key, []).append(d)
    return q


def compute_new_windows(days: list[str]) -> list[dict]:
    q = quarter_days(days)
    out = []
    for key in sorted(q):
        sessions = q[key]
        if len(sessions) < max(ANCHOR_SESSIONS):
            raise RuntimeError(f"R1_QUARTER_TOO_SHORT:{key}:{len(sessions)}")
        for anchor_session in ANCHOR_SESSIONS:
            anchor = sessions[anchor_session - 1]
            end = (datetime.fromisoformat(anchor) + timedelta(days=6)).date().isoformat()
            out.append({
                "quarter": key,
                "quarter_joint_sessions": len(sessions),
                "anchor_session": anchor_session,
                "anchor": anchor,
                "start": anchor,
                "end": end,
            })
    return out


def intervals_overlap(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    return not (a_end < b_start or b_end < a_start)


def validate_nonoverlap(new_windows: list[dict]) -> bool:
    old_by_q = {w["quarter"]: w for w in base.FROZEN_WINDOWS}
    for w in new_windows:
        old = old_by_q[w["quarter"]]
        if intervals_overlap(w["start"], w["end"], old["start"], old["end"]):
            return False
    return True


def old_positive_rows() -> list[dict]:
    obj = read_json(OLD_FINAL)
    rows = []
    for e in obj.get("reconstructed_positive_events", []):
        rows.append({
            "cohort_source": "V2.8.11_RECONSTRUCTED_POSITIVE",
            "quarter": e["quarter"],
            "announcement_id": str(e["announcement_id"]),
            "canonical_security_id": e["canonical_security_id"],
            "security_name": e.get("security_name", ""),
            "announcement_title": e.get("title", ""),
            "disclosure_date": e["disclosure_date"],
            "retrospective_causal_effective_date": e["retrospective_causal_effective_date"],
            "classification_state": POSITIVE,
            "matched_ai_role": "|".join(e.get("matched_ai_role") or []),
            "matched_commerciality": "|".join(e.get("matched_commerciality") or []),
            "object_sha256": "",
            "decision_sha256": "",
        })
    return rows


def filter_seen(rows: list[dict], seen: set[str]) -> list[dict]:
    out = []
    local = set()
    for r in rows:
        aid = str(r.get("announcement_id") or "").strip()
        if not aid or aid in seen or aid in local:
            continue
        local.add(aid)
        out.append(r)
    return out


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def imported_module_names() -> set[str]:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    return names


def self_test(write_outputs: bool = False) -> dict:
    c, _ = load_contract()
    days = base.trading_dates()
    windows = compute_new_windows(days)
    tests = []

    def ck(name: str, cond: bool):
        tests.append({"name": name, "pass": bool(cond)})

    ck("R101_exact_16_windows", len(windows) == 16)
    ck("R102_two_windows_per_quarter", all(sum(x["quarter"] == q for x in windows) == 2 for q in sorted(quarter_days(days))))
    ck("R103_anchor_sessions_exact", all(w["anchor_session"] in ANCHOR_SESSIONS for w in windows))
    q = quarter_days(days)
    ck("R104_anchor_dates_exact", all(w["anchor"] == q[w["quarter"]][w["anchor_session"] - 1] for w in windows))
    ck("R105_no_overlap_existing_21st_windows", validate_nonoverlap(windows))
    ck("R106_unique_new_windows", len({(w["start"], w["end"]) for w in windows}) == 16)

    synthetic = []
    for i in range(10):
        synthetic.append({
            "announcement_id": str(1000 + i),
            "canonical_security_id": f"SSE:{600000 + (i if i < 7 else 0):06d}",
            "adjunct_url": f"finalpage/2024-01-02/{1000+i}.pdf",
            "announcement_time": "1704153600000",
            "path_disclosure_date": "2024-01-02",
        })
    a = base.select_candidates(synthetic, MAX_PER_WINDOW)
    b = base.select_candidates(list(reversed(synthetic)), MAX_PER_WINDOW)
    ck("R107_selection_input_order_invariant", [x["announcement_id"] for x in a] == [x["announcement_id"] for x in b])
    ck("R108_selection_max_six", len(a) <= MAX_PER_WINDOW)
    ck("R109_one_security_per_window", len({x["canonical_security_id"] for x in a}) == len(a))

    seen = {"1001", "1003"}
    fd = filter_seen(synthetic, seen)
    ck("R110_cross_cohort_announcement_dedup", all(x["announcement_id"] not in seen for x in fd) and len(fd) == 8)
    ck("R111_global_cap_contract_96", MAX_PER_WINDOW * len(windows) == MAX_NEW_TOTAL)

    mods = {m.lower() for m in imported_module_names()}
    forbidden_fragments = ("outcome", "stock_kline", "benchmark_kline", "fold3", "fold4")
    ck("R112_no_price_or_outcome_module_import", not any(any(f in m for f in forbidden_fragments) for m in mods))
    ck("R113_R1_contract_price_access_false", c["stage_R1_outcome_blind_event_expansion"]["price_or_return_data_access_during_R1"] is False)
    ck("R114_prospective_gate_not_changed", c["governance"]["prospective_gate_thresholds_changed"] is False)

    old = old_positive_rows()
    ck("R115_exact_three_existing_positive_events", len(old) == 3)
    ck("R116_existing_positive_ids_unique", len({x["announcement_id"] for x in old}) == len(old))

    result = {
        "schema": "AI_CORE_EVID_V2_8_12R_R1_RUNNER_VALIDATION_RECEIPT_V1",
        "version": "V2.8.12R",
        "status": "PASS" if all(x["pass"] for x in tests) else "FAIL",
        "runner": str(Path(__file__)),
        "runner_sha256": sha_file(Path(__file__)),
        "tests": tests,
        "passed": sum(x["pass"] for x in tests),
        "total": len(tests),
        "derived_new_windows": windows,
        "authorization": {
            "execute_R1_bounded_expansion": all(x["pass"] for x in tests),
            "price_or_return_access_during_R1": false,
            "fold3_access": false,
            "fold4_access": false,
            "setup_emission": false,
            "live_authorized": false
        },
    }
    result["receipt_sha256"] = stable_sha(result)
    if write_outputs:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        window_obj = {
            "schema": "AI_CORE_EVID_V2_8_12R_EXPANSION_WINDOWS_V1",
            "version": "V2.8.12R",
            "status": "FROZEN_BEFORE_REAL_CANDIDATE_QUERY",
            "calendar_authority": str(base.CALENDAR),
            "window_rule": "1st and 41st joint A-share trading session of each 2023-2024 quarter, anchor through +6 calendar days inclusive",
            "windows": windows,
        }
        window_obj["receipt_sha256"] = stable_sha(window_obj)
        WINDOWS.write_text(json.dumps(window_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        VALIDATION.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result["status"] != "PASS":
        raise SystemExit(2)
    return result


def validate_real_run_authorization() -> tuple[dict, list[dict]]:
    load_contract()
    if not VALIDATION.exists() or not WINDOWS.exists():
        raise RuntimeError("R1_VALIDATION_OR_WINDOWS_MISSING")
    v = read_json(VALIDATION)
    w = read_json(WINDOWS)
    if v.get("status") != "PASS" or v.get("authorization", {}).get("execute_R1_bounded_expansion") is not True:
        raise RuntimeError("R1_REAL_RUN_NOT_AUTHORIZED")
    if v["authorization"].get("price_or_return_access_during_R1") is not False:
        raise RuntimeError("R1_PRICE_AUTHORIZATION_SCOPE_BLOCK")
    current_sha = sha_file(Path(__file__))
    if v.get("runner_sha256") != current_sha:
        raise RuntimeError("R1_RUNNER_HASH_DRIFT")
    expected = compute_new_windows(base.trading_dates())
    if w.get("windows") != expected:
        raise RuntimeError("R1_FROZEN_WINDOWS_DRIFT")
    return v, expected


def run() -> dict:
    _, windows = validate_real_run_authorization()
    if OUT_RECEIPT.exists():
        return {"status": "R1_COHORT_ALREADY_FROZEN_NO_REEXECUTION", "receipt_sha256": read_json(OUT_RECEIPT).get("receipt_sha256")}

    import v284_candidate_collector as cc
    import v284_candidate_triage as ct
    import v284_pdf_text_extractor as te
    import v284_page_scoped_classifier as pc
    from playwright.sync_api import sync_playwright

    days = base.trading_dates()
    existing = old_positive_rows()
    seen_aids = {r["announcement_id"] for r in existing}
    selected_aids = set(seen_aids)
    all_results: list[dict] = []
    window_records = []

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for wi, w in enumerate(windows, 1):
            wr = {**w, "window_status": "COMPLETED", "source_blocker": "", "candidate_rows": 0,
                  "triage_skipped": 0, "materializable_rows": 0, "selected_count": 0}
            try:
                wd = root / f"window_{wi}"
                # Candidate collector owns its own Playwright context: never nest it under another context.
                cc.collect(datetime.fromisoformat(w["start"]).date(), datetime.fromisoformat(w["end"]).date(), wd)
                dedup = wd / "V2.8.4_CNINFO_CANDIDATE_DEDUPED.csv"
                rows = list(csv.DictReader(dedup.read_text(encoding="utf-8").splitlines()))
                wr["candidate_rows"] = len(rows)
                materializable = []
                skipped = 0
                for row in rows:
                    q = ct.triage_title(row.get("announcement_title", ""), row.get("security_name", ""))
                    if q["triage_state"] == "MATERIALIZE_CANDIDATE":
                        materializable.append(row)
                    else:
                        skipped += 1
                wr["triage_skipped"] = skipped
                wr["materializable_rows"] = len(materializable)
                materializable = filter_seen(materializable, selected_aids)
                selected = base.select_candidates(materializable, MAX_PER_WINDOW)
                wr["selected_count"] = len(selected)
                selected_aids.update(str(x["announcement_id"]) for x in selected)

                if selected:
                    # Direct official PDF access only; no unnecessary CNInfo home preflight.
                    with sync_playwright() as pw:
                        api = pw.request.new_context(extra_http_headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36"
                        })
                        for rank, row in enumerate(selected, 1):
                            base_row = {
                                "quarter": w["quarter"], "anchor_session": w["anchor_session"],
                                "window_start": w["start"], "window_end": w["end"], "sample_rank": rank,
                                "selection_sha256": base.selection_key(row["announcement_id"]),
                                "announcement_id": row["announcement_id"], "canonical_security_id": row["canonical_security_id"],
                                "security_name": row.get("security_name", ""), "announcement_title": row.get("announcement_title", ""),
                                "announcement_time": row.get("announcement_time", ""), "adjunct_url": row.get("adjunct_url", ""),
                                "path_disclosure_date": row.get("path_disclosure_date", ""), "matched_terms": row.get("matched_terms", ""),
                            }
                            try:
                                temporal = base.resolve_temporal(row, days)
                                pdf = root / f"r1_{wi}_{rank}.pdf"
                                object_sha, nbytes = base.fetch_pdf(api, row, pdf)
                                page_rows, ex = te.extract_pdf(pdf, object_sha)
                                dec = pc.classify_pages(page_rows)
                                ev = dec["evidence"]
                                all_results.append({
                                    **base_row, **temporal, "pipeline_status": "SUCCESS", "blocker": "",
                                    "object_sha256": object_sha, "bytes": nbytes,
                                    "pdf_page_count": ex["pdf_page_count"], "pages_with_text": ex["pages_with_text"],
                                    "total_nonwhitespace_characters": ex["total_nonwhitespace_characters"],
                                    "page_text_sha256": ex["page_text_sha256"],
                                    "classification_state": dec["classification_state"],
                                    "evidence_page_number": ev["page_number"],
                                    "evidence_sentence_sha256": hashlib.sha256(str(ev.get("evidence_sentence") or "").encode()).hexdigest(),
                                    "matched_ai_role": "|".join(ev.get("matched_ai_role") or []),
                                    "matched_commerciality": "|".join(ev.get("matched_commerciality") or []),
                                    "classification_reason": ev.get("reason", ""), "decision_sha256": dec["decision_sha256"],
                                })
                            except Exception as ex:
                                all_results.append({**base_row, "pipeline_status": "BLOCKED", "blocker": f"{type(ex).__name__}:{ex}"})
                        api.dispose()
            except Exception as ex:
                wr["window_status"] = "WINDOW_SOURCE_BLOCKED"
                wr["source_blocker"] = f"{type(ex).__name__}:{ex}"
            window_records.append(wr)

    selected_total = sum(int(w["selected_count"]) for w in window_records)
    if selected_total > MAX_NEW_TOTAL:
        raise RuntimeError("R1_GLOBAL_SELECTION_CAP_BLOCK")

    write_csv(OUT_RESULTS, all_results, RESULT_FIELDS)
    new_positive_results = [r for r in all_results if r.get("pipeline_status") == "SUCCESS" and r.get("classification_state") == POSITIVE]

    cohort = list(existing)
    cohort_ids = {r["announcement_id"] for r in cohort}
    for r in new_positive_results:
        aid = str(r["announcement_id"])
        if aid in cohort_ids:
            continue
        cohort_ids.add(aid)
        cohort.append({
            "cohort_source": "V2.8.12R_R1_EXPANSION",
            "quarter": r["quarter"], "announcement_id": aid,
            "canonical_security_id": r["canonical_security_id"], "security_name": r.get("security_name", ""),
            "announcement_title": r.get("announcement_title", ""), "disclosure_date": r["path_disclosure_date"],
            "retrospective_causal_effective_date": r["retrospective_causal_effective_date"],
            "classification_state": POSITIVE, "matched_ai_role": r.get("matched_ai_role", ""),
            "matched_commerciality": r.get("matched_commerciality", ""), "object_sha256": r.get("object_sha256", ""),
            "decision_sha256": r.get("decision_sha256", ""),
        })

    cohort.sort(key=lambda r: (r["retrospective_causal_effective_date"], r["canonical_security_id"], r["announcement_id"]))
    write_csv(OUT_COHORT, cohort, COHORT_FIELDS)

    successful = [r for r in all_results if r.get("pipeline_status") == "SUCCESS"]
    blocked = [r for r in all_results if r.get("pipeline_status") == "BLOCKED"]
    quarter_set = {r["quarter"] for r in cohort}
    cid_counts: dict[str, int] = {}
    for r in cohort:
        cid_counts[r["canonical_security_id"]] = cid_counts.get(r["canonical_security_id"], 0) + 1
    max_share = max(cid_counts.values()) / len(cohort) if cohort else 1.0
    floor = read_json(CONTRACT)["analysis_contract"]["decision_eligibility_sample_floor"]
    sample_floor_pre_outcome = (
        len(cohort) >= floor["frozen_positive_events_min"]
        and len(cid_counts) >= floor["distinct_issuers_min"]
        and len(quarter_set) >= floor["distinct_positive_quarters_min"]
        and max_share <= floor["maximum_single_issuer_event_share"]
    )

    receipt = {
        "schema": "AI_CORE_EVID_V2_8_12R_EVENT_COHORT_RECEIPT_V1",
        "version": "V2.8.12R",
        "status": "R1_EVENT_COHORT_FROZEN_PRICE_OUTCOMES_NOT_YET_READ",
        "new_windows": 16,
        "new_selected_rows": selected_total,
        "new_successful_classifier_ready_rows": len(successful),
        "new_blocked_rows": len(blocked),
        "new_positive_events": len(new_positive_results),
        "existing_positive_events_reused": len(existing),
        "frozen_cohort_events": len(cohort),
        "distinct_canonical_security_ids": len(cid_counts),
        "distinct_positive_quarters": len(quarter_set),
        "maximum_single_security_event_share": max_share,
        "sample_floor_pre_outcome_pass": sample_floor_pre_outcome,
        "window_status_counts": {
            "COMPLETED": sum(w["window_status"] == "COMPLETED" for w in window_records),
            "WINDOW_SOURCE_BLOCKED": sum(w["window_status"] == "WINDOW_SOURCE_BLOCKED" for w in window_records),
        },
        "results_file": str(OUT_RESULTS), "results_sha256": sha_file(OUT_RESULTS),
        "cohort_file": str(OUT_COHORT), "cohort_sha256": sha_file(OUT_COHORT),
        "price_or_return_data_consumed": False,
        "prospective_shadow_ledger_mutated": False,
        "fold3_accessed": False, "fold4_accessed": False,
        "setup_or_live_authorized": False,
        "next_stage": "R2_OUTCOME_SOURCE_PREFLIGHT_AND_RESOLUTION" if sample_floor_pre_outcome else "R2_DESCRIPTIVE_OUTCOME_RESOLUTION_ALLOWED_BUT_NO_FEASIBILITY_VERDICT_UNLESS_FULL_SAMPLE_FLOOR_PASSES",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    OUT_RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("self-test")
    st.add_argument("--write-outputs", action="store_true")
    sub.add_parser("run")
    args = ap.parse_args()
    if args.cmd == "self-test":
        print(json.dumps(self_test(write_outputs=args.write_outputs), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(run(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
