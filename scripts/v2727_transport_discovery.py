from __future__ import annotations
import hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT=Path("v2727_transport_artifacts")
RAW=OUT/"raw"
RAW.mkdir(parents=True,exist_ok=True)

SAMPLES=[
  {
    "exchange":"SSE",
    "canonical_id":"SSE:600000",
    "page":"https://www.sse.com.cn/assortment/stock/list/info/announcement/index.shtml?productId=600000"
  },
  {
    "exchange":"SZSE",
    "canonical_id":"SZSE:000001",
    "page":"https://www.szse.cn/disclosure/listed/notice/index.html?stock=000001"
  }
]

def sha(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()

def save(ex:str,i:int,url:str,ct:str,b:bytes)->str:
    ext=".bin"
    l=(ct or "").lower()
    if "json" in l: ext=".json"
    elif "pdf" in l: ext=".pdf"
    elif "excel" in l or "spreadsheet" in l: ext=".xlsx"
    p=RAW/ex.lower()/f"{i:04d}_{hashlib.sha1(url.encode()).hexdigest()[:12]}{ext}"
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes(b)
    return str(p)

def looks_relevant(url:str,ct:str)->bool:
    u=url.lower(); c=(ct or "").lower()
    keys=("announcement","bulletin","disclosure","disc","report","query","notice","pdf")
    return any(k in u for k in keys) or "json" in c or "pdf" in c

def main():
    manifest={
      "schema":"AI_CORE_EVID_V2_7_27_TRANSPORT_DISCOVERY_V1",
      "captured_at_utc":datetime.now(timezone.utc).isoformat(),
      "samples":[]
    }
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        for sample in SAMPLES:
            ex=sample["exchange"]; recs=[]; errors=[]
            page=browser.new_page(
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
              locale="zh-CN"
            )
            def on_response(resp):
                try:
                    ct=resp.headers.get("content-type","")
                    if not looks_relevant(resp.url,ct): return
                    if resp.status>=400: 
                        recs.append({"url":resp.url,"status":resp.status,"content_type":ct})
                        return
                    b=resp.body()
                    if not b: return
                    p=save(ex,len(recs)+1,resp.url,ct,b)
                    req=resp.request
                    recs.append({
                      "url":resp.url,"status":resp.status,"content_type":ct,
                      "request_method":req.method,
                      "request_post_data":req.post_data,
                      "path":p,"bytes":len(b),"sha256":sha(b)
                    })
                except Exception as e:
                    errors.append(repr(e))
            page.on("response",on_response)
            page.goto(sample["page"],wait_until="domcontentloaded",timeout=90000)
            page.wait_for_timeout(8000)

            controls=[]
            for idx in range(page.locator("select").count()):
                sel=page.locator("select").nth(idx)
                try:
                    controls.append({
                      "index":idx,
                      "name":sel.get_attribute("name"),
                      "id":sel.get_attribute("id"),
                      "options":sel.locator("option").all_text_contents()
                    })
                except Exception as e:
                    controls.append({"index":idx,"error":repr(e)})

            # Prefer official UI filters for periodic reports when visible.
            filter_actions=[]
            for target in ("半年度报告","年度报告","定期报告"):
                loc=page.get_by_text(target,exact=True)
                for i in range(min(loc.count(),5)):
                    try:
                        el=loc.nth(i)
                        if el.is_visible():
                            el.click(timeout=3000)
                            filter_actions.append({"text":target,"index":i})
                            page.wait_for_timeout(2500)
                            break
                    except Exception:
                        pass

            # Trigger visible query button once if present.
            for label in ("查询","搜索"):
                loc=page.get_by_text(label,exact=True)
                clicked=False
                for i in range(min(loc.count(),5)):
                    try:
                        if loc.nth(i).is_visible():
                            loc.nth(i).click(timeout=3000)
                            page.wait_for_timeout(5000)
                            clicked=True; break
                    except Exception:
                        pass
                if clicked: break

            html=page.content().encode("utf-8")
            hp=RAW/ex.lower()/"rendered_page.html"; hp.write_bytes(html)
            manifest["samples"].append({
              **sample,
              "rendered_page_sha256":sha(html),
              "controls":controls,
              "filter_actions":filter_actions,
              "responses":recs,
              "errors":errors
            })
            page.close()
        browser.close()

    (OUT/"TRANSPORT_DISCOVERY_V2.7.27.json").write_text(
      json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
