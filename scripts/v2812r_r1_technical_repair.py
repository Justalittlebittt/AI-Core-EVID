from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from pathlib import Path

import v2811_bounded_e_reconstruction_retry1 as base

RESULTS = Path("evidence/retrospective_feasibility/V2.8.12R_EXPANSION_RESULTS.csv")
GATE = Path("evidence/retrospective_feasibility/V2.8.12R_R1_TECHNICAL_GATE_RECEIPT.json")
AMEND2 = Path("evidence/V2.8.12R_RETROSPECTIVE_FEASIBILITY_CONTRACT_AMENDMENT_2.json")
AMBIGUITY = Path("evidence/retrospective_feasibility/V2.8.12R_R1_AMBIGUITY_SET_SELECTION_AUDIT.json")
SOURCE_PROBE = Path("evidence/retrospective_feasibility/V2.8.12R_R1_BLOCKED_WINDOW_IDENTIFICATION_PROBE.json")
OUT_CSV = Path("evidence/retrospective_feasibility/V2.8.12R_R1_TECHNICAL_REPAIR_RESULTS.csv")
OUT_RECEIPT = Path("evidence/retrospective_feasibility/V2.8.12R_R1_TECHNICAL_REPAIR_RECEIPT.json")

NEW_CANDIDATE_ID = "1216331011"
EXPECTED_EXISTING_BLOCKED_IDS = {"1218801205", "1219266476", "1220302463"}

