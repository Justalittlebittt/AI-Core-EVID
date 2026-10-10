from __future__ import annotations
import argparse, csv, hashlib, json
from pathlib import Path
import v291_negative_space_batch1 as base

CHUNK_COUNT=8
OUT_RESULTS=Path("evidence/V2.9.3_RECONSTRUCTED_BATCH3_RESULTS_1.csv")
OUT_SUPP_POS=Path("evidence/V2.9.3_RECONSTRUCTED_BATCH3_POSITIVE_EVENTS_1.csv")
OUT_UNION_POS=Path("evidence/V2.9.3_HYBRID_DISCOVERY_UNION_POSITIVE_EVENTS_AFTER_RECONSTRUCTED_BATCH3_1.csv")
OUT_RECEIPT=Path("evidence/V2.9.3_RECONSTRUCTED_BATCH3_RECEIPT_1.json")
B1_RECEIPT=Path("evidence/V2.9.1_NEGATIVE_SPACE_BATCH1_RECEIPT_1.json")
B1_POS=Path("evidence/V2.9.1_NEGATIVE_SPACE_BATCH1_POSITIVE_EVENTS_1.csv")
POSITIVE=base.POSITIVE

def read_csv(p:Path):
    return list(csv.DictReader(p.read_text(encoding="utf-8").splitlines()))

def write_csv_union(path:Path, rows:list[dict]):
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields: fields.append(k)
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore",lineterminator="\n")
        w.writeheader(); w.writerows(rows)

def chunk_paths(i:int):
    p=f"{i:02d}"
    if i==3:
        return (
          Path(f"evidence/V2.9.3_BATCH3_RECONSTRUCTION_CHUNK_{p}_RESULTS_1.csv"),
          Path(f"evidence/V2.9.3_BATCH3_RECONSTRUCTION_CHUNK_{p}_RECEIPT_1.json")
        )
    return (
      Path(f"evidence/V2.9.2_HYBRID_DISCOVERY_BATCH3_CHUNK_{p}_RESULTS_1.csv"),
      Path(f"evidence/V2.9.2_HYBRID_DISCOVERY_BATCH3_CHUNK_{p}_RECEIPT_1.json")
    )

