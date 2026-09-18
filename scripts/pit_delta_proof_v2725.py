from __future__ import annotations
import hashlib, io, json, re
from datetime import date, datetime, timezone
from pathlib import Path
import pandas as pd
import requests
from playwright.sync_api import sync_playwright

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
    headers={
      "Accept":"*/*",
      "Accept-Language":"zh-CN,zh;q=0.9,en;q=0.8",
      "Cache-Control":"no-cache",
      "Pragma":"no-cache",
      "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153.0 Safari/537.36",
      "Referer":"https://www.sse.com.cn/assortment/stock/list/delisting/",
    }
    endpoints=[
      "https://query.sse.com.cn/commonQuery.do",
      "https://query.sse.com.cn/sseQuery/commonQuery.do",
    ]
    events=[]; source_files=[]; failures=[]
    # Split Main A and STAR so no ticker/board inference is needed.
    for stock_type,label in [("1","MAIN_A"),("8","STAR")]:
        success=False
        for endpoint in endpoints:
            params={
              "sqlId":"COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
              "isPagination":"true","STOCK_CODE":"","CSRC_CODE":"","REG_PROVINCE":"",
              "STOCK_TYPE":stock_type,"COMPANY_STATUS":"3","type":"inParams",
              "pageHelp.cacheSize":"1","pageHelp.beginPage":"1","pageHelp.pageSize":"10000",
              "pageHelp.pageNo":"1","pageHelp.endPage":"1",
            }
            for attempt in range(1,4):
                try:
                    r=requests.get(endpoint,params=params,headers=headers,timeout=60)
                    if r.status_code==403:
                        failures.append({"label":label,"endpoint":endpoint,"attempt":attempt,"status":403})
                        continue
                    r.raise_for_status()
                    sm=save(f"sse_delisted_{label}_{attempt}.json",r.content)
                    j=r.json()
                    rows=j.get("result") or (j.get("pageHelp") or {}).get("data") or []
                    if not isinstance(rows,list):
                        raise RuntimeError("SSE delist rows not list")
                    for x in rows:
                        c=code6(x.get("A_STOCK_CODE") or x.get("COMPANY_CODE"))
                        dd=d(x.get("DELIST_DATE"))
                        if c and dd:
                            events.append({
                              "canonical_id":"SSE:"+c,
                              "delist_date":dd.isoformat(),
                              "name":x.get("COMPANY_ABBR"),
                              "stock_type":stock_type,
                            })
                    source_files.append({"label":label,"endpoint":endpoint,"rows":len(rows),**sm})
                    success=True
                    break
                except Exception as e:
                    failures.append({"label":label,"endpoint":endpoint,"attempt":attempt,"error":repr(e)})
            if success: break
        if not success:
            raise RuntimeError(f"SSE delisted capture failed for {label}: {failures[-6:]}")
    # De-duplicate across source pages by canonical id + date.
    uniq={(e["canonical_id"],e["delist_date"]):e for e in events}
    return list(uniq.values()),{"rows":len(uniq),"files":source_files,"failures":failures}

def szse_delisted():
    # Direct requests from hosted runners are intermittently reset by SZSE.
    # Use a real browser page, then fetch the same official JSON endpoint
    # inside the accepted same-origin browser context.
    page_url="https://www.szse.cn/market/stock/suspend/index.html"
    api_path="/api/report/ShowReport/data"
    events=[]; files=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(
          user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
          locale="zh-CN",
        )
        page.goto(page_url,wait_until="domcontentloaded",timeout=90000)
        page.wait_for_timeout(5000)

        def get_page(n:int):
            return page.evaluate("""async ({path,n}) => {
              const u = path + '?SHOWTYPE=JSON&CATALOGID=1793_ssgs&TABKEY=tab2&PAGENO=' + n + '&random=' + Math.random();
              const r = await fetch(u, {credentials:'same-origin'});
              return {status:r.status, url:r.url, text:await r.text()};
            }""", {"path":api_path,"n":n})

        first=get_page(1)
        if first["status"] != 200:
            raise RuntimeError(f"SZSE browser fetch HTTP {first['status']}")
        raw=first["text"].encode("utf-8")
        sm=save("szse_delisted_page_01.json",raw)
        jo=json.loads(first["text"])
        b=next((x for x in jo if isinstance(x,dict) and (x.get("metadata") or {}).get("tabkey")=="tab2"), jo[0])
        md=b.get("metadata") or {}
        pages=int(md.get("pagecount") or 1)
        recordcount=int(md.get("recordcount") or 0)

        total_rows=0
        for n in range(1,pages+1):
            if n==1:
                obj=jo; meta=sm; fetch_url=first["url"]
            else:
                q=get_page(n)
                if q["status"] != 200:
                    raise RuntimeError(f"SZSE page {n} HTTP {q['status']}")
                raw=q["text"].encode("utf-8")
                meta=save(f"szse_delisted_page_{n:02d}.json",raw)
                obj=json.loads(q["text"]); fetch_url=q["url"]
            block=next((x for x in obj if isinstance(x,dict) and (x.get("metadata") or {}).get("tabkey")=="tab2"), obj[0])
            rows=block.get("data") or []
            total_rows += len(rows)
            for row in rows:
                cc=code6(row.get("zqdm")); dd=d(row.get("zzrq"))
                if cc and dd:
                    events.append({
                      "canonical_id":"SZSE:"+cc,
                      "delist_date":dd.isoformat(),
                      "name":str(row.get("zqjc","")),
                      "list_date":str(row.get("ssrq","")),
                    })
            files.append({"page":n,"rows":len(rows),"url":fetch_url,**meta})
        browser.close()
    if recordcount and total_rows != recordcount:
        raise RuntimeError(f"SZSE delist pagination incomplete: {total_rows} != {recordcount}")
    uniq={(e["canonical_id"],e["delist_date"]):e for e in events}
    return list(uniq.values()),{"recordcount":recordcount,"pagecount":pages,"rows_fetched":total_rows,"files":files}

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
