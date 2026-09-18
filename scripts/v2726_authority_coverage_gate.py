from __future__ import annotations
import copy, hashlib, json
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
SPEC=ROOT/"evidence/V2.7.26_AUTHORITY_COVERAGE_SEPARATION.json"
MIS=ROOT/"evidence/V2.7.25_MISMATCH_RESOLUTION.json"
PIT=ROOT/"evidence/V2.7.25_PIT_DELTA_PROOF.json"
OUT=Path("v2726_artifacts"); OUT.mkdir(exist_ok=True)

EXPECTED={
  "pit_date":"2026-09-17",
  "official_count":5221,
  "official_hash":"b9733a28f99a8c91902fb5ba7fb2fbcce5f2b4845612a1bc225a888bcc2cfa6c",
  "alpha_count":5219,
  "alpha_hash":"6b12b575881563a437d5d0201ff1261870691518a927d3f3ed8efe2edd21e4cb",
  "alpha_revision":"cd74b1ec67a5cfa2dfaa0d286cba8dbd104024f0",
  "alpha_raw_sha256":"e81837329b28f627f6ded02a9728a4cd059860782ead92562aea8b2a48d2e3c2",
  "missing":["SSE:601091","SSE:688837"],
  "official_source_run_id":35317123694,
  "pit_proof_run_id":35318215853,
}

def load(p:Path)->dict[str,Any]:
    return json.loads(p.read_text(encoding="utf-8"))

def evaluate(spec:dict[str,Any],mis:dict[str,Any],pit:dict[str,Any])->dict[str,Any]:
    errors=[]
    om=spec.get("frozen_official_membership",{})
    ac=spec.get("alphadojo_coverage",{})
    sc=spec.get("source_concordance",{})
    preserved=spec.get("preserved_rules",{})

    # Official membership is an exchange-authority proposition.
    membership_checks={
      "pit_date": spec.get("pit_date")==EXPECTED["pit_date"]==mis.get("pit_date")==pit.get("pit_date"),
      "official_count": om.get("count")==EXPECTED["official_count"]==mis.get("reconciliation",{}).get("official_count"),
      "official_hash": om.get("canonical_sorted_newline_sha256")==EXPECTED["official_hash"],
      "official_source_run": om.get("source_run_id")==EXPECTED["official_source_run_id"],
      "pit_proof_run": om.get("pit_delta_proof_run_id")==EXPECTED["pit_proof_run_id"],
      "pit_delta_zero": pit.get("delta",{}).get("removal_event_count")==0,
      "pit_delta_status": pit.get("delta",{}).get("status")=="PASS_NO_REMOVALS_IN_DELTA",
      "pit_reconstruction": pit.get("pit_reconstruction",{}).get("result")=="CURRENT_OFFICIAL_FILTERED_BY_LIST_DATE_IS_VALID_2026-09-17_PIT_SET",
      "no_vendor_override": om.get("membership_gate_status")=="EXACT_PASS",
    }
    membership_ok=all(membership_checks.values())

    # Vendor coverage is separate and exact at execution scope.
    coverage_checks={
      "revision":ac.get("repo_revision")==EXPECTED["alpha_revision"],
      "raw_hash":ac.get("raw_sha256")==EXPECTED["alpha_raw_sha256"],
      "usable_count":ac.get("usable_pit_count")==EXPECTED["alpha_count"],
      "usable_hash":ac.get("canonical_sorted_newline_sha256")==EXPECTED["alpha_hash"],
      "missing_exact":sorted(ac.get("missing_official_members",[]))==EXPECTED["missing"],
      "extra_empty":ac.get("extra_nonofficial_members",[])==[],
      "gap_status":ac.get("coverage_gate_status")=="GAP_PRESENT",
    }
    coverage_integrity_ok=all(coverage_checks.values())
    full_coverage=coverage_integrity_ok and len(ac.get("missing_official_members",[]))==0

    # Concordance must remain blocked while the sets differ.
    concordance_checks={
      "official_minus":sc.get("official_minus_alphadojo_count")==2==mis.get("reconciliation",{}).get("official_minus_alphadojo_count"),
      "alpha_minus":sc.get("alphadojo_minus_official_count")==0==mis.get("reconciliation",{}).get("alphadojo_minus_official_count"),
      "symdiff":sc.get("symmetric_diff_count")==2==mis.get("reconciliation",{}).get("symmetric_diff_count"),
      "not_equal":sc.get("exact_equal") is False,
      "blocked":sc.get("status")=="MISMATCH_BLOCKED",
    }
    concordance_ok=all(concordance_checks.values())

    safety_checks={
      "no_mutate_alpha":preserved.get("mutate_alphadojo_raw") is False,
      "no_infer_date":preserved.get("infer_missing_listing_date") is False,
      "no_manual_override":preserved.get("manual_membership_override") is False,
      "no_accept_as_equal":preserved.get("accept_mismatch_as_equal") is False,
      "no_drop_official":preserved.get("drop_official_only_security") is False,
      "no_threshold_pass":preserved.get("coverage_threshold_pass") is False,
      "no_ticker_exchange_inference":preserved.get("ticker_prefix_exchange_inference") is False,
    }
    safety_ok=all(safety_checks.values())

    if not membership_ok: errors.append("OFFICIAL_MEMBERSHIP_EVIDENCE_INVALID")
    if not coverage_integrity_ok: errors.append("ALPHADOJO_COVERAGE_EVIDENCE_INVALID")
    if not concordance_ok: errors.append("SOURCE_CONCORDANCE_EVIDENCE_INVALID")
    if not safety_ok: errors.append("SAFETY_CONTRACT_INVALID")

    return {
      "membership_checks":membership_checks,
      "coverage_checks":coverage_checks,
      "concordance_checks":concordance_checks,
      "safety_checks":safety_checks,
      "REAL_MOTHER_POOL_MEMBERSHIP":"EXACT_PASS" if membership_ok and safety_ok else "BLOCKED",
      "ALPHADOJO_COVERAGE":"FULL_EXACT_PASS" if full_coverage else ("GAP_PRESENT_2" if coverage_integrity_ok else "BLOCKED"),
      "SOURCE_CONCORDANCE":"MISMATCH_BLOCKED" if concordance_ok else "BLOCKED_INVALID_EVIDENCE",
      "FIRST60_SELECTION":"READY_TO_RUN" if membership_ok and safety_ok else "BLOCKED",
      "FIRST60_DATA_EXECUTION":"PENDING_SCOPE_COVERAGE_CHECK" if membership_ok and coverage_integrity_ok and safety_ok else "BLOCKED",
      "errors":errors,
    }

