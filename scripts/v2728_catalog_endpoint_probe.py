from __future__ import annotations
import csv, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

MAP=Path("evidence/V2.7.27_SECURITY_ISSUER_PIT_MAP.csv")
OUT=Path("v2728_probe_artifacts")
RAW=OUT/"raw"
RAW.mkdir(parents=True,exist_ok=True)

def sha(b:bytes): return hashlib.sha256(b).hexdigest()

def sample_codes():
    rows=list(csv.DictReader(MAP.open(encoding="utf-8")))
    wanted={}
    for r in rows:
        ex=r["exchange"]; board=r["official_board_code"]
        key=None
        if ex=="SSE" and board=="1": key="SSE_MAIN"
        elif ex=="SSE" and board!="1": key="SSE_STAR"
        elif ex=="SZSE" and board=="主板": key="SZSE_MAIN"
        elif ex=="SZSE" and board=="创业板": key="SZSE_GEM"
        if key and key not in wanted:
            wanted[key]=r
    return wanted

def summarize_json(body:bytes):
    try:
        obj=json.loads(body.decode("utf-8","ignore"))
    except Exception:
        return {"json_parse":False}
    out={"json_parse":True,"top_type":type(obj).__name__}
    if isinstance(obj,dict):
        out["top_keys"]=sorted(map(str,obj.keys()))[:80]
    elif isinstance(obj,list):
        out["list_len"]=len(obj)
        if obj and isinstance(obj[0],dict):
            out["row_keys"]=sorted(map(str,obj[0].keys()))[:80]
    samples=[]
    stack=[obj]
    while stack and len(samples)<5:
        x=stack.pop()
        if isinstance(x,dict):
            ks={str(k).lower():k for k in x}
            interesting=any(any(t in k for t in ("title","announcement","date","time","url","attach","pdf","bulletin","sec","code")) for k in ks)
            if interesting:
                samples.append({str(k):x[k] for k in list(x)[:30]})
            stack.extend(x.values())
        elif isinstance(x,list):
            stack.extend(x[:50])
    out["candidate_samples"]=samples
    return out

def capture_page(page, tag, url, interact=None):
    recs=[]
    tagdir=RAW/tag
    tagdir.mkdir(parents=True,exist_ok=True)
    def on_response(resp):
        try:
            u=resp.url
            host=urlparse(u).hostname or ""
            if not any(d in host for d in ("sse.com.cn","szse.cn","cninfo.com.cn")):
                return
            ct=resp.headers.get("content-type","").lower()
            rt=resp.request.resource_type
            if rt not in ("xhr","fetch") and "json" not in ct:
                return
            body=resp.body()
            if not body: return
            ext=".json" if "json" in ct or body[:1] in (b"{",b"[") else ".bin"
            p=tagdir/f"{len(recs)+1:03d}_{hashlib.sha1(u.encode()).hexdigest()[:12]}{ext}"
            p.write_bytes(body)
            recs.append({
              "url":u,"status":resp.status,"content_type":ct,"resource_type":rt,
              "bytes":len(body),"sha256":sha(body),"path":str(p),
              "summary":summarize_json(body)
            })
        except Exception as e:
            recs.append({"capture_error":repr(e)})
    page.on("response",on_response)
    page.goto(url,wait_until="domcontentloaded",timeout=90000)
    page.wait_for_timeout(6000)
    if interact:
        try: interact(page)
        except Exception as e: recs.append({"interaction_error":repr(e)})
        page.wait_for_timeout(6000)
    (tagdir/"rendered.html").write_text(page.content(),encoding="utf-8")
    page.remove_listener("response",on_response)
    return recs

def szse_interact(code):
    def fn(page):
        candidates=[
          "input[placeholder*='股票代码']","input[placeholder*='代码']",
          "input[placeholder*='简称']"
        ]
        for sel in candidates:
            loc=page.locator(sel)
            if loc.count():
                el=loc.first
                if el.is_visible():
                    el.fill(code)
                    el.press("Enter")
                    page.wait_for_timeout(5000)
                    break
        for txt in ("定期报告","公告"):
            loc=page.get_by_text(txt,exact=True)
            if loc.count():
                for i in range(min(loc.count(),3)):
                    try:
                        if loc.nth(i).is_visible():
                            loc.nth(i).click(timeout=3000)
                            page.wait_for_timeout(4000)
                            return
                    except Exception:
                        pass
    return fn

def cninfo_interact(code):
    def fn(page):
        for sel in ("input[type='text']","input"):
            loc=page.locator(sel)
            for i in range(min(loc.count(),6)):
                try:
                    el=loc.nth(i)
                    if el.is_visible():
                        ph=el.get_attribute("placeholder") or ""
                        if "关键" in ph or "代码" in ph or "简称" in ph:
                            el.fill(code)
                            el.press("Enter")
                            page.wait_for_timeout(5000)
                            return
                except Exception: pass
    return fn

def main():
    samples=sample_codes()
    result={
      "schema":"AI_CORE_EVID_V2_7_28_CATALOG_ENDPOINT_PROBE_V1",
      "captured_at_utc":datetime.now(timezone.utc).isoformat(),
      "samples":samples,
      "captures":{}
    }
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        ctx=browser.new_context(
          user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
          locale="zh-CN"
        )
        for key,r in samples.items():
            code=r["security_code"]
            if r["exchange"]=="SSE":
                page=ctx.new_page()
                url=f"https://www.sse.com.cn/assortment/stock/list/info/announcement/index.shtml?productId={code}"
                result["captures"][key]=capture_page(page,key,url)
                page.close()
            else:
                page=ctx.new_page()
                url="https://www.szse.cn/certificate/"
                result["captures"][key]=capture_page(page,key,url,szse_interact(code))
                page.close()
        # CNInfo official disclosure fallback probe on one SSE + one SZSE code.
        for key in ("SSE_MAIN","SZSE_MAIN"):
            if key in samples:
                code=samples[key]["security_code"]
                page=ctx.new_page()
                url=f"https://www.cninfo.com.cn/new/fulltextSearch?keyWord={code}"
                result["captures"]["CNINFO_"+key]=capture_page(page,"CNINFO_"+key,url,cninfo_interact(code))
                page.close()
        browser.close()

    # Compact endpoint inventory.
    endpoint_rows=[]
    for tag,recs in result["captures"].items():
        for r in recs:
            if "url" in r:
                endpoint_rows.append({
                  "tag":tag,"url":r["url"],"status":r["status"],
                  "content_type":r["content_type"],"resource_type":r["resource_type"],
                  "bytes":r["bytes"],"sha256":r["sha256"],
                  "json_parse":r.get("summary",{}).get("json_parse"),
                  "top_keys":"|".join(r.get("summary",{}).get("top_keys",[])),
                  "row_keys":"|".join(r.get("summary",{}).get("row_keys",[])),
                })
    with (OUT/"ENDPOINT_INVENTORY.csv").open("w",encoding="utf-8",newline="") as f:
        fields=["tag","url","status","content_type","resource_type","bytes","sha256","json_parse","top_keys","row_keys"]
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n");w.writeheader();w.writerows(endpoint_rows)
    (OUT/"V2.7.28_CATALOG_ENDPOINT_PROBE.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"samples":samples,"endpoint_count":len(endpoint_rows),"inventory":endpoint_rows},ensure_ascii=False,indent=2))

if __name__=="__main__": main()
