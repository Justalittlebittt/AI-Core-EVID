"""Read-only isolated 486-title frozen V2.8.4 triage-input equivalence study.

No PDF classification, no price/outcome data, no Batch-3 source adapter.
Compare exchange raw titles, original security-name argument, and explicit
security-prefix + separator stripping. Do not replace frozen semantics.
"""
import hashlib
import json
import re
from pathlib import Path
import v284_candidate_triage as frozen

SOURCE=Path("evidence/V2.9.4_002667_SZSE_RAW_ROWS_RETRIEVAL_V1.json")
OUT=Path("evidence/V2.9.4_002667_FROZEN_TRIAGE_TITLE_INPUT_EQUIVALENCE_1.json")
NAMES={"鞍重股份","威领股份"}
EXPECTED_COUNT=486

def analyze(rows):
    ids=[str(r["ann_id"]) for r in rows]
    if len(rows)!=EXPECTED_COUNT or len(set(ids))!=EXPECTED_COUNT:
        raise ValueError("EXACT_486_UNIQUE_OFFICIAL_ROWS_REQUIRED")
    results=[];collisions=[];states={"raw":{},"with_historic_name":{},"strip_prefix_separator":{}}
    prefix_counts={}
    for r in rows:
        aid=str(r["ann_id"])
        code=r["exchange_stock_codes"]
        title=str(r["title"])
        match=re.fullmatch(r"(鞍重股份|威领股份)：(.+)",title,re.S)
        if code!=["002667"] or not match or not r["publication_day"]:
            raise ValueError("SOURCE_TITLE_IDENTITY_PREFIX_BLOCK:"+aid)
        historic_name=match.group(1)
        suffix=match.group(2)
        prefix_counts[historic_name]=prefix_counts.get(historic_name,0)+1
        variants={
            "raw":frozen.triage_title(title,""),
            "with_historic_name":frozen.triage_title(title,historic_name),
            "strip_prefix_separator":frozen.triage_title(suffix,""),
        }
        for key,output in variants.items():
            st=output["triage_state"]
            states[key][st]=states[key].get(st,0)+1
        classes={x["triage_state"] for x in variants.values()}
        if len(classes)>1:
            collisions.append({"ann_id":aid,"publication_day":r["publication_day"],
                               "original_source_title":title,"historic_short_name":historic_name,
                               "variants":variants})
        results.append({"ann_id":aid,"title_sha256":hashlib.sha256(title.encode()).hexdigest(),
                        "states":{key:x["triage_state"] for key,x in variants.items()}})
    return {"scoped_rows":len(rows),"historical_prefix_counts":prefix_counts,
            "triage_state_counts":states,
            "input_variant_disagreements":collisions,
            "input_variant_disagreement_count":len(collisions),
            "tested_id_sha256":hashlib.sha256(("\n".join(sorted(ids))+"\n").encode()).hexdigest(),
            "per_announcement_states":results,
            "frozen_triage_function_modified":False,
            "official_cninfo_titles_486_verified_equivalent":False,
            "original_batch3_triage_source_migration_authorized":False,
            "scientific_batch3_authorized":False,
            "price_or_return_data_consumed":False,"trading_authorized":False}

def main():
    receipt=json.loads(SOURCE.read_text(encoding="utf-8"))
    if receipt.get("evaluation",{}).get("full_source_row_reference_match") is not True:
        raise RuntimeError("OFFICIAL_SOURCE_ROWS_NOT_RECONCILED")
    rows=receipt["source_rows"]
    out=analyze(rows)
    payload={"schema":"V294_002667_EXCHANGE_TITLE_INPUT_FROZEN_TRIAGE_EQUIVALENCE_V1",
             "source_rows_path":str(SOURCE),"source_rows_git_blob_sha":"26e9d9d4fd28d6cabb32204d3e34caa4a4927235",
             "frozen_triage_module":"scripts/v284_candidate_triage.py",
             "interpretation":"Pure input-semantics sensitivity to exchange short-name prefixes and separator. No CNINFO original title-equivalence inference.",
             "analysis":out}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in out.items() if k not in ("per_announcement_states","input_variant_disagreements")},ensure_ascii=False))
    print(json.dumps(out["input_variant_disagreements"],ensure_ascii=False))
    if not out["per_announcement_states"] or len(out["per_announcement_states"])!=EXPECTED_COUNT:
        raise SystemExit("FROZEN_TRIAGE_SOURCE_ROWS_INCOMPLETE")

if __name__=="__main__":
    main()
