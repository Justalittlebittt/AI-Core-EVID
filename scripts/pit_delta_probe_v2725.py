from __future__ import annotations
import hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from playwright.sync_api import sync_playwright

PIT_DATE="2026-09-17"
OUT=Path("pit_delta_artifacts")
RAW=OUT/"raw"
RAW.mkdir(parents=True,exist_ok=True)

PAGES=[
    ("sse_delisting","SSE","https://www.sse.com.cn/assortment/stock/list/delisting/"),
    ("szse_suspend_delist","SZSE","https://www.szse.cn/market/stock/suspend/index.html"),
]

def sha(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()

def safe(tag:str,i:int,url:str,ct:str)->Path:
    ext=".bin"
    l=(ct or "").lower()
    if "json" in l: ext=".json"
    elif "excel" in l or "spreadsheet" in l: ext=".xlsx"
    elif "csv" in l: ext=".csv"
    return RAW/tag/f"{i:04d}_{hashlib.sha1(url.encode()).hexdigest()[:12]}{ext}"

def collect_metadata(obj:Any,out:list):
    if isinstance(obj,dict):
        md=obj.get("metadata")
        if isinstance(md,dict):
            out.append(md)
        for v in obj.values():
            collect_metadata(v,out)
    elif isinstance(obj,list):
        for v in obj:
            collect_metadata(v,out)

def collect_rows(obj:Any,out:list):
    if isinstance(obj,dict):
        keys=[str(k) for k in obj]
        joined="|".join(keys).lower()
        values="|".join(str(v) for v in obj.values() if v is not None)
        has_code=any(x in joined for x in ["code","证券代码","股票代码","公司代码","zqdm","agdm"])
        has_event=any(x in joined for x in ["delist","suspend","date","终止","暂停","退市","摘牌","ssrq"]) or any(x in values for x in ["终止上市","暂停上市","退市","摘牌"])
        if has_code and has_event:
            out.append(obj)
        for v in obj.values():
            collect_rows(v,out)
    elif isinstance(obj,list):
        for v in obj:
            collect_rows(v,out)

def decode_json(b:bytes):
    s=b.decode("utf-8","ignore").strip()
    try:
        return json.loads(s)
    except Exception:
        m=re.match(r"^[A-Za-z_$][\w$]*\((.*)\)\s*;?\s*$",s,re.S)
        if m:
            return json.loads(m.group(1))
        raise

def capture(tag:str,exchange:str,url:str):
    d=RAW/tag; d.mkdir(parents=True,exist_ok=True)
    recs=[]
    ui_actions=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
            locale="zh-CN",
        )
        def on_response(resp):
            try:
                if ("sse.com.cn" not in resp.url) and ("szse.cn" not in resp.url):
                    return
                ct=resp.headers.get("content-type","")
                if not any(x in ct.lower() for x in ["json","excel","spreadsheet","csv","octet-stream"]):
                    return
                body=resp.body()
                if not body: return
                p=safe(tag,len(recs)+1,resp.url,ct)
                p.parent.mkdir(parents=True,exist_ok=True)
                p.write_bytes(body)
                recs.append({
                    "exchange":exchange,"url":resp.url,"status":resp.status,
                    "content_type":ct,"path":str(p),"bytes":len(body),"sha256":sha(body),
                    "captured_at_utc":datetime.now(timezone.utc).isoformat()
                })
            except Exception as e:
                recs.append({"capture_error":repr(e),"exchange":exchange})
        page.on("response",on_response)
        page.goto(url,wait_until="domcontentloaded",timeout=90000)
        page.wait_for_timeout(7000)

        # Try every visible select option explicitly labelled as terminated/delisted.
        for idx in range(page.locator("select").count()):
            sel=page.locator("select").nth(idx)
            try:
                opts=sel.locator("option").all_text_contents()
                for txt in opts:
                    if "终止上市" in txt:
                        sel.select_option(label=txt)
                        ui_actions.append({"type":"select","index":idx,"label":txt})
                        page.wait_for_timeout(5000)
                        break
            except Exception as e:
                ui_actions.append({"type":"select_error","index":idx,"error":repr(e)})

        # Also try explicit visible text/tabs.
        loc=page.get_by_text("终止上市",exact=True)
        for i in range(min(loc.count(),5)):
            try:
                el=loc.nth(i)
                if el.is_visible():
                    el.click(timeout=3000)
                    ui_actions.append({"type":"click_text","index":i,"text":"终止上市"})
                    page.wait_for_timeout(5000)
            except Exception as e:
                ui_actions.append({"type":"click_error","index":i,"error":repr(e)})

        html=page.content().encode("utf-8")
        hp=d/"rendered_page.html"; hp.write_bytes(html)
        browser.close()
    return recs,ui_actions

def main():
    all_recs=[]; actions=[]
    for tag,ex,url in PAGES:
        try:
            r,a=capture(tag,ex,url); all_recs.extend(r); actions.extend([{"tag":tag,**x} for x in a])
        except Exception as e:
            all_recs.append({"tag":tag,"exchange":ex,"page_error":repr(e)})

    summaries=[]
    for r in all_recs:
        p=Path(r.get("path",""))
        if not p.is_file() or p.suffix.lower()!=".json":
            continue
        md=[]; rows=[]
        try:
            obj=decode_json(p.read_bytes())
            collect_metadata(obj,md); collect_rows(obj,rows)
            summaries.append({
                "path":str(p),"url":r.get("url"),"metadata":md[:20],
                "candidate_row_count":len(rows),
                "candidate_row_samples":rows[:20]
            })
        except Exception as e:
            summaries.append({"path":str(p),"url":r.get("url"),"parse_error":repr(e)})

    result={
        "schema":"AI_CORE_EVID_V2_7_25_PIT_DELTA_PROBE_V1",
        "pit_date":PIT_DATE,
        "capture_date_utc":datetime.now(timezone.utc).date().isoformat(),
        "purpose":"Discover official delisting/suspension source structure; does not clear gate.",
        "responses":all_recs,
        "ui_actions":actions,
        "parsed_summaries":summaries
    }
    (OUT/"PIT_DELTA_PROBE_SUMMARY.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
