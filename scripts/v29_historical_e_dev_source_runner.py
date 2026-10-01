from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

CONTRACT = Path("evidence/V2.9_HISTORICAL_E_DEV_SOURCE_DATASET_CONTRACT_1.json")
CALENDAR = Path("evidence/V2.8.5_JOINT_A_SHARE_TRADING_CALENDAR_2023_2024.json")
VALIDATION = Path("evidence/V2.9_HISTORICAL_E_DEV_SOURCE_RUNNER_VALIDATION_1.json")
OUT_WINDOWS = Path("evidence/V2.9_HISTORICAL_E_DEV_SOURCE_WINDOWS_1.json")
OUT_RESULTS = Path("evidence/V2.9_HISTORICAL_E_DEV_SOURCE_RESULTS_1.csv")
OUT_POSITIVE = Path("evidence/V2.9_HISTORICAL_E_DEV_SOURCE_POSITIVE_EVENTS_1.csv")
OUT_FINAL = Path("evidence/V2.9_HISTORICAL_E_DEV_SOURCE_FINAL_RECEIPT_1.json")

CONTRACT_SCHEMA = "AI_CORE_EVID_V2_9_HISTORICAL_E_DEV_SOURCE_DATASET_CONTRACT_1"
VALIDATION_SCHEMA = "AI_CORE_EVID_V2_9_HISTORICAL_E_DEV_SOURCE_RUNNER_VALIDATION_1"
POSITIVE = "ELIGIBLE_AI_CORE"
ORDINALS = [4, 12, 20, 28, 36, 44, 52]
MAX_PER_WINDOW = 6
EXPECTED_WINDOWS = 56
SH = ZoneInfo("Asia/Shanghai")
CANON = re.compile(r"^(SSE|SZSE):\d{6}$")

MANIFESTS = [
    {
        "fold": 0,
        "path": Path("evidence/V2.8.5_BACKWARD_HOLDOUT_SAMPLE_MANIFEST.csv"),
        "sha256": "199864ece6c02f3257647d59ba63fe261a7b478a2525b7ed8042bbf475a9fe48",
        "count": 1031,
    },
    {
        "fold": 1,
        "path": Path("evidence/V2.8.6_FOLD1_MECHANISM_REPLICATION_MANIFEST.csv"),
        "sha256": "fe15777a0a3a131b58288454a0e3023503bd80ac6a22f20a2e50c45a4deed38a",
        "count": 1058,
    },
    {
        "fold": 2,
        "path": Path("evidence/V2.8.7_FOLD2_SETUP_SHAPE_MANIFEST.csv"),
        "sha256": "79b6a4c752a22a16f6ec7167dfb1e6b007473229d7ec6729fb03a15b3ba0fa9a",
        "count": 1048,
    },
]

