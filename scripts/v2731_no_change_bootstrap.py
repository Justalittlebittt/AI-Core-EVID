from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ISSUER=Path("evidence/V2.7.27_SECURITY_ISSUER_PIT_MAP.csv")
ISSUER_SHA="769960860eaeb97f34780eca3b8cdb2618a4e3afd580e97f59fe6435da8b25a8"
LOCATOR=Path("evidence/V2.7.29_PRIMARY_LOCATOR_INVENTORY.csv")
LOCATOR_SHA="6f497c81f99344596ba19e7ef62c54a23d373c07f80877d79af6f70f19f4a4f4"
PROOF=Path("evidence/V2.7.31_NO_CHANGE_INTERVAL_PROOF.json")
MIGRATION=Path("evidence/V2.7.31_FORWARD_EPOCH_CONTRACT_MIGRATION.json")
T0=Path("evidence/V2.7.31_FORWARD_EPOCH_T0.json")
EXPECTED_COUNT=5221
EXPECTED_SSE=2320
EXPECTED_SZSE=2901
EXPECTED_SET_HASH="b9733a28f99a8c91902fb5ba7fb2fbcce5f2b4845612a1bc225a888bcc2cfa6c"
OUT=Path("v2731_no_change_bootstrap")
OUT.mkdir(exist_ok=True)

def sha(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()

def read_csv_exact(path:Path, expected_sha:str):
    b=path.read_bytes()
    actual=sha(b)
    if actual!=expected_sha:
        raise RuntimeError(f"{path}: SHA mismatch {actual} != {expected_sha}")
    return list(csv.DictReader(b.decode("utf-8").splitlines()))

def write_csv(path:Path, rows:list[dict], fields:list[str]):
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k:r.get(k,"") for k in fields})