def attack_tests(spec,mis,pit):
    tests=[]
    def t(name,mutator,expect):
        s,m,p=copy.deepcopy(spec),copy.deepcopy(mis),copy.deepcopy(pit)
        mutator(s,m,p)
        r=evaluate(s,m,p)
        ok=expect(r)
        tests.append({"name":name,"pass":bool(ok),"result":r})
    t("A01_PIT_PROOF_REMOVAL_INJECTED",
      lambda s,m,p:p["delta"].update({"removal_event_count":1}),
      lambda r:r["REAL_MOTHER_POOL_MEMBERSHIP"]=="BLOCKED")
    t("A02_OFFICIAL_COUNT_TAMPER",
      lambda s,m,p:s["frozen_official_membership"].update({"count":5219}),
      lambda r:r["REAL_MOTHER_POOL_MEMBERSHIP"]=="BLOCKED")
    t("A03_OFFICIAL_HASH_TAMPER",
      lambda s,m,p:s["frozen_official_membership"].update({"canonical_sorted_newline_sha256":"0"*64}),
      lambda r:r["REAL_MOTHER_POOL_MEMBERSHIP"]=="BLOCKED")
    t("A04_SOURCE_RUN_TAMPER",
      lambda s,m,p:s["frozen_official_membership"].update({"source_run_id":0}),
      lambda r:r["REAL_MOTHER_POOL_MEMBERSHIP"]=="BLOCKED")
    t("A05_VENDOR_GAP_DOES_NOT_DELETE_OFFICIAL_MEMBERSHIP",
      lambda s,m,p:None,
      lambda r:r["REAL_MOTHER_POOL_MEMBERSHIP"]=="EXACT_PASS" and r["ALPHADOJO_COVERAGE"]=="GAP_PRESENT_2")
    t("A06_CONCORDANCE_CANNOT_FAKE_EQUAL",
      lambda s,m,p:s["source_concordance"].update({"exact_equal":True,"status":"EXACT_PASS"}),
      lambda r:r["SOURCE_CONCORDANCE"]=="BLOCKED_INVALID_EVIDENCE")
    t("A07_MANUAL_OVERRIDE_FORBIDDEN",
      lambda s,m,p:s["preserved_rules"].update({"manual_membership_override":True}),
      lambda r:r["REAL_MOTHER_POOL_MEMBERSHIP"]=="BLOCKED")
    t("A08_DROP_OFFICIAL_ONLY_FORBIDDEN",
      lambda s,m,p:s["preserved_rules"].update({"drop_official_only_security":True}),
      lambda r:r["REAL_MOTHER_POOL_MEMBERSHIP"]=="BLOCKED")
    t("A09_ALPHA_RAW_HASH_TAMPER_ONLY_BLOCKS_COVERAGE_NOT_OFFICIAL_AUTHORITY",
      lambda s,m,p:s["alphadojo_coverage"].update({"raw_sha256":"f"*64}),
      lambda r:r["REAL_MOTHER_POOL_MEMBERSHIP"]=="EXACT_PASS" and r["ALPHADOJO_COVERAGE"]=="BLOCKED" and r["FIRST60_DATA_EXECUTION"]=="BLOCKED")
    t("A10_COVERAGE_THRESHOLD_CANNOT_AUTHORIZE_GAP",
      lambda s,m,p:s["preserved_rules"].update({"coverage_threshold_pass":True}),
      lambda r:r["REAL_MOTHER_POOL_MEMBERSHIP"]=="BLOCKED")
    t("A11_INFER_MISSING_LIST_DATE_FORBIDDEN",
      lambda s,m,p:s["preserved_rules"].update({"infer_missing_listing_date":True}),
      lambda r:r["REAL_MOTHER_POOL_MEMBERSHIP"]=="BLOCKED")
    t("A12_PIT_STATUS_TAMPER",
      lambda s,m,p:p["delta"].update({"status":"PASS_NO_REMOVALS_IN_DELTA_TAMPERED"}),
      lambda r:r["REAL_MOTHER_POOL_MEMBERSHIP"]=="BLOCKED")
    return tests

