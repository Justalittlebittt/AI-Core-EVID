from __future__ import annotations
import hashlib,json,math
from pathlib import Path
import requests
import pandas as pd
from akshare.utils import demjson

URL="https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
START="2022-01-04"; END="2022-03-31"
SYMS=["sh600000","sz000001","sz300750"]
EXPECTED={
 "sh600000":"e6dad2ecb8e4ff4f1fdb4d8501a6ded86fa934d6a40b8d2c253d3b1dcfaa6c49",
 "sz000001":"6cdd0cbc2e22893c21883eecd8d8975a1ee6c2621de7df87eb134c4e86890a35",
 "sz300750":"8e644f390aa254dc90d51ce6beb47537b3ab963af914db2d1dbd9184da86bb83"
}
OUT=Path("v286_direct_probe/V2.8.6_TENCENT_DIRECT_TRANSPORT_PROBE_RECEIPT.json")

def sha(o):
    return hashlib.sha256(json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def fetch(sym):
    params={"_var":"kline_dayhfq_direct","param":f"{sym},day,{START},{END},640,hfq","r":"0.8205512681390605"}
    r=requests.get(URL,params=params,timeout=20); r.raise_for_status()
    data=demjson.decode(r.text[r.text.find("={")+1:])["data"][sym]
    raw=data.get("hfqday") or data.get("day") or data.get("qfqday")
    if raw is None: raise RuntimeError(f"NO_DATA_KEY:{sym}")
    rows=[]
    for z in raw:
        d=str(z[0]); vals={k:float(v) for k,v in zip(("open","close","high","low","volume"),z[1:6])}
        if not sym.startswith(("sh688","sz399","sh000","sz000")): vals["volume"]*=100
        if any(not math.isfinite(v) for v in vals.values()): raise RuntimeError(f"NONFINITE:{sym}:{d}")
        rows.append({"date":d,**vals})
    rows=[x for x in rows if START<=x["date"]<=END]
    rows.sort(key=lambda x:x["date"])
    if len({x["date"] for x in rows})!=len(rows): raise RuntimeError(f"DUP:{sym}")
    return rows

def main():
    q=[]
    for sym in SYMS:
        rows=fetch(sym); h=sha(rows); ok=h==EXPECTED[sym]
        q.append({"symbol":sym,"rows":len(rows),"rows_sha256":h,"expected_sha256":EXPECTED[sym],"exact_match":ok})
        if not ok: raise RuntimeError(f"SEMANTIC_HASH_MISMATCH:{sym}:{h}")
    out={"schema":"AI_CORE_EVID_V2_8_6_TENCENT_DIRECT_TRANSPORT_PROBE_V1","version":"V2.8.6","status":"PASS","queries":q,
         "fold1_price_rows_read":False,"factor_or_forward_return_computed":False,"fold2_3_4_consumed":False}
    out["receipt_sha256"]=sha(out); OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
