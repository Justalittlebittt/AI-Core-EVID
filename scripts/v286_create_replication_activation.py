from __future__ import annotations
import json
from pathlib import Path

SOURCE=Path("evidence/V2.8.6_FOLD1_SOURCE_SNAPSHOT_RECEIPT.json")
MANIFEST=Path("evidence/V2.8.6_FOLD1_MANIFEST_RECEIPT.json")
OUT=Path("evidence/V2.8.6_MECHANISM_REPLICATION_ACTIVATION.json")
VALIDATION_COMMIT="5358c888408b2ebd64d3f8db3068f4a9d5690552"

def main():
    s=json.loads(SOURCE.read_text(encoding="utf-8"))
    m=json.loads(MANIFEST.read_text(encoding="utf-8"))
    if s.get("status")!="PASS" or int(s.get("sample_count",0))!=1058:
        raise RuntimeError("SOURCE_NOT_PASS")
    if m.get("status")!="PASS" or int(m.get("target_fold",-1))!=1:
        raise RuntimeError("MANIFEST_NOT_PASS")
    if s.get("sample_manifest_sha256")!=m.get("manifest_sha256"):
        raise RuntimeError("SOURCE_MANIFEST_BINDING_MISMATCH")
    obj={
      "schema":"AI_CORE_EVID_V2_8_6_MECHANISM_REPLICATION_ACTIVATION_V1",
      "version":"V2.8.6",
      "status":"ACTIVE_ONE_TIME_V2_8_6_MECHANISM_REPLICATION",
      "source_snapshot_receipt":"evidence/V2.8.6_FOLD1_SOURCE_SNAPSHOT_RECEIPT.json",
      "source_snapshot_receipt_sha256":s["receipt_sha256"],
      "fold1_manifest":"evidence/V2.8.6_FOLD1_MECHANISM_REPLICATION_MANIFEST.csv",
      "fold1_manifest_sha256":m["manifest_sha256"],
      "evaluator_validation_receipt":"evidence/V2.8.6_LOCKED_MECHANISM_REPLICATION_VALIDATION_RECEIPT.json",
      "evaluator_validation_commit_sha":VALIDATION_COMMIT,
      "fold2_3_4_consumed":False,
      "setup_or_episode_emission_authorized":False,
      "first60_append_authorized":False,
      "live_authorized":False
    }
    OUT.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(obj,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
