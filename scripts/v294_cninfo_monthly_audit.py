"""Read-only monthly partition pagination audit; never authorizes scientific evidence."""
import calendar, hashlib, json
from collections import Counter
from pathlib import Path
from playwright.sync_api import sync_playwright
import v291_negative_space_batch1 as base

OUT=Path("evidence/V2.9.4_CNINFO_002667_MONTHLY_AUDIT_1.json")
def collect(page, org, start, end):
    payload={"column":"szse","tabName":"fulltext","plate":"sz","stock":"002667,"+org,"searchkey":"","secid":"","category":"","trade":"","seDate":start+"~"+end,"sortName":"","sortType":"","isHLtitle":"true","pageNum":"1","pageSize":"30"}
    all_ids=[]; totals=[]; counts=[]
    for n in range(1,50):
        obj=json.loads(base.post(page,{**payload,"pageNum":str(n)}))
        total=int(obj.get("totalRecordNum") or obj.get("totalAnnouncement") or 0)
        ids=[str(a.get("announcementId") or "").strip() for a in (obj.get("announcements") or [])]
        totals.append(total);counts.append(len(ids));all_ids+=ids
        if len(ids)<30:break
    else:raise RuntimeError("MONTH_PAGE_RUNAWAY")
    ded=Counter(all_ids)
    return {"range":[start,end],"reported_totals":sorted(set(totals)),"page_counts":counts,"raw_count":len(all_ids),"unique_count":len(ded),"duplicate_ids":[k for k,v in ded.items() if v>1],"complete":len(set(totals))==1 and len(ded)==totals[0] and all(all_ids) and len(all_ids)==totals[0],"ids":sorted(ded)}
def main():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);page=browser.new_page(locale="zh-CN")
        page.goto("https://www.cninfo.com.cn/",wait_until="domcontentloaded",timeout=90000)
        mapping={x["canonical_security_id"]:x for x in base.read_rows(base.MAP)}
        org=mapping["SZSE:002667"].get("validated_org_id") or base.resolve_org(page,"002667")
        months=[]
        for year in (2023,2024):
            for month in range(1,13):
                start=f"{year}-{month:02d}-01"
                end=f"{year}-{month:02d}-{calendar.monthrange(year,month)[1]:02d}"
                if end>base.END:end=base.END
                months.append(collect(page,org,start,end))
        browser.close()
    seen={}
    for m in months:
        for aid in m["ids"]:seen.setdefault(aid,[]).append(m["range"][0])
    cross={aid:ms for aid,ms in seen.items() if len(ms)>1}
    result={"schema":"V294_CNINFO_MONTHLY_PARTITION_AUDIT_1","security":"SZSE:002667","frozen_range":[base.START,base.END],"months":months,"all_months_closed":all(m["complete"] for m in months),"unique_union_count":len(seen),"cross_month_duplicates":cross,"scientific_admission_authorized":False}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"months_closed":sum(m["complete"] for m in months),"months_total":len(months),"union":len(seen),"cross_month_duplicates":len(cross)},ensure_ascii=False))
if __name__=="__main__":main()
