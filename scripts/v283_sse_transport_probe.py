from __future__ import annotations
import json,time
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright

ENDPOINT="https://query.sse.com.cn/sseQuery/commonQuery.do"
REFERER="https://www.sse.com.cn/assortment/stock/list/share/"
OUT=Path("evidence/V2.8.3_SSE_TRANSPORT_PROBE_1.json")

def params():
    return {
      "jsonCallBack":"jsonpCallback2831",
      "STOCK_TYPE":"1",
      "REG_PROVINCE":"",
      "CSRC_CODE":"",
      "STOCK_CODE":"",
      "sqlId":"COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
      "COMPANY_STATUS":"2,4,5,7,8",
      "type":"inParams",
      "isPagination":"true",
      "pageHelp.cacheSize":"1",
      "pageHelp.pageSize":"100",
      "_":str(int(time.time()*1000)),
      "pageHelp.beginPage":"1",
      "pageHelp.pageNo":"1",
      "pageHelp.endPage":"1",
    }

def main():
    p=params()
    sess=requests.Session()
    sess.headers.update({
      "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
      "Referer":REFERER,
      "Accept":"*/*",
    })
    try:
        warm=sess.get(REFERER,timeout=20)
        warm_status=warm.status_code
    except Exception as e:
        warm_status=f"ERR:{type(e).__name__}:{e}"
    try:
        r=sess.get(ENDPOINT,params=p,timeout=30)
        requests_result={"status":r.status_code,"bytes":len(r.content),"content_type":r.headers.get("content-type","")}
    except Exception as e:
        requests_result={"status":0,"error":f"{type(e).__name__}:{e}"}

    browser_result={}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(locale="zh-CN")
        nav=page.goto(REFERER,wait_until="domcontentloaded",timeout=90000)
        page.wait_for_timeout(1500)
        browser_result=page.evaluate("""async ({endpoint,payload})=>{
          const u=new URL(endpoint);
          Object.entries(payload).forEach(([k,v])=>u.searchParams.set(k,v));
          try {
            const r=await fetch(u.toString(),{
              method:'GET',
              headers:{'Accept':'*/*','X-Requested-With':'XMLHttpRequest'},
              credentials:'include'
            });
            const t=await r.text();
            return {status:r.status,bytes:t.length,content_type:r.headers.get('content-type')||'',prefix:t.slice(0,120)};
          } catch(e) {
            return {status:0,error:String(e)};
          }
        }""",{"endpoint":ENDPOINT,"payload":p})
        browser_result["referer_navigation_status"]=nav.status if nav else None
        browser.close()

    out={
      "schema":"AI_CORE_EVID_V2_8_3_SSE_TRANSPORT_PROBE_1",
      "status":"PROBE_COMPLETE",
      "official_endpoint":ENDPOINT,
      "requests_warmup_status":warm_status,
      "requests":requests_result,
      "browser_same_origin":browser_result,
      "scientific_output_generated":False,
      "price_or_return_data_consumed":False,
      "fold3_accessed":False,
      "fold4_accessed":False
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
