from __future__ import annotations

import json
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright

ENDPOINT="https://www.cninfo.com.cn/new/hisAnnouncement/query"
HOME="https://www.cninfo.com.cn/"
TERM="半年度报告"
WINDOW="2026-08-31~2026-08-31"
VARIANTS=[
    ("szse_sz","szse","sz"),
    ("szse_blank","szse",""),
    ("blank_sz","","sz"),
    ("blank_blank","",""),
]

def query(api,name,column,plate):
    payload={
        "pageNum":"1","pageSize":"30","tabName":"fulltext",
        "column":column,"stock":"","searchkey":TERM,"secid":"",
        "plate":plate,"category":"","trade":"","seDate":WINDOW,
        "sortName":"time","sortType":"desc","isHLtitle":"true",
    }
    r=api.post(
        ENDPOINT,data=urlencode(payload),
        headers={
            "Content-Type":"application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With":"XMLHttpRequest",
            "Referer":"https://www.cninfo.com.cn/new/fulltextSearch",
        },timeout=60000,
    )
    out={"name":name,"column":column,"plate":plate,"http_status":r.status}
    if r.status!=200:
        return out
    obj=r.json()
    anns=obj.get("announcements") or []
    out["server_total"]=int(obj.get("totalRecordNum") or obj.get("totalAnnouncement") or 0)
    out["first_page_count"]=len(anns)
    out["codes"]=[str(a.get("secCode") or "") for a in anns[:30]]
    out["sample_titles"]=[str(a.get("announcementTitle") or "") for a in anns[:5]]
    return out

def main():
    with sync_playwright() as pw:
        api=pw.request.new_context(extra_http_headers={
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36"
        })
        home=api.get(HOME,timeout=30000)
        rows=[query(api,*v) for v in VARIANTS]
        api.dispose()
    result={
        "schema":"AI_CORE_EVID_V2_8_4_CNINFO_SZSE_ROUTE_PROBE_V1",
        "term":TERM,"window":WINDOW,"home_http_status":home.status,
        "variants":rows,
        "eligibility_effect":"NONE_TRANSPORT_DIAGNOSTIC_ONLY",
        "real_security_classification_computed":False,
        "price_or_return_data_consumed":False
    }
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if home.status!=200 or not any(r.get("server_total",0)>0 for r in rows):
        raise SystemExit(2)

if __name__=="__main__":
    main()
