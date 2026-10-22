"""Read-only official CNINFO pagination diagnostic for frozen SZSE:002667 range."""
import json, time, hashlib
from collections import Counter
from pathlib import Path
from playwright.sync_api import sync_playwright
import v291_negative_space_batch1 as base

OUT=Path("evidence/V2.9.4_CNINFO_002667_PAGINATION_DIAGNOSTIC_1.json")
def run(page, size):
    payload={"column":"szse","tabName":"fulltext","plate":"sz","stock":"002667,9900036460","searchkey":"","secid":"","category":"","trade":"","seDate":f"{base.START}~{base.END}","sortName":"","sortType":"","isHLtitle":"true","pageNum":"1","pageSize":str(size)}
    # Identity is anchored to V2.9.3's frozen validated PIT issuer map, never inferred from an external snippet.
    mapping={x["canonical_security_id"]:x for x in base.read_rows(base.MAP)}
    entry=mapping["SZSE:002667"]
    org=entry.get("validated_org_id") or base.resolve_org(page,"002667")
    if not org: raise RuntimeError("OFFICIAL_ORG_ID_UNRESOLVED")
    payload["stock"]="002667,"+org
    pages=[]; ids=[]; total=None
    for num in range(1,40):
        obj=json.loads(base.post(page,{**payload,"pageNum":str(num)}))
        reported=int(obj.get("totalRecordNum") or obj.get("totalAnnouncement") or 0)
        rows=obj.get("announcements") or []
        keys=[str(x.get("announcementId") or "").strip() for x in rows]
        pages.append({"page":num,"reported_total":reported,"raw_count":len(rows),"id_sha256":hashlib.sha256("\n".join(keys).encode()).hexdigest(),"ids":keys})
        if total is None: total=reported
        ids+=keys
        if not rows or len(rows)<size: break
    counts=Counter(ids)
    return {"page_size":size,"first_reported_total":total,"raw_count":len(ids),"unique_count":len(counts),"duplicate_ids":{k:v for k,v in counts.items() if v>1},"pages":pages,"complete":total==len(counts)}
def main():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(locale="zh-CN")
        page.goto("https://www.cninfo.com.cn/",wait_until="domcontentloaded",timeout=90000)
        result={"schema":"V294_CNINFO_PAGINATION_READ_ONLY_DIAGNOSTIC","security":"SZSE:002667","range":[base.START,base.END],"runs":[],"science_changed":False,"scientific_batch_authorized":False}
        for size in (30,20):
            result["runs"].append(run(page,size))
            time.sleep(2)
        browser.close()
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps([{k:x[k] for k in ("page_size","first_reported_total","raw_count","unique_count","duplicate_ids","complete")} for x in result["runs"]],ensure_ascii=False))
if __name__=="__main__":main()