def main():
    issuer_rows=read_csv_exact(ISSUER,ISSUER_SHA)
    locator_rows=read_csv_exact(LOCATOR,LOCATOR_SHA)
    proof=json.loads(PROOF.read_text(encoding="utf-8"))
    migration=json.loads(MIGRATION.read_text(encoding="utf-8"))
    t0=json.loads(T0.read_text(encoding="utf-8"))

    issuer={r["canonical_security_id"]:r for r in issuer_rows}
    locator={r["canonical_security_id"]:r for r in locator_rows}
    ids=sorted(issuer)
    if set(issuer)!=set(locator):
        raise RuntimeError("issuer and locator identity sets differ")
    if len(ids)!=EXPECTED_COUNT:
        raise RuntimeError(f"count {len(ids)} != {EXPECTED_COUNT}")
    sse=sum(1 for x in ids if x.startswith("SSE:"))
    szse=sum(1 for x in ids if x.startswith("SZSE:"))
    if (sse,szse)!=(EXPECTED_SSE,EXPECTED_SZSE):
        raise RuntimeError(f"exchange counts {(sse,szse)} != {(EXPECTED_SSE,EXPECTED_SZSE)}")
    set_hash=sha(("\n".join(ids)+"\n").encode())
    if set_hash!=EXPECTED_SET_HASH:
        raise RuntimeError(f"set hash {set_hash} != {EXPECTED_SET_HASH}")

    source=proof["source_snapshot"]
    if source["canonical_count"]!=EXPECTED_COUNT or source["canonical_sorted_newline_sha256"]!=EXPECTED_SET_HASH:
        raise RuntimeError("no-change proof source snapshot does not bind expected set")
    if proof["gate_status"]!="PASS_NONTRADING_INTERVAL_CARRY_FOR_RESEARCH_BOOTSTRAP":
        raise RuntimeError("no-change proof not PASS")
    accepted=set(migration["new_membership_provenance_rule"]["accepted_states"])
    required={"FORWARD_OBSERVED_AFTER_T0_EXACT_MATCH","FORWARD_CARRIED_OVER_NONTRADING_INTERVAL"}
    if not required.issubset(accepted):
        raise RuntimeError("migration does not authorize required provenance states")
    if t0["marker_commit_sha"]!="0226b94172632b1e68bb002b454f5e37b3497606":
        raise RuntimeError("T0 marker mismatch")

    certified=[]
    for cid in ids:
        ir=issuer[cid]
        lr=locator[cid]
        if not lr.get("announcement_id") or not lr.get("adjunct_url"):
            raise RuntimeError(f"{cid}: incomplete terminal locator")
        if cid.startswith("SSE:"):
            membership_provenance="FORWARD_OBSERVED_AFTER_T0_EXACT_MATCH"
            membership_evidence="V2.7.31 SSE forward crosscheck + V2.7.31 no-change proof"
        else:
            membership_provenance="FORWARD_CARRIED_OVER_NONTRADING_INTERVAL"
            membership_evidence="V2.7.26 after-close official snapshot + V2.7.31 no-change proof"
        certified.append({
          "epoch_id":"AI_CORE_EVID_FORWARD_EPOCH_001",
          "epoch_t0_utc":"2026-09-20T07:17:16Z",
          "canonical_security_id":cid,
          "exchange":ir["exchange"],
          "security_code":ir["security_code"],
          "official_issuer_query_key":ir["official_issuer_query_key"],
          "official_issuer_query_key_type":ir["official_issuer_query_key_type"],
          "issuer_legal_name":ir["issuer_legal_name"],
          "security_short_name":ir["security_short_name"],
          "official_list_date":ir["official_list_date"],
          "official_board_code":ir["official_board_code"],
          "membership_provenance":membership_provenance,
          "membership_evidence":membership_evidence,
          "issuer_provenance":"BASELINE_ADOPTED_AT_T0",
          "issuer_original_pit_date":ir["pit_date"],
          "locator_provenance":"BASELINE_ADOPTED_AT_T0",
          "locator_original_first_observed_at_utc":"2026-09-20T06:36:51.251465+00:00",
          "resolution":lr.get("resolution",""),
          "document_type":lr.get("document_type",""),
          "title":lr.get("title",""),
          "disclosure_date":lr.get("disclosure_date",""),
          "period_end":lr.get("period_end",""),
          "revision":lr.get("revision",""),
          "announcement_id":lr.get("announcement_id",""),
          "adjunct_url":lr.get("adjunct_url",""),
          "org_id":lr.get("org_id",""),
          "locator_source":lr.get("source",""),
          "pdf_materialization_status":"ON_DEMAND_V2.7.30",
          "certification_scope":"RESEARCH_EPISODE_BOOTSTRAP_PRE_NEXT_SESSION",
          "live_execution_eligible":"false",
          "membership_refresh_required_before":"2026-09-21T09:15:00+08:00",
          "universe_entry_status":"CERTIFIED"
        })

    outcsv=OUT/"V2.7.31_FORWARD_CERTIFIED_UNIVERSE.csv"
    write_csv(outcsv,certified,list(certified[0].keys()))

    receipt={
      "schema":"AI_CORE_EVID_V2_7_31_FORWARD_CERTIFIED_UNIVERSE_OFFLINE_BOOTSTRAP_V1",
      "epoch_id":"AI_CORE_EVID_FORWARD_EPOCH_001",
      "epoch_t0_utc":"2026-09-20T07:17:16Z",
      "mode":"OFFLINE_NO_CHANGE_INTERVAL_BOOTSTRAP",
      "external_network_calls":0,
      "source_artifacts":{
        "issuer_map_sha256":ISSUER_SHA,
        "primary_locator_inventory_sha256":LOCATOR_SHA,
        "official_after_close_set_sha256":EXPECTED_SET_HASH,
        "no_change_interval_proof":"evidence/V2.7.31_NO_CHANGE_INTERVAL_PROOF.json",
        "contract_migration":"evidence/V2.7.31_FORWARD_EPOCH_CONTRACT_MIGRATION.json"
      },
      "universe":{
        "count":len(ids),
        "sse_count":sse,
        "szse_count":szse,
        "canonical_sorted_newline_sha256":set_hash,
        "csv_sha256":sha(outcsv.read_bytes()),
        "sse_membership_provenance":"FORWARD_OBSERVED_AFTER_T0_EXACT_MATCH",
        "szse_membership_provenance":"FORWARD_CARRIED_OVER_NONTRADING_INTERVAL"
      },
      "temporal_scope":{
        "research_episode_bootstrap_allowed":True,
        "first60_research_start_allowed":True,
        "live_execution_allowed":False,
        "membership_refresh_required_before":"2026-09-21T09:15:00+08:00",
        "pre_t0_decisions_authorized":False,
        "historical_2026_09_17_prospective_relabeling":"FORBIDDEN"
      },
      "downstream":{
        "certified_v2_universe":"PASS_RESEARCH_BOOTSTRAP",
        "first60":"READY_FOR_DETERMINISTIC_EPISODE_START",
        "s4_s5_s6":"BLOCKED_PENDING_FIRST60_AND_LATER_GATES",
        "live":"BLOCKED_REFRESH_REQUIRED"
      },
      "gate":{
        "status":"FORWARD_CERTIFIED_UNIVERSE_PASS_WITH_NONTRADING_CARRY",
        "identity_exact":True,
        "issuer_exact":True,
        "terminal_locator_exact":True,
        "network_independent":True
      }
    }
    canon=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    receipt["receipt_sha256"]=sha(canon)
    (OUT/"V2.7.31_FORWARD_CERTIFIED_UNIVERSE_RECEIPT.json").write_text(
      json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
