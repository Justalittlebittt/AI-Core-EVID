from __future__ import annotations
import hashlib,json
from pathlib import Path

U=Path("evidence/V2.7.31_FORWARD_CERTIFIED_UNIVERSE.csv")
R=Path("evidence/V2.7.31_FORWARD_CERTIFIED_UNIVERSE_RECEIPT.json")
F=Path("evidence/V2.7.31_FINAL_RECORD.json")

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    final=json.loads(F.read_text(encoding="utf-8"))
    receipt=json.loads(R.read_text(encoding="utf-8"))
    u=sha(U); r=sha(R)
    expected_u=final["authoritative_membership"]["certified_universe_csv_sha256"]
    expected_receipt=final["validation"]["receipt_sha256"]
    tests=[
      {"name":"universe_sha_matches_final_record","pass":u==expected_u,"actual":u,"expected":expected_u},
      {"name":"receipt_internal_universe_sha_matches","pass":receipt["universe"]["csv_sha256"]==u,"actual":receipt["universe"]["csv_sha256"],"expected":u},
      {"name":"receipt_seal_matches_final_record","pass":receipt["receipt_sha256"]==expected_receipt,"actual":receipt["receipt_sha256"],"expected":expected_receipt},
      {"name":"universe_count_5221","pass":receipt["universe"]["count"]==5221,"actual":receipt["universe"]["count"],"expected":5221},
    ]
    out={"schema":"AI_CORE_EVID_V2_8_1_V2731_AUTHORITY_INTEGRITY_CHECK_V1","tests":tests}
    out["passed"]=sum(x["pass"] for x in tests); out["total"]=len(tests); out["all_pass"]=out["passed"]==out["total"]
    Path("v281_v2731_authority_check.json").write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out,indent=2))
    if not out["all_pass"]: raise SystemExit(1)
if __name__=="__main__": main()