def effective_date(r):
    return str(r.get("retrospective_causal_effective_date") or r.get("retrospective_effective_date") or r.get("effective_date") or "").strip()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--parent-positive-events",required=True)
    ap.add_argument("--parent-final-receipt",required=True)
    a=ap.parse_args()

    contract=base.read_json(Path("evidence/V2.9.3_BATCH3_MINIMAL_RECONSTRUCTION_CONTRACT_1.json"))
    if contract.get("schema")!="AI_CORE_EVID_V2_9_3_BATCH3_MINIMAL_RECONSTRUCTION_CONTRACT_1" or contract.get("status")!="FROZEN_BEFORE_IMPLEMENTATION":
        raise RuntimeError("V293_CONTRACT_BLOCK")
    parent_receipt=base.read_json(Path(a.parent_final_receipt))
    if parent_receipt.get("status")!="V2_9_HISTORICAL_E_SOURCE_EXPANSION_TOO_SPARSE":
        raise RuntimeError("PARENT_V29_TERMINAL_STATUS_BLOCK")
    b1=base.read_json(B1_RECEIPT)
    if b1.get("status")!="V2_9_1_DISCOVERY_SELECTION_BIAS_CONFIRMED":
        raise RuntimeError("V291_BATCH1_REUSE_BLOCK")

    owner,_=base.old.load_development_universe()
    order=sorted(owner,key=lambda x:(hashlib.sha256(x.encode()).hexdigest(),x))
    batch=order[128:192]
    if len(batch)!=64: raise RuntimeError("BATCH3_MEMBERSHIP_BLOCK")

    results=[]; transport=[]; prov=[]; seen_ids=[]; seen_ranks=[]
    for i in range(1,9):
        rp,cp=chunk_paths(i)
        if not rp.exists() or not cp.exists(): raise RuntimeError(f"CHUNK_EVIDENCE_MISSING:{i}")
        rec=base.read_json(cp)
        exp_ids=batch[(i-1)*8:i*8]
        exp_ranks=list(range(129+(i-1)*8,129+i*8))
        if i==3:
            if rec.get("schema")!="AI_CORE_EVID_V2_9_3_BATCH3_RECONSTRUCTION_CHUNK_RECEIPT_1":
                raise RuntimeError("CHUNK3_RECON_SCHEMA_BLOCK")
            if rec.get("status")!="V2_9_3_BATCH3_RECONSTRUCTION_CHUNK_COMPLETE" or rec.get("execution_integrity_pass") is not True:
                raise RuntimeError("CHUNK3_RECON_NOT_COMPLETE")
            if rec.get("scientific_batch_index")!=3:
                raise RuntimeError("CHUNK3_RECON_BATCH_INDEX_BLOCK")
        else:
            if rec.get("schema")!="AI_CORE_EVID_V2_9_2_HYBRID_DISCOVERY_BATCH3_EXECUTION_CHUNK_RECEIPT_1":
                raise RuntimeError(f"CHUNK_SCHEMA_BLOCK:{i}")
            if rec.get("status")!="V2_9_2_BATCH3_EXECUTION_CHUNK_COMPLETE" or rec.get("execution_integrity_pass") is not True:
                raise RuntimeError(f"CHUNK_NOT_COMPLETE:{i}")
        if rec.get("batch_ranks")!=exp_ranks or rec.get("security_ids")!=exp_ids:
            raise RuntimeError(f"CHUNK_MEMBERSHIP_BLOCK:{i}")
        if base.sha_file(rp)!=rec.get("results_sha256"):
            raise RuntimeError(f"CHUNK_HASH_BLOCK:{i}")
        if any(rec.get(k) is not False for k in ("price_or_return_data_consumed","candidate_outcome_research_executed","fold3_accessed","fold4_accessed")):
            raise RuntimeError(f"CHUNK_PROHIBITED_DATA_BLOCK:{i}")
        rr=read_csv(rp); results.extend(rr); transport.extend(rec.get("transport_evidence") or [])
        seen_ids.extend(exp_ids); seen_ranks.extend(exp_ranks)
        prov.append({"chunk_index":i,"receipt_sha256":rec.get("receipt_sha256"),"results_sha256":rec.get("results_sha256"),"result_count":len(rr)})

    base.write_csv(OUT_RESULTS,results)
    supp=[r for r in results if r.get("pipeline_status")=="SUCCESS" and r.get("classification_state")==POSITIVE]
    base.write_csv(OUT_SUPP_POS,supp)

    parent_pos=read_csv(Path(a.parent_positive_events))
    b1_pos=read_csv(B1_POS)
    b2_pos=read_csv(Path("evidence/V2.9.2_HYBRID_DISCOVERY_BATCH2_POSITIVE_EVENTS_1.csv"))
    b2_receipt=base.read_json(Path("evidence/V2.9.2_HYBRID_DISCOVERY_BATCH2_RECEIPT_1.json"))
    if b2_receipt.get("status")!="V2_9_2_HYBRID_DISCOVERY_BATCH2_COMPLETE_TOO_SPARSE" or b2_receipt.get("next_batch_authorized") is not True:
        raise RuntimeError("BATCH3_NOT_AUTHORIZED_BY_BATCH2_RECEIPT")
    union={}
    for source,rows in (("V2.9_BASE",parent_pos),("V2.9.1_SUPPLEMENT_BATCH1",b1_pos),("V2.9.2_SUPPLEMENT_BATCH2",b2_pos),("V2.9.3_RECONSTRUCTED_SUPPLEMENT_BATCH3",supp)):
        for r in rows:
            aid=str(r.get("announcement_id") or "").strip()
            if not aid: raise RuntimeError(f"MISSING_ANNOUNCEMENT_ID:{source}")
            if aid in union:
                raise RuntimeError(f"UNEXPECTED_CROSS_LAYER_DUPLICATE:{aid}")
            x=dict(r); x["v293_discovery_layer"]=source; union[aid]=x
    u=list(union.values())
    write_csv_union(OUT_UNION_POS,u)

    secs={}; dates=set(); months=set()
    for r in u:
        cid=str(r.get("canonical_security_id") or "").strip()
        if not cid: raise RuntimeError("UNION_SECURITY_ID_BLOCK")
        secs[cid]=secs.get(cid,0)+1
        d=effective_date(r)
        if not d: raise RuntimeError(f"UNION_EFFECTIVE_DATE_BLOCK:{r.get('announcement_id')}")
        dates.add(d); months.add(d[:7])
    max_count=max(secs.values()) if secs else 0
    max_share=(max_count/len(u)) if u else 1.0
    floor={
      "eligible_events":{"value":len(u),"threshold":20,"pass":len(u)>=20},
      "distinct_securities":{"value":len(secs),"threshold":12,"pass":len(secs)>=12},
      "distinct_effective_dates":{"value":len(dates),"threshold":12,"pass":len(dates)>=12},
      "distinct_calendar_months":{"value":len(months),"threshold":6,"pass":len(months)>=6},
      "max_single_security_share":{"value":max_share,"threshold":0.20,"pass":max_share<=0.20}
    }
    ready=sum(r.get("pipeline_status")=="SUCCESS" for r in results)
    mat=ready/len(results) if results else 1.0
    technical={
      "batch3_membership_exact_64":seen_ids==batch and seen_ranks==list(range(129,193)),
      "all_64_issuers_transport_complete":len(transport)==64 and all(x.get("status")=="PASS" for x in transport),
      "pagination_closed":all(x.get("official_total")==x.get("deduped_count") for x in transport),
      "all_supplement_candidates_parent_absent":all(str(r.get("parent_candidate_absent")).lower() in {"true","1"} for r in results),
      "classifier_ready_materialization_rate_ge_0_90":mat>=0.90,
      "all_positive_temporal_provenance_pass":all(r.get("temporal_provenance_status")=="PASS" for r in supp),
      "all_8_execution_chunks_complete":len(prov)==8
    }
    if not all(technical.values()):
        status="V2_9_3_BATCH3_RECONSTRUCTION_TECHNICALLY_BLOCKED"
    elif all(x["pass"] for x in floor.values()):
        status="V2_9_3_HYBRID_DISCOVERY_READY"
    else:
        status="V2_9_3_BATCH3_COMPLETE_TOO_SPARSE"

    out={
      "schema":"AI_CORE_EVID_V2_9_3_RECONSTRUCTED_BATCH3_RECEIPT_1",
      "version":"V2.9.3","status":status,
      "batch_index":3,"batch_ranks":[129,192],"batch_size":64,
      "execution_chunks":prov,
      "summary":{
        "batch3_negative_space_triage_admitted":len(results),
        "batch3_classifier_ready":ready,
        "batch3_materialization_rate":mat,
        "batch3_supplement_positive_count":len(supp),
        "batch2_supplement_positive_count":len(b2_pos),
        "base_positive_count":len(parent_pos),
        "batch1_supplement_positive_count":len(b1_pos),
        "union_unique_positive_events":len(u),
        "union_distinct_securities":len(secs),
        "union_distinct_effective_dates":len(dates),
        "union_distinct_calendar_months":len(months),
        "union_max_single_security_share":max_share
      },
      "information_floor":floor,
      "technical_checks":technical,
      "batch3_results_sha256":base.sha_file(OUT_RESULTS),
      "batch3_positive_events_sha256":base.sha_file(OUT_SUPP_POS),
      "union_positive_events_sha256":base.sha_file(OUT_UNION_POS),
      "price_or_return_data_consumed":False,
      "candidate_outcome_research_executed":False,
      "fold3_accessed":False,"fold4_accessed":False,
      "next_batch_authorized":False
    }
    out["receipt_sha256"]=base.stable_sha(out)
    OUT_RECEIPT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if status=="V2_9_3_BATCH3_RECONSTRUCTION_TECHNICALLY_BLOCKED": raise SystemExit(2)

if __name__=="__main__": main()
