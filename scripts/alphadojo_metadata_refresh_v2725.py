from pathlib import Path
import json, hashlib
import pandas as pd
from huggingface_hub import HfApi, hf_hub_download

TARGETS={"601091","688837"}
OUT=Path("alphadojo_refresh_artifacts"); OUT.mkdir(exist_ok=True)
api=HfApi(); info=api.dataset_info("AlphaDojo/dojo_stock_info"); rev=info.sha
p=Path(hf_hub_download("AlphaDojo/dojo_stock_info","data.parquet",repo_type="dataset",revision=rev))
b=p.read_bytes()
df=pd.read_parquet(p)
def code(v):
    s=str(v).strip()
    import re
    ms=re.findall(r"(?<!\d)(\d{6})(?!\d)",s)
    return ms[0] if len(set(ms))==1 else None
df["code6"]=df["ticker"].map(code)
rows=df[df["code6"].isin(TARGETS)].copy()
fields=["ticker","code6","short_name","full_exchange_name","market","quote_type","first_traded_date","is_delisted","delisted_at"]
present=[x for x in fields if x in rows.columns]
records=rows[present].fillna("").to_dict("records")
status={}
for c in sorted(TARGETS):
    rr=[r for r in records if r.get("code6")==c]
    status[c]={
      "row_count":len(rr),
      "first_traded_date_values":sorted({str(r.get("first_traded_date","")).strip() for r in rr}),
      "resolved":any(str(r.get("first_traded_date","")).strip() for r in rr)
    }
out={
 "schema":"AI_CORE_EVID_V2_7_25_ALPHADOJO_METADATA_REFRESH_V1",
 "repo_revision":rev,
 "raw_sha256":hashlib.sha256(b).hexdigest(),
 "raw_bytes":len(b),
 "source_rows":len(df),
 "previous_frozen_revision":"cd74b1ec67a5cfa2dfaa0d286cba8dbd104024f0",
 "targets":status,
 "records":records,
 "all_resolved":all(v["resolved"] for v in status.values())
}
(OUT/"ALPHADOJO_METADATA_REFRESH_V2.7.25.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
print(json.dumps(out,ensure_ascii=False,indent=2))
