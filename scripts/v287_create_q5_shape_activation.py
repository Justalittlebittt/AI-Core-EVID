from __future__ import annotations
import json
from pathlib import Path
SOURCE=Path("evidence/V2.8.7_FOLD2_SOURCE_SNAPSHOT_RECEIPT.json")
MANIFEST=Path("evidence/V2.8.7_FOLD2_SETUP_SHAPE_MANIFEST_RECEIPT.json")
OUT=Path("evidence/V2.8.7_Q5_SETUP_SHAPE_ACTIVATION.json")
VALIDATION_COMMIT="062efa5a117cb7de94e0737d531fb12b2a894437"
def main():
    s=json.loads(SOURCE.read_text(encoding="utf-8")); m=json.loads(MANIFEST.read_text(encoding="utf-8"))
    if s.get("status")!="PASS" or int(s.get("sample_count",0))!=1048: raise RuntimeError("SOURCE_NOT_PASS")
    if m.get("status")!="PASS" or int(m.get("target_fold",-1))!=2: raise RuntimeError("MANIFEST_NOT_PASS")
    if s.get("sample_manifest_sha256")!=m.get("manifest_sha256"): raise RuntimeError("SOURCE_MANIFEST_BINDING_MISMATCH")
    obj={
      "schema":"AI_CORE_EVID_V2_8_7_Q5_SETUP_SHAPE_ACTIVATION_V1","version":"V2.8.7",
      "status":"ACTIVE_ONE_TIME_V2_8_7_Q5_SETUP_SHAPE_RESEARCH",
      "source_snapshot_receipt":"evidence/V2.8.7_FOLD2_SOURCE_SNAPSHOT_RECEIPT.json",
      "source_snapshot_receipt_sha256":s["receipt_sha256"],
      "fold2_manifest":"evidence/V2.8.7_FOLD2_SETUP_SHAPE_MANIFEST.csv",
      "fold2_manifest_sha256":m["manifest_sha256"],
      "evaluator_validation_receipt":"evidence/V2.8.7_LOCKED_Q5_SETUP_SHAPE_VALIDATION_RECEIPT.json",
      "evaluator_validation_commit_sha":VALIDATION_COMMIT,
      "alternate_threshold_search_authorized":False,"fold3_4_consumed":False,
      "setup_emission_authorized":False,"first60_append_authorized":False,"episode_emission_authorized":False,"live_authorized":False
    }
    OUT.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(obj,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