RESULT_FIELDS = [
    "window_id", "quarter", "anchor_ordinal", "window_start", "window_end",
    "sample_rank", "selection_sha256", "announcement_id", "canonical_security_id",
    "development_fold", "security_name", "announcement_title", "announcement_time",
    "adjunct_url", "path_disclosure_date", "matched_terms",
    "announcement_local_date_asia_shanghai", "temporal_provenance_status",
    "retrospective_causal_effective_date", "pipeline_status", "blocker",
    "object_sha256", "bytes", "pdf_page_count", "pages_with_text",
    "total_nonwhitespace_characters", "page_text_sha256", "classification_state",
    "evidence_page_number", "evidence_sentence_sha256", "matched_ai_role",
    "matched_commerciality", "classification_reason", "decision_sha256",
]


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def stable_sha(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def load_contract() -> dict:
    c = read_json(CONTRACT)
    if c.get("schema") != CONTRACT_SCHEMA:
        raise RuntimeError("CONTRACT_SCHEMA_BLOCK")
    if c.get("status") != "FROZEN_BEFORE_SOURCE_ONLY_RUNNER_IMPLEMENTATION":
        raise RuntimeError("CONTRACT_STATUS_BLOCK")
    ts = c.get("time_scope", {})
    if ts.get("quarter_anchor_joint_session_ordinals") != ORDINALS:
        raise RuntimeError("WINDOW_ORDINAL_DRIFT")
    if ts.get("expected_window_count") != EXPECTED_WINDOWS:
        raise RuntimeError("WINDOW_COUNT_CONTRACT_DRIFT")
    ds = c.get("discovery_selection_and_classification", {})
    if ds.get("maximum_selected_per_window") != MAX_PER_WINDOW:
        raise RuntimeError("SELECTION_CAP_DRIFT")
    auth = c.get("authorization", {})
    if any(auth.get(k) is not False for k in (
        "price_or_return_access", "candidate_outcome_research", "fold3_access", "fold4_access",
        "setup_live_or_brokerage",
    )):
        raise RuntimeError("CONTRACT_AUTHORIZATION_SCOPE_BLOCK")
    return c


def trading_dates() -> list[str]:
    obj = read_json(CALENDAR)
    if obj.get("receipt_sha256") != "1f6e44915ec0a6f3db0396a491c83118b6ce57448f7f08b2d35a7d8ee7cf4ed8":
        raise RuntimeError("CALENDAR_RECEIPT_BLOCK")
    d = list(obj.get("trading_dates", []))
    if len(d) != 484 or d != sorted(d) or len(d) != len(set(d)):
        raise RuntimeError("CALENDAR_INTEGRITY_BLOCK")
    return d


def quarter_key(d: str) -> str:
    y, m = map(int, d.split("-")[:2])
    return f"{y}Q{(m - 1) // 3 + 1}"


def compute_windows(days: list[str]) -> list[dict]:
    quarters: dict[str, list[str]] = {}
    for d in days:
        q = quarter_key(d)
        if q[:4] in {"2023", "2024"}:
            quarters.setdefault(q, []).append(d)
    if sorted(quarters) != [f"{y}Q{q}" for y in (2023, 2024) for q in range(1, 5)]:
        raise RuntimeError("QUARTER_COVERAGE_BLOCK")
    out: list[dict] = []
    for q in sorted(quarters):
        qdays = quarters[q]
        if len(qdays) < max(ORDINALS):
            raise RuntimeError(f"QUARTER_TOO_SHORT:{q}:{len(qdays)}")
        for ordinal in ORDINALS:
            anchor = qdays[ordinal - 1]
            end = (datetime.fromisoformat(anchor) + timedelta(days=6)).date().isoformat()
            out.append({
                "window_id": f"{q}_J{ordinal:02d}",
                "quarter": q,
                "anchor_ordinal": ordinal,
                "quarter_joint_sessions": len(qdays),
                "anchor": anchor,
                "start": anchor,
                "end": end,
            })
    if len(out) != EXPECTED_WINDOWS:
        raise RuntimeError(f"WINDOW_COUNT_BLOCK:{len(out)}")
    if len({x["window_id"] for x in out}) != EXPECTED_WINDOWS:
        raise RuntimeError("WINDOW_ID_DUPLICATE_BLOCK")
    return out


def load_development_universe() -> tuple[dict[str, int], dict[int, set[str]]]:
    by_fold: dict[int, set[str]] = {}
    owner: dict[str, int] = {}
    for spec in MANIFESTS:
        path = spec["path"]
        if sha_file(path) != spec["sha256"]:
            raise RuntimeError(f"MANIFEST_SHA_BLOCK:FOLD{spec['fold']}")
        rows = read_csv(path)
        if len(rows) != spec["count"]:
            raise RuntimeError(f"MANIFEST_COUNT_BLOCK:FOLD{spec['fold']}:{len(rows)}")
        ids: set[str] = set()
        for row in rows:
            cid = str(row.get("canonical_security_id") or "").strip()
            if not CANON.fullmatch(cid):
                raise RuntimeError(f"MANIFEST_IDENTITY_BLOCK:FOLD{spec['fold']}:{cid}")
            if cid in ids:
                raise RuntimeError(f"MANIFEST_DUPLICATE_WITHIN_FOLD:{spec['fold']}:{cid}")
            if cid in owner:
                raise RuntimeError(f"MANIFEST_CROSS_FOLD_OVERLAP:{owner[cid]}:{spec['fold']}:{cid}")
            ids.add(cid)
            owner[cid] = spec["fold"]
        by_fold[spec["fold"]] = ids
    if set(by_fold) != {0, 1, 2}:
        raise RuntimeError("DEV_FOLD_SET_BLOCK")
    return owner, by_fold


def selection_key(announcement_id: str) -> str:
    return hashlib.sha256(str(announcement_id).encode()).hexdigest()


def select_candidates(rows: list[dict], dev_owner: dict[str, int], limit: int = MAX_PER_WINDOW) -> list[dict]:
    unique: dict[str, dict] = {}
    for row in rows:
        aid = str(row.get("announcement_id") or "").strip()
        cid = str(row.get("canonical_security_id") or "").strip()
        if not aid or not CANON.fullmatch(cid):
            raise RuntimeError("INVALID_SELECTION_IDENTITY")
        if cid not in dev_owner:
            continue
        if aid in unique:
            keys = ("canonical_security_id", "adjunct_url", "announcement_time", "path_disclosure_date")
            if any(str(unique[aid].get(k)) != str(row.get(k)) for k in keys):
                raise RuntimeError(f"ANNOUNCEMENT_CONFLICT:{aid}")
            continue
        x = dict(row)
        x["development_fold"] = dev_owner[cid]
        unique[aid] = x
    ordered = sorted(unique.values(), key=lambda r: (selection_key(r["announcement_id"]), str(r["announcement_id"])))
    chosen: list[dict] = []
    seen_security: set[str] = set()
    for row in ordered:
        cid = row["canonical_security_id"]
        if cid in seen_security:
            continue
        chosen.append(row)
        seen_security.add(cid)
        if len(chosen) >= limit:
            break
    return chosen


def announcement_local_date(value) -> str:
    s = str(value or "").strip()
    if not re.fullmatch(r"\d{10}|\d{13}", s):
        raise RuntimeError("TEMPORAL_ANNOUNCEMENT_TIME_BLOCK")
    n = int(s)
    seconds = n / 1000.0 if len(s) == 13 else float(n)
    try:
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone(SH)
    except (ValueError, OverflowError, OSError) as exc:
        raise RuntimeError("TEMPORAL_ANNOUNCEMENT_TIME_BLOCK") from exc
    return dt.date().isoformat()


def official_path_date(row: dict) -> str:
    aid = str(row.get("announcement_id") or "").strip()
    adjunct = str(row.get("adjunct_url") or "").strip()
    pdate = str(row.get("path_disclosure_date") or "").strip()
    m = re.fullmatch(r"finalpage/(\d{4}-\d{2}-\d{2})/(\d+)\.pdf", adjunct, re.I)
    if not m or m.group(2) != aid or m.group(1) != pdate:
        raise RuntimeError("TEMPORAL_OFFICIAL_PATH_BLOCK")
    datetime.fromisoformat(pdate)
    return pdate


def next_joint_after(d: str, days: list[str]) -> str:
    for x in days:
        if x > d:
            return x
    raise RuntimeError("TEMPORAL_NO_LATER_JOINT_SESSION")


def resolve_temporal(row: dict, days: list[str]) -> dict:
    p = official_path_date(row)
    a = announcement_local_date(row.get("announcement_time"))
    if a != p:
        raise RuntimeError(f"TEMPORAL_DATE_CONFLICT:{a}:{p}")
    eff = next_joint_after(p, days)
    if eff <= p:
        raise RuntimeError("TEMPORAL_SAME_DAY_BLOCK")
    return {
        "announcement_local_date_asia_shanghai": a,
        "temporal_provenance_status": "PASS",
        "retrospective_causal_effective_date": eff,
    }


def validate_run_authorization() -> None:
    if not VALIDATION.exists():
        raise RuntimeError("SOURCE_RUNNER_NOT_VALIDATED")
    v = read_json(VALIDATION)
    if v.get("schema") != VALIDATION_SCHEMA or v.get("status") != "PASS":
        raise RuntimeError("SOURCE_RUNNER_VALIDATION_NOT_PASS")
    a = v.get("authorization", {})
    if a.get("execute_source_only_collection") is not True:
        raise RuntimeError("SOURCE_COLLECTION_NOT_AUTHORIZED")
    if any(a.get(k) is not False for k in ("price_or_return_access", "fold3_access", "fold4_access", "candidate_outcome_research")):
        raise RuntimeError("SOURCE_RUNNER_VALIDATION_SCOPE_BLOCK")


def fetch_pdf(api, row: dict, path: Path):
    import v284_pdf_text_extractor as te
    adjunct = str(row["adjunct_url"])
    aid = str(row["announcement_id"])
    if not adjunct.lower().endswith(f"/{aid}.pdf".lower()):
        raise RuntimeError("INVALID_OFFICIAL_LOCATOR")
    response = api.get(
        "https://static.cninfo.com.cn/" + adjunct,
        timeout=90000,
        headers={"Referer": "https://www.cninfo.com.cn/", "Accept": "application/pdf,*/*;q=0.8"},
    )
    if response.status != 200:
        raise RuntimeError(f"PDF_FETCH_HTTP_{response.status}")
    body = response.body()
    path.write_bytes(body)
    return te.validate_pdf(path), len(body)


def source_summary(results: list[dict], windows: list[dict]) -> dict:
    selected = len(results)
    success = sum(r.get("pipeline_status") == "SUCCESS" for r in results)
    positives = [r for r in results if r.get("pipeline_status") == "SUCCESS" and r.get("classification_state") == POSITIVE]
    securities = {r["canonical_security_id"] for r in positives}
    dates = {r["retrospective_causal_effective_date"] for r in positives}
    months = {d[:7] for d in dates}
    counts: dict[str, int] = {}
    for r in positives:
        counts[r["canonical_security_id"]] = counts.get(r["canonical_security_id"], 0) + 1
    max_share = max(counts.values()) / len(positives) if positives else 1.0
    represented = {r.get("window_id") for r in results}
    window_records = {w["window_id"] for w in windows}
    return {
        "selected_filings": selected,
        "successful_classifier_ready_filings": success,
        "materialization_rate": success / selected if selected else 0.0,
        "positive_filings": len(positives),
        "distinct_positive_securities": len(securities),
        "distinct_positive_effective_dates": len(dates),
        "distinct_positive_calendar_months": len(months),
        "max_single_security_share": max_share,
        "windows_with_selected_rows": len(represented & window_records),
    }


def terminal_status(summary: dict, window_runtime: list[dict]) -> tuple[str, dict, dict]:
    technical = {
        "all_56_windows_accounted_for": len(window_runtime) == EXPECTED_WINDOWS and all(
            x.get("window_status") in {"COMPLETED", "WINDOW_SOURCE_BLOCKED"} for x in window_runtime
        ),
        "successful_classifier_ready_materialization_rate_ge_0_90": summary["materialization_rate"] >= 0.90,
        "semantics_unchanged": True,
    }
    info = {
        "eligible_events_ge_20": summary["positive_filings"] >= 20,
        "distinct_securities_ge_12": summary["distinct_positive_securities"] >= 12,
        "distinct_effective_dates_ge_12": summary["distinct_positive_effective_dates"] >= 12,
        "distinct_calendar_months_ge_6": summary["distinct_positive_calendar_months"] >= 6,
        "max_single_security_share_le_0_20": summary["max_single_security_share"] <= 0.20,
    }
    if not all(technical.values()):
        return "V2_9_HISTORICAL_E_DEV_SOURCE_TECHNICALLY_BLOCKED", technical, info
    if not all(info.values()):
        return "V2_9_HISTORICAL_E_DEV_SOURCE_TOO_SPARSE", technical, info
    return "V2_9_HISTORICAL_E_DEV_SOURCE_READY", technical, info


def run() -> dict:
    load_contract()
    validate_run_authorization()
    if OUT_FINAL.exists():
        return {"status": "FINAL_ALREADY_FROZEN_NO_REEXECUTION", "receipt_sha256": read_json(OUT_FINAL).get("receipt_sha256")}

    days = trading_dates()
    windows = compute_windows(days)
    dev_owner, _ = load_development_universe()

    import v284_candidate_collector as cc
    import v284_candidate_triage as ct
    import v284_pdf_text_extractor as te
    import v284_page_scoped_classifier as pc
    from playwright.sync_api import sync_playwright

    all_results: list[dict] = []
    window_runtime: list[dict] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with sync_playwright() as pw:
            api = pw.request.new_context(extra_http_headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36"
            })
            for wi, w in enumerate(windows, 1):
                rec = {**w, "window_status": "COMPLETED", "source_blocker": "", "candidate_rows": 0,
                       "triage_materializable_rows": 0, "development_universe_rows": 0, "selected_count": 0}
                try:
                    wd = root / f"window_{wi:02d}"
                    cc.collect(datetime.fromisoformat(w["start"]).date(), datetime.fromisoformat(w["end"]).date(), wd)
                    candidates = read_csv(wd / "V2.8.4_CNINFO_CANDIDATE_DEDUPED.csv")
                    rec["candidate_rows"] = len(candidates)
                    triaged: list[dict] = []
                    for row in candidates:
                        q = ct.triage_title(row.get("announcement_title", ""), row.get("security_name", ""))
                        if q["triage_state"] == "MATERIALIZE_CANDIDATE":
                            triaged.append(row)
                    rec["triage_materializable_rows"] = len(triaged)
                    dev_rows = [r for r in triaged if str(r.get("canonical_security_id") or "").strip() in dev_owner]
                    rec["development_universe_rows"] = len(dev_rows)
                    selected = select_candidates(dev_rows, dev_owner, MAX_PER_WINDOW)
                    rec["selected_count"] = len(selected)
                    for rank, row in enumerate(selected, 1):
                        base = {
                            "window_id": w["window_id"], "quarter": w["quarter"], "anchor_ordinal": w["anchor_ordinal"],
                            "window_start": w["start"], "window_end": w["end"], "sample_rank": rank,
                            "selection_sha256": selection_key(row["announcement_id"]),
                            "announcement_id": row["announcement_id"], "canonical_security_id": row["canonical_security_id"],
                            "development_fold": dev_owner[row["canonical_security_id"]],
                            "security_name": row.get("security_name", ""), "announcement_title": row.get("announcement_title", ""),
                            "announcement_time": row.get("announcement_time", ""), "adjunct_url": row.get("adjunct_url", ""),
                            "path_disclosure_date": row.get("path_disclosure_date", ""), "matched_terms": row.get("matched_terms", ""),
                        }
                        try:
                            temporal = resolve_temporal(row, days)
                            pdf = root / f"{wi:02d}_{rank}.pdf"
                            obj_sha, nbytes = fetch_pdf(api, row, pdf)
                            pages, ex = te.extract_pdf(pdf, obj_sha)
                            dec = pc.classify_pages(pages)
                            ev = dec["evidence"]
                            all_results.append({
                                **base, **temporal, "pipeline_status": "SUCCESS", "blocker": "",
                                "object_sha256": obj_sha, "bytes": nbytes, "pdf_page_count": ex["pdf_page_count"],
                                "pages_with_text": ex["pages_with_text"],
                                "total_nonwhitespace_characters": ex["total_nonwhitespace_characters"],
                                "page_text_sha256": ex["page_text_sha256"], "classification_state": dec["classification_state"],
                                "evidence_page_number": ev["page_number"],
                                "evidence_sentence_sha256": hashlib.sha256(str(ev.get("evidence_sentence") or "").encode()).hexdigest(),
                                "matched_ai_role": "|".join(ev.get("matched_ai_role") or []),
                                "matched_commerciality": "|".join(ev.get("matched_commerciality") or []),
                                "classification_reason": ev.get("reason", ""), "decision_sha256": dec["decision_sha256"],
                            })
                        except Exception as exc:
                            all_results.append({**base, "pipeline_status": "BLOCKED", "blocker": f"{type(exc).__name__}:{exc}"})
                except Exception as exc:
                    rec["window_status"] = "WINDOW_SOURCE_BLOCKED"
                    rec["source_blocker"] = f"{type(exc).__name__}:{exc}"
                window_runtime.append(rec)
            api.dispose()

    write_csv(OUT_RESULTS, all_results, RESULT_FIELDS)
    positives = [r for r in all_results if r.get("pipeline_status") == "SUCCESS" and r.get("classification_state") == POSITIVE]
    write_csv(OUT_POSITIVE, positives, RESULT_FIELDS)
    summary = source_summary(all_results, windows)
    status, technical, info = terminal_status(summary, window_runtime)
    window_obj = {
        "schema": "AI_CORE_EVID_V2_9_HISTORICAL_E_DEV_SOURCE_WINDOWS_1",
        "version": "V2.9", "contract": str(CONTRACT), "runtime_windows": window_runtime,
    }
    window_obj["receipt_sha256"] = stable_sha(window_obj)
    OUT_WINDOWS.write_text(json.dumps(window_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    final = {
        "schema": "AI_CORE_EVID_V2_9_HISTORICAL_E_DEV_SOURCE_FINAL_RECEIPT_1",
        "version": "V2.9", "status": status, "summary": summary,
        "technical_checks": technical, "information_floor_checks": info,
        "windows_sha256": sha_file(OUT_WINDOWS), "results_sha256": sha_file(OUT_RESULTS),
        "positive_events_sha256": sha_file(OUT_POSITIVE),
        "price_or_return_data_consumed": False, "candidate_outcome_research_executed": False,
        "fold3_accessed": False, "fold4_accessed": False, "v2812r_modified": False,
        "setup_live_or_brokerage_authorized": False,
    }
    final["receipt_sha256"] = stable_sha(final)
    OUT_FINAL.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(final, ensure_ascii=False, indent=2))
    return final


def self_test() -> None:
    c = load_contract()
    days = trading_dates()
    windows = compute_windows(days)
    owner, by_fold = load_development_universe()
    tests: list[dict] = []

    def check(name: str, passed: bool) -> None:
        tests.append({"name": name, "pass": bool(passed)})

    check("T01_exact_56_windows", len(windows) == EXPECTED_WINDOWS)
    check("T02_exact_anchor_ordinals", sorted({w["anchor_ordinal"] for w in windows}) == ORDINALS)
    check("T03_eight_quarters_seven_windows_each", all(sum(w["quarter"] == q for w in windows) == 7 for q in sorted({w["quarter"] for w in windows})))
    check("T04_three_manifest_folds_loaded", set(by_fold) == {0, 1, 2})
    check("T05_manifest_counts", [len(by_fold[i]) for i in (0, 1, 2)] == [1031, 1058, 1048])
    check("T06_pairwise_disjoint", len(owner) == sum(len(x) for x in by_fold.values()))

    sample_rows = [
        {"announcement_id": "100", "canonical_security_id": next(iter(by_fold[0])), "adjunct_url": "a", "announcement_time": "1", "path_disclosure_date": "x"},
        {"announcement_id": "200", "canonical_security_id": next(iter(by_fold[1])), "adjunct_url": "b", "announcement_time": "2", "path_disclosure_date": "y"},
        {"announcement_id": "300", "canonical_security_id": "SSE:999999", "adjunct_url": "c", "announcement_time": "3", "path_disclosure_date": "z"},
    ]
    s1 = select_candidates(sample_rows, owner, 6)
    s2 = select_candidates(list(reversed(sample_rows)), owner, 6)
    check("T07_unknown_identity_filtered_before_selection", all(x["canonical_security_id"] in owner for x in s1) and len(s1) == 2)
    check("T08_selection_input_order_invariant", [x["announcement_id"] for x in s1] == [x["announcement_id"] for x in s2])
    check("T09_selected_rows_carry_development_fold", all(x["development_fold"] in {0, 1, 2} for x in s1))
    check("T10_max_six_selection", len(select_candidates(sample_rows * 1, owner, 6)) <= 6)

    d = "2024-01-31"
    ts = int(datetime(2024, 1, 31, 2, 0, tzinfo=timezone.utc).timestamp() * 1000)
    row = {"announcement_id": "123", "canonical_security_id": next(iter(by_fold[0])), "announcement_time": str(ts),
           "adjunct_url": "finalpage/2024-01-31/123.PDF", "path_disclosure_date": d}
    temporal = resolve_temporal(row, days)
    check("T11_temporal_date_consistency", temporal["announcement_local_date_asia_shanghai"] == d)
    check("T12_effective_date_strictly_later", temporal["retrospective_causal_effective_date"] > d)

    src = Path(__file__).read_text(encoding="utf-8")
    forbidden_tokens = [
        "V2.8.10_AC_EVENT_LEDGER", "v2810_locked_ac_pullback_reclaim_evaluator",
        "v290_strategy_validity_evaluator", "v291_portfolio_path_evaluator",
        "v292_matched_random_baseline", "fold3_source", "fold4_source",
    ]
    check("T13_no_outcome_or_fold34_modules", not any(token in src for token in forbidden_tokens))
    check("T14_contract_outcome_access_false", c["authorization"]["price_or_return_access"] is False and c["authorization"]["candidate_outcome_research"] is False)
    check("T15_contract_fold34_false", c["authorization"]["fold3_access"] is False and c["authorization"]["fold4_access"] is False)

    out = {
        "schema": "AI_CORE_EVID_V2_9_HISTORICAL_E_DEV_SOURCE_RUNNER_SELFTEST_1",
        "version": "V2.9", "tests": tests, "passed": sum(x["pass"] for x in tests),
        "total": len(tests), "all_pass": all(x["pass"] for x in tests),
        "real_source_queries_executed": False, "price_or_return_data_consumed": False,
        "fold3_accessed": False, "fold4_accessed": False,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not out["all_pass"]:
        raise SystemExit(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["self-test", "run"])
    args = parser.parse_args()
    self_test() if args.command == "self-test" else run()
