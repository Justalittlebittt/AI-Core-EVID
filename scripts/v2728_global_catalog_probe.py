from __future__ import annotations
import csv,json
from pathlib import Path
from playwright.sync_api import sync_playwright

MAP=Path("evidence/V2.7.27_SECURITY_ISSUER_PIT_MAP.csv")
OUT=Path("v2728_global_probe_artifacts"); OUT.mkdir(exist_ok=True)
CUTOFF="2026-09-16"
START="2025-01-01"
CATS={"ANNUAL":"category_ndbg_szsh","HALF_YEAR":"category_bndbg_szsh"}

def main():
    rows=list(csv.DictReader(MAP.open(encoding="utf-8")))
    by_code={r["security_code"]:r for r in rows}
    result={"schema":"AI_CORE_EVID_V2_7_28_GLOBAL_CATALOG_PROBE_V1","queries":[]}
    with sync_playwright() as pw:
        b=pw.chromium.launch(headless=True)
        page=b.new_page(
          user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
          locale="zh-CN")
        page.goto("https://www.cninfo.com.cn/",wait_until="domcontentloaded",timeout=90000)
        page.wait_for_timeout(3000)
        for exchange,column,plate in [("SSE","sse","sh"),("SZSE","szse","sz")]:
          for kind,category in CATS.items():
            payload={
              "pageNum":"1","pageSize":"30","column":column,"tabName":"fulltext",
              "plate":plate,"stock":"","searchkey":"","secid":"","category":category,
              "trade":"","seDate":f"{START}~{CUTOFF}","sortName":"","sortType":"","isHLtitle":"true"
            }
            q=page.evaluate("""async (payload) => {
              const body = new URLSearchParams(payload).toString();
              const r = await fetch('/new/hisAnnouncement/query', {
                method:'POST',
                headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'},
                body
              });
              return {status:r.status,text:await r.text()};
            }""",payload)
            rec={"exchange":exchange,"column":column,"plate":plate,"kind":kind,"category":category,"status":q["status"]}
            if q["status"]==200:
                obj=json.loads(q["text"])
                anns=obj.get("announcements") or []
                samples=[]
                wrong=[]
                for a in anns[:30]:
                    code=str(a.get("secCode") or "")
                    m=by_code.get(code)
                    if m and m["exchange"]!=exchange:
                        wrong.append({"secCode":code,"mapped_exchange":m["exchange"]})
                    samples.append({k:a.get(k) for k in (
                      "secCode","secName","orgId","announcementId","announcementTitle",
                      "announcementTime","adjunctUrl","adjunctType","announcementType","pageColumn"
                    )})
                rec.update({
                  "totalpages":obj.get("totalpages"),
                  "totalRecordNum":obj.get("totalRecordNum"),
                  "totalAnnouncement":obj.get("totalAnnouncement"),
                  "page_count":len(anns),
                  "sample_mapped_to_expected_exchange_count":sum(1 for a in anns[:30] if (str(a.get("secCode") or "") in by_code and by_code[str(a.get("secCode") or "")]["exchange"]==exchange)),
                  "wrong_exchange_samples":wrong,
                  "samples":samples
                })
            result["queries"].append(rec)
        b.close()
    (OUT/"V2.7.28_GLOBAL_CATALOG_PROBE.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if any(q.get("status")!=200 or not q.get("totalpages") for q in result["queries"]):
        raise SystemExit(2)
if __name__=="__main__": main()
