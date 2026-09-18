from __future__ import annotations
import csv,json
from pathlib import Path
from playwright.sync_api import sync_playwright

MAP=Path("evidence/V2.7.27_SECURITY_ISSUER_PIT_MAP.csv")
OUT=Path("v2728_contract_artifacts"); OUT.mkdir(exist_ok=True)

def pick():
    rows=list(csv.DictReader(MAP.open(encoding="utf-8")))
    a=next(r for r in rows if r["canonical_security_id"]=="SSE:600000")
    b=next(r for r in rows if r["canonical_security_id"]=="SZSE:000001")
    return [a,b]

def main():
    records=[]
    with sync_playwright() as pw:
        b=pw.chromium.launch(headless=True)
        ctx=b.new_context(
          user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
          locale="zh-CN")
        for row in pick():
            page=ctx.new_page()
            reqs=[]
            def on_req(req):
                if "cninfo.com.cn/new/hisAnnouncement/query" in req.url:
                    reqs.append({
                      "method":req.method,
                      "url":req.url,
                      "post_data":req.post_data,
                      "headers":{k:v for k,v in req.headers.items() if k.lower() in ("content-type","origin","referer","x-requested-with")}
                    })
            page.on("request",on_req)
            code=row["security_code"]
            page.goto(f"https://www.cninfo.com.cn/new/fulltextSearch?keyWord={code}",wait_until="domcontentloaded",timeout=90000)
            page.wait_for_timeout(4000)
            # Resolve the security exactly as the production UI does.
            q=page.locator("input")
            filled=False
            for i in range(min(q.count(),12)):
                try:
                    el=q.nth(i)
                    if el.is_visible():
                        ph=el.get_attribute("placeholder") or ""
                        if any(x in ph for x in ("代码","简称","关键")):
                            el.fill(code); el.press("Enter"); filled=True
                            page.wait_for_timeout(6000); break
                except Exception: pass
            records.append({"canonical_security_id":row["canonical_security_id"],"filled":filled,"requests":reqs})
            page.close()
        b.close()
    (OUT/"V2.7.28_CNINFO_REQUEST_CONTRACT.json").write_text(json.dumps(records,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(records,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