def main():
    spec,mis,pit=load(SPEC),load(MIS),load(PIT)
    baseline=evaluate(spec,mis,pit)
    tests=attack_tests(spec,mis,pit)
    passed=sum(1 for x in tests if x["pass"])
    receipt={
      "schema":"AI_CORE_EVID_V2_7_26_AUTHORITY_COVERAGE_RECEIPT_V1",
      "version":"V2.7.26",
      "baseline":baseline,
      "attack_tests":{"passed":passed,"total":len(tests),"all_pass":passed==len(tests),
                      "results":[{"name":x["name"],"pass":x["pass"]} for x in tests]},
    }
    authorized=(
      baseline["REAL_MOTHER_POOL_MEMBERSHIP"]=="EXACT_PASS"
      and baseline["FIRST60_SELECTION"]=="READY_TO_RUN"
      and passed==len(tests)
    )
    receipt["authorization"]={
      "REAL_MOTHER_POOL_MEMBERSHIP": authorized,
      "FIRST60_SELECTION": authorized,
      "FIRST60_DATA_EXECUTION": False,
      "note":"Data execution remains pending exact scope coverage check; no vendor gap is waived."
    }
    canonical=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    receipt["receipt_sha256"]=hashlib.sha256(canonical).hexdigest()
    (OUT/"V2.7.26_AUTHORITY_COVERAGE_RECEIPT.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
    if not authorized:
        raise SystemExit(2)

if __name__=="__main__":
    main()
