from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

BASE = Path("evidence/retrospective_feasibility")
R1_COHORT = BASE / "V2.8.12R_FROZEN_EVENT_COHORT.csv"
R1_RESULTS = BASE / "V2.8.12R_EXPANSION_RESULTS.csv"
OLD_POS = Path("evidence/V2.8.11_BOUNDED_E_RECONSTRUCTION_RETRY1_POSITIVE_EVENTS.csv")
AMENDMENT = Path("evidence/V2.8.12R_RETROSPECTIVE_FEASIBILITY_CONTRACT_AMENDMENT_3.json")
OUT = BASE / "V2.8.12R_FINAL_PRE_OUTCOME_COHORT.csv"
RECEIPT = BASE / "V2.8.12R_FINAL_PRE_OUTCOME_COHORT_RECEIPT.json"

FIELDS = [
    "cohort_source", "quarter", "announcement_id", "canonical_security_id", "security_name",
    "announcement_title", "disclosure_date", "retrospective_causal_effective_date",
    "classification_state", "matched_ai_role", "matched_commerciality",
    "object_sha256", "page_text_sha256", "decision_sha256", "evidence_sentence_sha256"
]
IMMUTABLE = [
    "announcement_id", "canonical_security_id", "quarter", "disclosure_date",
    "retrospective_causal_effective_date", "classification_state"
]
HASH_FIELDS = ["object_sha256", "page_text_sha256", "decision_sha256", "evidence_sentence_sha256"]


def rows(path: Path) -> list[dict]:
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def provenance_map() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for src in (OLD_POS, R1_RESULTS):
        for r in rows(src):
            if r.get("classification_state") != "ELIGIBLE_AI_CORE" or r.get("pipeline_status") != "SUCCESS":
                continue
            aid = str(r.get("announcement_id") or "").strip()
            if not aid:
                raise RuntimeError("PROVENANCE_EMPTY_ANNOUNCEMENT_ID")
            compact = {k: str(r.get(k) or "").strip() for k in HASH_FIELDS}
            if not all(compact.values()):
                raise RuntimeError(f"PROVENANCE_HASH_INCOMPLETE:{aid}")
            compact.update({
                "announcement_id": aid,
                "canonical_security_id": str(r.get("canonical_security_id") or "").strip(),
                "quarter": str(r.get("quarter") or "").strip(),
                "disclosure_date": str(r.get("path_disclosure_date") or "").strip(),
                "retrospective_causal_effective_date": str(r.get("retrospective_causal_effective_date") or "").strip(),
                "classification_state": str(r.get("classification_state") or "").strip(),
            })
            if aid in out and out[aid] != compact:
                raise RuntimeError(f"PROVENANCE_CONFLICT:{aid}")
            out[aid] = compact
    return out


def canonicalize(write: bool = True) -> dict:
    a = json.loads(AMENDMENT.read_text(encoding="utf-8"))
    if a.get("status") != "ACTIVE_PRE_OUTCOME_PROVENANCE_CANONICALIZATION":
        raise RuntimeError("AMENDMENT3_NOT_ACTIVE")
    cohort = rows(R1_COHORT)
    pmap = provenance_map()
    if len({r["announcement_id"] for r in cohort}) != len(cohort):
        raise RuntimeError("COHORT_DUPLICATE_ANNOUNCEMENT_ID")
    out = []
    legacy = 0
    expansion = 0
    for r in cohort:
        aid = r["announcement_id"]
        if aid not in pmap:
            raise RuntimeError(f"COHORT_PROVENANCE_NOT_FOUND:{aid}")
        p = pmap[aid]
        for k in IMMUTABLE:
            if str(r.get(k) or "").strip() != str(p.get(k) or "").strip():
                raise RuntimeError(f"IMMUTABLE_MISMATCH:{aid}:{k}:{r.get(k)}:{p.get(k)}")
        z = {k: str(r.get(k) or "") for k in FIELDS}
        for k in HASH_FIELDS:
            z[k] = p[k]
        if r.get("cohort_source") == "V2.8.11_RECONSTRUCTED_POSITIVE":
            legacy += 1
        elif r.get("cohort_source") == "V2.8.12R_R1_EXPANSION":
            expansion += 1
        else:
            raise RuntimeError(f"UNKNOWN_COHORT_SOURCE:{aid}:{r.get('cohort_source')}")
        out.append(z)
    out.sort(key=lambda r: (r["retrospective_causal_effective_date"], r["canonical_security_id"], r["announcement_id"]))
    if legacy != 3:
        raise RuntimeError(f"LEGACY_COUNT_NOT_THREE:{legacy}")
    if not all(all(str(r.get(k) or "").strip() for k in HASH_FIELDS) for r in out):
        raise RuntimeError("FINAL_COHORT_HASH_COMPLETENESS_BLOCK")

    if write:
        with OUT.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
            w.writeheader(); w.writerows(out)
        membership = [{k: r[k] for k in IMMUTABLE} for r in out]
        receipt = {
            "schema": "AI_CORE_EVID_V2_8_12R_FINAL_PRE_OUTCOME_COHORT_RECEIPT_V1",
            "version": "V2.8.12R",
            "status": "PASS_FINAL_PRE_OUTCOME_COHORT_FROZEN",
            "authority": str(AMENDMENT),
            "input_R1_cohort": str(R1_COHORT),
            "input_R1_cohort_sha256": sha_file(R1_COHORT),
            "final_cohort": str(OUT),
            "final_cohort_sha256": sha_file(OUT),
            "event_count": len(out),
            "legacy_events_hydrated": legacy,
            "R1_expansion_events": expansion,
            "all_four_provenance_hashes_complete": True,
            "membership_and_event_semantics_changed": False,
            "membership_identity_sha256": stable_sha(membership),
            "price_or_return_data_consumed": False,
            "prospective_gate_changed": False,
            "fold3_accessed": False,
            "fold4_accessed": False,
            "R2_may_use_this_as_final_event_population_only_if_R1_technical_gate_passed": True
        }
        receipt["receipt_sha256"] = stable_sha(receipt)
        RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return receipt
    return {"status": "PASS_DRY_RUN", "event_count": len(out), "legacy": legacy, "expansion": expansion}


if __name__ == "__main__":
    print(json.dumps(canonicalize(write=True), ensure_ascii=False, indent=2))