FIELDS = [
    "repair_origin", "quarter", "anchor_session", "window_start", "window_end", "sample_rank",
    "selection_sha256", "announcement_id", "canonical_security_id", "security_name", "announcement_title",
    "announcement_time", "adjunct_url", "path_disclosure_date", "matched_terms",
    "announcement_local_date_asia_shanghai", "temporal_provenance_status",
    "retrospective_causal_effective_date", "pipeline_status", "blocker", "object_sha256", "bytes",
    "pdf_page_count", "pages_with_text", "total_nonwhitespace_characters", "page_text_sha256",
    "classification_state", "evidence_page_number", "evidence_sentence_sha256", "matched_ai_role",
    "matched_commerciality", "classification_reason", "decision_sha256"
]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_scope() -> tuple[dict, dict, list[dict]]:
    gate = read_json(GATE)
    if gate.get("status") != "R1_TECHNICAL_INCOMPLETE_R2_OUTCOME_ACCESS_BLOCKED":
        raise RuntimeError("R1_GATE_STATUS_SCOPE_BLOCK")
    if gate.get("R2_price_or_return_access_authorized") is not False:
        raise RuntimeError("R2_ALREADY_AUTHORIZED_SCOPE_BLOCK")
    if gate.get("price_or_return_data_consumed_in_R1") is not False:
        raise RuntimeError("PRICE_FIREWALL_HISTORY_BLOCK")
    checks = gate.get("checks", {})
    if int(checks.get("selected_filings", -1)) != 41 or int(checks.get("classifier_ready_filings", -1)) != 38:
        raise RuntimeError("ORIGINAL_GATE_COUNT_DRIFT")
    if checks.get("classifier_ready_rate_ge_0_90") is not True:
        raise RuntimeError("ORIGINAL_READY_RATE_NOT_ALREADY_PASS")

    amend = read_json(AMEND2)
    retry = amend.get("retry_semantics_if_incomplete", {})
    required = {
        "same_frozen_windows_only": True,
        "same_deterministic_selection_only": True,
        "replacement_with_next_ranked_announcement_forbidden": True,
        "window_shift_or_expansion_forbidden": True,
        "keyword_or_classifier_change_forbidden": True,
        "price_or_return_access_before_technical_pass": False,
    }
    for key, expected in required.items():
        if retry.get(key) is not expected:
            raise RuntimeError(f"RETRY_CONTRACT_SCOPE_BLOCK:{key}")

    probe = read_json(SOURCE_PROBE)
    if probe.get("price_or_return_data_consumed") is not False or probe.get("classifier_executed") is not False:
        raise RuntimeError("SOURCE_PROBE_SCOPE_BLOCK")
    source_records = probe.get("records", [])
    if len(source_records) != 2 or any(r.get("source_status") != "SOURCE_QUERY_COMPLETED" for r in source_records):
        raise RuntimeError("AMBIGUOUS_WINDOWS_NOT_SOURCE_COMPLETE")

    rows = list(csv.DictReader(RESULTS.read_text(encoding="utf-8").splitlines()))
    by_id = {str(r.get("announcement_id") or ""): r for r in rows if r.get("announcement_id")}
    if NEW_CANDIDATE_ID in by_id:
        raise RuntimeError("NEW_CANDIDATE_ALREADY_PRESENT_IN_FROZEN_RESULTS")

    blocked_rows = [r for r in rows if r.get("pipeline_status") == "BLOCKED"]
    blocked_ids = {str(r.get("announcement_id") or "") for r in blocked_rows}
    if blocked_ids != EXPECTED_EXISTING_BLOCKED_IDS:
        raise RuntimeError(f"EXISTING_BLOCKED_SET_DRIFT:{sorted(blocked_ids)}")
    if any("BLOCKED_TEXT_EXTRACTION:INSUFFICIENT_EMBEDDED_TEXT" not in str(r.get("blocker") or "") for r in blocked_rows):
        raise RuntimeError("EXISTING_BLOCKER_REASON_DRIFT")

    audit = read_json(AMBIGUITY)
    if audit.get("requires_downstream_candidate_repair") is not True:
        raise RuntimeError("AMBIGUITY_AUDIT_NO_REPAIR_REQUIRED")
    if audit.get("historical_blocked_window_identity_required_for_next_step") is not False:
        raise RuntimeError("HISTORICAL_IDENTITY_STILL_REQUIRED_BLOCK")
    if audit.get("price_or_return_data_consumed") is not False or audit.get("classifier_executed") is not False:
        raise RuntimeError("AMBIGUITY_AUDIT_SCOPE_BLOCK")
    recs = audit.get("records", [])
    if len(recs) != 1 or str(recs[0].get("announcement_id")) != NEW_CANDIDATE_ID:
        raise RuntimeError("NEW_CANDIDATE_AUDIT_ID_BLOCK")
    ar = recs[0]
    if ar.get("deterministically_selected") is not True or ar.get("triage_state") != "MATERIALIZE_CANDIDATE":
        raise RuntimeError("NEW_CANDIDATE_SELECTION_BLOCK")

    w = audit["window"]
    target = {
        "repair_origin": "AMBIGUITY_SET_MISSING_SELECTED_CANDIDATE",
        "quarter": w["quarter"],
        "anchor_session": str(w["anchor_session"]),
        "window_start": w["start"],
        "window_end": w["end"],
        "sample_rank": "1",
        "selection_sha256": ar["selection_sha256"],
        "announcement_id": ar["announcement_id"],
        "canonical_security_id": ar["canonical_security_id"],
        "security_name": ar.get("security_name", ""),
        "announcement_title": ar.get("announcement_title", ""),
        "announcement_time": ar.get("announcement_time", ""),
        "adjunct_url": ar.get("adjunct_url", ""),
        "path_disclosure_date": ar.get("path_disclosure_date", ""),
        "matched_terms": ar.get("matched_terms", ""),
    }
    if base.selection_key(target["announcement_id"]) != target["selection_sha256"]:
        raise RuntimeError("NEW_CANDIDATE_SELECTION_HASH_BLOCK")
    return target, gate, blocked_rows


