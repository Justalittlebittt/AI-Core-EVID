from __future__ import annotations
import hashlib, io, json, re
from datetime import date, datetime, timezone
from pathlib import Path
import pandas as pd
import requests

PIT=date.fromisoformat("2026-09-17")
CAPTURE=datetime.now(timezone.utc).date()
OUT=Path("pit_delta_proof_artifacts")
RAW=OUT/"raw"
RAW.mkdir(parents=True,exist_ok=True)

def sha(b:bytes): return hashlib.sha256(b).hexdigest()
def save(name,b):
    p=RAW/name; p.write_bytes(b)
    return {"path":str(p),"bytes":len(b),"sha256":sha(b)}
def d(v):
    x=pd.to_datetime(v,errors="coerce")
    return None if pd.isna(x) else x.date()
def code6(v):
    m=re.fullmatch(r"\s*(\d{1,6})\s*",str(v))
    return m.group(1).zfill(6) if m else None

def sse_delisted():
    url="https://query.sse.com.cn/commonQuery.do"
    params={
      "sqlId":"COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
      "isPagination":"true","STOCK_CODE":"","CSRC_CODE":"","REG_PROVINCE":"",
      "STOCK_TYPE":"1,8","COMPANY_STATUS":"3","type":"inParams",
      "pageHelp.cacheSize":"1","pageHelp.beginPage":"1","pageHelp.pageSize":"10000",
      "pageHelp.pageNo":"1","pageHelp.endPage":"1",
    }
    r=requests.get(url,params=params,headers={
      "User-Agent":"Mozilla/5.0",
      "Referer":"https://www.sse.com.cn/assortment/stock/list/delisting/"
    },timeout=60)
    r.raise_for_status()
    meta=save("sse_delisted.json",r.content)
    j=r.json()
    rows=j.get("result") or (j.get("pageHelp") or {}).get("data") or []
    events=[]
    for x in rows:
        c=code6(x.get("A_STOCK_CODE") or x.get("COMPANY_CODE"))
        dd=d(x.get("DELIST_DATE"))
        if c and dd:
            events.append({
              "canonical_id":"SSE:"+c,
              "delist_date":dd.isoformat(),
              "name":x.get("COMPANY_ABBR"),
              "stock_type":x.get("STOCK_TYPE"),
              "raw":x,
            })
    return events,{"rows":len(rows),**meta}

def szse_delisted():
    url="https://www.szse.cn/api/report/ShowReport"
    params={"SHOWTYPE":"xlsx","CATALOGID":"1793_ssgs","TABKEY":"tab2"}
    r=requests.get(url,params=params,headers={
      "User-Agent":"Mozilla/5.0",
      "Referer":"https://www.szse.cn/market/stock/suspend/index.html"
    },timeout=60)
    r.raise_for_status()
    meta=save("szse_delisted.xlsx",r.content)
    sheets=pd.read_excel(io.BytesIO(r.content),sheet_name=None,dtype=str)
    events=[]; sheet_meta={}
    for sheet,df in sheets.items():
        sheet_meta[sheet]={"rows":len(df),"columns":[str(c) for c in df.columns]}
        cols={str(c).replace(" ",""):c for c in df.columns}
        code_col=next((orig for k,orig in cols.items() if k in ("证券代码","A股代码","代码")),None)
        date_col=next((orig for k,orig in cols.items() if any(t in k for t in ("终止上市日期","摘牌日期","退市日期"))),None)
        name_col=next((orig for k,orig in cols.items() if k in ("证券简称","A股简称","公司简称")),None)
        if not code_col or not date_col:
            continue
        for _,row in df.iterrows():
            c=code6(row.get(code_col)); dd=d(row.get(date_col))
            if c and dd:
                events.append({
                  "canonical_id":"SZSE:"+c,
                  "delist_date":dd.isoformat(),
                  "name":str(row.get(name_col,"")) if name_col else "",
                  "source_sheet":sheet,
                })
    return events,{"sheets":sheet_meta,**meta}

def main():
    result={
      "schema":"AI_CORE_EVID_V2_7_25_PIT_DELTA_PROOF_V1",
      "pit_date":PIT.isoformat(),
      "capture_date_utc":CAPTURE.isoformat(),
      "method":"official full delisted-company tables; detect removals effective after PIT through capture",
      "sources":{},
      "events_after_pit_through_capture":[],
      "status":"BLOCKED",
    }
    try:
        sse,sm=sse_delisted(); result["sources"]["sse"]=sm
        sz,zm=szse_delisted(); result["sources"]["szse"]=zm
        events=sse+sz
        for e in events:
            dd=date.fromisoformat(e["delist_date"])
            if PIT < dd <= CAPTURE:
                result["events_after_pit_through_capture"].append(e)
        result["all_delist_event_count"]=len(events)
        result["delta_event_count"]=len(result["events_after_pit_through_capture"])
        # This proof addresses removals only. Additions are separately reconstructed
        # by official LIST_DATE <= PIT in V2.7.24.
        result["status"]="PASS_NO_REMOVALS_IN_DELTA" if result["delta_event_count"]==0 else "PASS_WITH_REMOVALS_TO_ADD_BACK"
        result["pit_reconstruction_instruction"]={
          "additions_after_pit":"exclude via official LIST_DATE > PIT",
          "removals_after_pit":"add back these canonical IDs to current official set",
        }
    except Exception as e:
        import traceback
        result["error"]=repr(e); result["traceback"]=traceback.format_exc()
    canonical=json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    result["receipt_sha256"]=sha(canonical)
    (OUT/"PIT_DELTA_PROOF_V2.7.25.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__": raise SystemExit(main())
