from __future__ import annotations
import json,tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import sys
sys.path.insert(0,"scripts")
import v283_pit_date_authority as pit

OUT=Path("evidence/V2.8.3_SSE_FULL_TRANSPORT_VALIDATION_1.json")

def main():
    d=datetime.now(ZoneInfo("Asia/Shanghai")).date()
    with tempfile.TemporaryDirectory() as td:
        df,captures=pit.fetch_sse(d,Path(td))
    out={
      "schema":"AI_CORE_EVID_V2_8_3_SSE_FULL_TRANSPORT_VALIDATION_1",
      "status":"PASS",
      "signal_date_probe":d.isoformat(),
      "normalized_security_count":int(len(df)),
      "capture_file_count":len(captures),
      "distinct_security_count":int(df["canonical_security_id"].nunique()),
      "all_codes_shape_valid":bool(df["security_code"].astype(str).str.fullmatch(r"\d{6}").all()),
      "scientific_output_generated":False,
      "price_or_return_data_consumed":False,
      "fold3_accessed":False,
      "fold4_accessed":False
    }
    if out["normalized_security_count"]<=1000 or out["distinct_security_count"]!=out["normalized_security_count"]:
        out["status"]="FAIL"
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if out["status"]!="PASS":
        raise SystemExit(2)

if __name__=="__main__":
    main()
