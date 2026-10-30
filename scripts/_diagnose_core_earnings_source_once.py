#!/usr/bin/env python3
"""One-time read-only diagnostic: locate real Q3 deducted parent profit, do not trade."""
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CASES = [
 ("web_summary", "https://datacenter-web.eastmoney.com/api/data/v1/get",
  {"reportName":"RPT_LICO_FN_CPD","columns":"ALL","filter":"(REPORTDATE='2026-09-30')(SECURITY_CODE='600078')","pageNumber":1,"pageSize":5,"source":"WEB","client":"WEB"}),
 ("web_income", "https://datacenter-web.eastmoney.com/api/data/v1/get",
  {"reportName":"RPT_DMSK_FN_INCOME","columns":"ALL","filter":"(REPORT_DATE='2026-09-30')(SECURITY_CODE='600078')","pageNumber":1,"pageSize":5,"source":"WEB","client":"WEB"}),
 ("f10_general", "https://datacenter.eastmoney.com/securities/api/data/v1/get",
  {"reportName":"RPT_F10_FINANCE_GINCOME","columns":"ALL","filter":'(SECUCODE="600078.SH")',"pageNumber":1,"pageSize":5,"sortColumns":"REPORT_DATE","sortTypes":"-1","source":"HSF10","client":"PC"}),
 ("f10_bank", "https://datacenter.eastmoney.com/securities/api/data/v1/get",
  {"reportName":"RPT_F10_FINANCE_BINCOME","columns":"ALL","filter":'(SECUCODE="000001.SZ")',"pageNumber":1,"pageSize":5,"sortColumns":"REPORT_DATE","sortTypes":"-1","source":"HSF10","client":"PC"}),
 ("f10_main", "https://datacenter.eastmoney.com/securities/api/data/v1/get",
  {"reportName":"RPT_F10_FINANCE_MAINFINADATA","columns":"ALL","filter":'(SECUCODE="600078.SH")',"pageNumber":1,"pageSize":5,"sortColumns":"REPORT_DATE","sortTypes":"-1","source":"HSF10","client":"PC"}),
]
KEYS=("DATE","NOTICE","REPORT","DEDUCT","PARENT","UPDATE","EITIME","ORG","EPS")
for label, base, params in CASES:
    try:
        req=Request(base+"?"+urlencode(params),headers={"User-Agent":"Mozilla/5.0","Referer":"https://data.eastmoney.com"})
        with urlopen(req, timeout=12) as res:
            obj=json.loads(res.read(600000))
        data=obj.get("result") or obj.get("data") or {}
        rows=data.get("data") or data.get("diff") or []
        if isinstance(rows,dict): rows=list(rows.values())
        matches=[r for r in rows if "2026-09-30" in str(r.get("REPORT_DATE", r.get("REPORTDATE","")))]
        useful=[{k:v for k,v in r.items() if any(token in k.upper() for token in KEYS)} for r in matches[:1]]
        print(json.dumps({"case":label,"code":obj.get("code"),"success":obj.get("success"),
                          "message":str(obj.get("message",""))[:160],"row_count":len(rows),
                          "period_match":len(matches),"field_names":sorted(rows[0].keys())[:65] if rows else [],
                          "selected":useful},ensure_ascii=False,default=str))
    except Exception as e:
        print(json.dumps({"case":label,"error":type(e).__name__+":"+str(e)[:180]}))
