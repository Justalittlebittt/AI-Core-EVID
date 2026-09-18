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
    # Browser probe proved this official JSON endpoint and metadata:
    # CATALOGID=1793_ssgs, tab2=终止上市, zqdm/ssrq/zzrq,
    # with pagecount/recordcount supplied by the exchange.
    url="https://www.szse.cn/api/report/ShowReport/data"
    headers={
      "User-Agent":"Mozilla/5.0",
      "Referer":"https://www.szse.cn/market/stock/suspend/index.html"
    }
    session=requests.Session()
    first=session.get(url,params={
      "SHOWTYPE":"JSON","CATALOGID":"1793_ssgs","TABKEY":"tab2","PAGENO":"1"
    },headers=headers,timeout=60)
    first.raise_for_status()
    obj=first.json()
    block=obj[1] if isinstance(obj,list) and len(obj)>1 and (obj[1].get("metadata") or {}).get("tabkey")=="tab2" else obj[0]
    md=block.get("metadata") or {}
    pages=int(md.get("pagecount") or 1)
    recordcount=int(md.get("recordcount") or 0)
    events=[]; files=[]; raw_rows=0
    for page in range(1,pages+1):
        r=first if page==1 else session.get(url,params={
          "SHOWTYPE":"JSON","CATALOGID":"1793_ssgs","TABKEY":"tab2","PAGENO":str(page)
        },headers=headers,timeout=60)
        r.raise_for_status()
        sm=save(f"szse_delisted_page_{page:02d}.json",r.content)
        jo=r.json()
        b=next((x for x in jo if isinstance(x,dict) and (x.get("metadata") or {}).get("tabkey")=="tab2"), jo[0]) if isinstance(jo,list) else jo
        rows=b.get("data") or []
        raw_rows += len(rows)
        for row in rows:
            c=code6(row.get("zqdm")); dd=d(row.get("zzrq"))
            if c and dd:
                events.append({
                  "canonical_id":"SZSE:"+c,
                  "delist_date":dd.isoformat(),
                  "name":str(row.get("zqjc","")),
                  "list_date":str(row.get("ssrq","")),
                })
        files.append({"page":page,"rows":len(rows),**sm})
    if recordcount and raw_rows != recordcount:
        raise RuntimeError(f"SZSE delist pagination incomplete: {raw_rows} != {recordcount}")
    return events,{"recordcount":recordcount,"pagecount":pages,"rows_fetched":raw_rows,"files":files}

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
