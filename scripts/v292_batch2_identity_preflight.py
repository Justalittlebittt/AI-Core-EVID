from __future__ import annotations
import hashlib, json
from pathlib import Path
import v291_negative_space_batch1 as base

OUT=Path("evidence/V2.9.2_BATCH2_IDENTITY_PREFLIGHT_1.json")
CONTRACT=Path("evidence/V2.9.2_HYBRID_DISCOVERY_REDESIGN_CONTRACT_1.json")

def main():
    c=base.read_json(CONTRACT)
    if c.get("schema")!="AI_CORE_EVID_V2_9_2_HYBRID_DISCOVERY_REDESIGN_CONTRACT_1" or c.get("status")!="FROZEN_BEFORE_IMPLEMENTATION":
        raise RuntimeError("V292_CONTRACT_BLOCK")
    owner,_=base.old.load_development_universe()
    order=sorted(owner,key=lambda x:(hashlib.sha256(x.encode()).hexdigest(),x))
    batch=order[64:128]
    if len(batch)!=64:
        raise RuntimeError("BATCH2_MEMBERSHIP_BLOCK")
    rows=base.read_rows(base.MAP)
    ids={r["canonical_security_id"] for r in rows}
    missing=[x for x in batch if x not in ids]
    out={
      "schema":"AI_CORE_EVID_V2_9_2_BATCH2_IDENTITY_PREFLIGHT_1",
      "version":"V2.9.2",
      "status":"PASS" if not missing else "BLOCKED_MISSING_IDENTITY_AUTHORITY",
      "batch_index":2,
      "batch_ranks":[65,128],
      "security_count":len(batch),
      "security_ids":batch,
      "missing_identity_count":len(missing),
      "missing_identity_security_ids":missing,
      "folds_used":sorted(set(owner[x] for x in batch)),
      "price_or_return_data_consumed":False,
      "candidate_outcome_research_executed":False,
      "fold3_accessed":False,
      "fold4_accessed":False
    }
    out["receipt_sha256"]=base.stable_sha(out)
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if missing:
        raise SystemExit(2)

if __name__=="__main__":
    main()
