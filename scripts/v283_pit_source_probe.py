from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from v283_pit_date_authority import fetch_sse, fetch_szse

def stable_json_sha(obj) -> str:
    b=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--asof-date",required=True)
    ap.add_argument("--out",default="v283_pit_probe")
    args=ap.parse_args()
    d=date.fromisoformat(args.asof_date)
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        sse,sc=fetch_sse(d,root/"sse")
        sz,zc=fetch_szse(d,root/"szse")
        allx=pd.concat([sse,sz],ignore_index=True)
        if allx["canonical_security_id"].duplicated().any():
            raise RuntimeError("probe cross-exchange duplicate identity")
        receipt={
          "schema":"AI_CORE_EVID_V2_8_3_PIT_SOURCE_PROBE_V1",
          "asof_date":d.isoformat(),
          "captured_at_utc":datetime.now(timezone.utc).isoformat(),
          "sse_count":int(len(sse)),
          "szse_count":int(len(sz)),
          "total_count":int(len(allx)),
          "sse_capture_responses":len(sc),
          "szse_capture_responses":len(zc),
          "sse_min_list_date":str(sse["official_list_date"].min()),
          "sse_max_list_date":str(sse["official_list_date"].max()),
          "szse_min_list_date":str(sz["official_list_date"].min()),
          "szse_max_list_date":str(sz["official_list_date"].max()),
          "status":"PASS" if len(sse)>1000 and len(sz)>1000 else "BLOCKED_IMPLAUSIBLE_COUNTS",
        }
        receipt["receipt_sha256"]=stable_json_sha(receipt)
        p=out/"V2.8.3_PIT_SOURCE_PROBE_RECEIPT.json"
        p.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(receipt,ensure_ascii=False,indent=2))
        if receipt["status"]!="PASS":
            raise SystemExit(2)

if __name__=="__main__":
    main()