def main() -> None:
    target, gate, existing_blocked = validate_scope()

    import v284_pdf_text_extractor as te
    import v284_page_scoped_classifier as pc
    from playwright.sync_api import sync_playwright

    days = base.trading_dates()
    out = {k: target.get(k, "") for k in FIELDS}

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with sync_playwright() as pw:
            api = pw.request.new_context(extra_http_headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36"
            })
            home = api.get("https://www.cninfo.com.cn/", timeout=30000)
            if home.status != 200:
                raise RuntimeError(f"CNINFO_HOME_HTTP_{home.status}")
            try:
                temporal = base.resolve_temporal(target, days)
                pdf = root / f"repair_{target['announcement_id']}.pdf"
                obj_sha, nbytes = base.fetch_pdf(api, target, pdf)
                page_rows, ex = te.extract_pdf(pdf, obj_sha)
                dec = pc.classify_pages(page_rows)
                evidence = dec["evidence"]
                out.update({
                    **temporal,
                    "pipeline_status": "SUCCESS",
                    "blocker": "",
                    "object_sha256": obj_sha,
                    "bytes": nbytes,
                    "pdf_page_count": ex["pdf_page_count"],
                    "pages_with_text": ex["pages_with_text"],
                    "total_nonwhitespace_characters": ex["total_nonwhitespace_characters"],
                    "page_text_sha256": ex["page_text_sha256"],
                    "classification_state": dec["classification_state"],
                    "evidence_page_number": evidence["page_number"],
                    "evidence_sentence_sha256": hashlib.sha256(str(evidence.get("evidence_sentence") or "").encode()).hexdigest(),
                    "matched_ai_role": "|".join(evidence.get("matched_ai_role") or []),
                    "matched_commerciality": "|".join(evidence.get("matched_commerciality") or []),
                    "classification_reason": evidence.get("reason", ""),
                    "decision_sha256": dec["decision_sha256"],
                })
            except Exception as ex:
                out.update({"pipeline_status": "BLOCKED", "blocker": f"{type(ex).__name__}:{ex}"})
            api.dispose()

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerow(out)

    new_ready = 1 if out.get("pipeline_status") == "SUCCESS" else 0
    reconciled_selected = 42
    reconciled_ready = 38 + new_ready
    ready_rate = reconciled_ready / reconciled_selected

    receipt = {
        "schema": "AI_CORE_EVID_V2_8_12R_R1_TECHNICAL_REPAIR_RECEIPT_V2",
        "version": "V2.8.12R",
        "status": "MISSING_SELECTED_CANDIDATE_MATERIALIZED" if new_ready else "MISSING_SELECTED_CANDIDATE_CLASSIFIER_BLOCKED",
        "authority": str(AMEND2),
        "input_gate_status": gate["status"],
        "repair_scope": {
            "ambiguity_set_missing_selected_id": NEW_CANDIDATE_ID,
            "target_count": 1,
            "existing_three_classifier_blocked_rows_preserved_without_retry": sorted(EXPECTED_EXISTING_BLOCKED_IDS),
            "why_existing_blocked_rows_not_retried": "Original gate already passed classifier-ready-rate >= 0.90; retrying them is unnecessary to close the actual failing all-16-windows/source-completeness condition.",
            "replacement_announcements_used": False,
            "new_or_shifted_windows_used": False,
            "classifier_changed": False,
            "keyword_rule_changed": False,
        },
        "candidate_result": {
            "announcement_id": NEW_CANDIDATE_ID,
            "pipeline_status": out.get("pipeline_status"),
            "blocker": out.get("blocker", ""),
            "classification_state": out.get("classification_state", ""),
            "temporal_provenance_status": out.get("temporal_provenance_status", ""),
        },
        "reconciled_counts_if_gate_is_evaluated": {
            "selected_filings": reconciled_selected,
            "classifier_ready_filings": reconciled_ready,
            "classifier_ready_rate": ready_rate,
            "classifier_ready_rate_ge_0_90": ready_rate >= 0.90,
            "existing_blocked_rows": len(existing_blocked),
        },
        "R2_price_or_return_access_authorized": False,
        "R2_authorization_changed_by_this_repair": False,
        "price_or_return_data_consumed": False,
        "prospective_gate_changed": False,
        "fold3_accessed": False,
        "fold4_accessed": False,
        "setup_or_live_accessed": False,
        "original_gate_receipt_remains_immutable": True,
        "repair_results_file": str(OUT_CSV),
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    OUT_RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
