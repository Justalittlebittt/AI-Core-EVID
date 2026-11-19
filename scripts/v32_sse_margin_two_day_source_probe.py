#!/usr/bin/env python3
"""Official SSE two-date margin detail source admission, exhaustive page boundary.

SSE now returns dict records (stockCode/opDate/rzye/rzmre/rzche)
and caps pageSize at 2000. Require all pageHelp.total identities exactly.
No stock price outcomes or trading/strategy claims.
"""
import hashlib
import json
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path

DAYS=("20261116","20261117")
URL="https://query.sse.com.cn/marketdata/tradedata/queryMargin.do"

def fetch(day,page):
    q={"isPagination":"true","tabType":"mxtype","detailsDate":day,
       "stockCode":"","beginDate":"","endDate":"",
       "pageHelp.pageSize":"2000","pageHelp.pageCount":"50",
       "pageHelp.pageNo":str(page),"pageHelp.beginPage":str(page),
       "pageHelp.cacheSize":"1","pageHelp.endPage":str(page)}
    req=urllib.request.Request(URL+"?"+urllib.parse.urlencode(q),headers={
      "Referer":"https://www.sse.com.cn/market/othersdata/margin/detail/",
      "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
      "Accept":"application/json,text/plain,*/*"})
    with urllib.request.urlopen(req,timeout=18) as res:
        raw=res.read(3500001)
    if len(raw)>3500000:raise ValueError("SOURCE_PAGE_OVER_3_5MB")
    obj=json.loads(raw)
    if not isinstance(obj,dict) or not isinstance(obj.get("result"),list):
        raise ValueError("SSE_RESPONSE_INVALID")
    help_=obj.get("pageHelp")
    if not isinstance(help_,dict):raise ValueError("SSE_PAGINATION_NOT_PROVEN")
    return obj["result"],help_,hashlib.sha256(raw).hexdigest()

def parse(row,day):
    if not isinstance(row,dict):raise ValueError("SSE_ROW_NOT_CURRENT_OBJECT_SCHEMA")
    if str(row.get("opDate"))!=day:raise ValueError("SSE_WRONG_DATE")
    code=str(row.get("stockCode") or "")
    if len(code)!=6 or not code.isdigit():raise ValueError("SSE_BAD_SECURITY_ID")
    def dec(k):
        try:
            x=Decimal(str(row[k]))
        except (InvalidOperation,KeyError,TypeError):
            raise ValueError("SSE_FINANCING_NUMBER_INVALID_"+k)
        if not x.is_finite() or x<0:raise ValueError("SSE_NONFINITE_NEGATIVE_"+k)
        return x
    bal,buy,rep=dec("rzye"),dec("rzmre"),dec("rzche")
    return code,{"balance":str(bal),"buy":str(buy),"repay":str(rep)}

def day_report(day):
    data={}
    pages=[]
    status="NOT_COMPLETE"
    expected=None
    try:
        for page in range(1,5):
            rows,h,sha=fetch(day,page)
            total=int(h["total"])
            print("SSE_PAGINATION_METADATA",day,page,"returned_page",h.get("pageNo"),"pageCount",h.get("pageCount"),"first_code",rows[0].get("stockCode") if rows else None,flush=True)
            page_count=int(h["pageCount"])
            page_no=int(h["pageNo"])
            if page_no!=page or total<0 or page_count<1:raise ValueError("BAD_PAGINATION_META")
            if expected is None:expected=total
            if expected!=total:raise ValueError("TOTAL_CHANGED_DURING_PAGING")
            for r in rows:
                code,x=parse(r,day)
                if code in data:raise ValueError("DUPLICATE_SECURITY_ACROSS_PAGES")
                data[code]=x
            pages.append({"page":page,"count":len(rows),"sha256":sha,
                          "declared_total":total,"declared_page_count":page_count})
            print("SSE_MARGIN_PAGE",day,page,len(rows),"total",total,flush=True)
            if page>=page_count:
                if len(data)!=total:raise ValueError("PAGINATION_TOTAL_NOT_EXHAUSTIVE")
                status="SOURCE_PAGINATION_EXHAUSTIVE"
                break
    except (OSError,ValueError,TypeError,KeyError) as e:
        status="REQUEST_OR_SCHEMA_INCOMPLETE"
        error={"type":type(e).__name__,"message":str(e)[:130]}
    else:error=None
    result={"date":day,"status":status,"unique_securities":len(data),
            "declared_total":expected,"pages":pages,
            "selected_codes":{k:data[k] for k in ("603993","600362","601609") if k in data}}
    if status!="SOURCE_PAGINATION_EXHAUSTIVE":result["failure"]=locals().get("error")
    return result,data if status=="SOURCE_PAGINATION_EXHAUSTIVE" else {}

def main():
    reports,rows=[],{}
    for d in DAYS:
        res,one=day_report(d)
        reports.append(res);rows[d]=one
    common=sorted(set(rows[DAYS[0]])&set(rows[DAYS[1]]))
    errors=[]
    for code in common:
        prev=rows[DAYS[0]][code]
        now=rows[DAYS[1]][code]
        change=Decimal(now["balance"])-Decimal(prev["balance"])
        flow=Decimal(now["buy"])-Decimal(now["repay"])
        if abs(change-flow)>Decimal(".01"):
            errors.append({"code":code,"balance_change":str(change),
                           "buys_minus_repayments":str(flow)})
    complete=all(r["status"]=="SOURCE_PAGINATION_EXHAUSTIVE" for r in reports)
    out={
      "schema":"V32_SSE_MARGIN_TWO_DAY_OFFICIAL_SOURCE_EXHAUSTIVE_V2",
      "dates":list(DAYS),"source_day_pages_complete":complete,
      "common_securities":len(common),"accounting_balance_identity_checked":len(common),
      "accounting_identity_exception_count":len(errors),
      "accounting_identity_examples":errors[:8],
      "note":"Changes in securities eligible for margin trading can alter the universe; identity may also be affected by exchange adjustments.",
      "days":reports,
      "all_A_share_stocks_covered":False,
      "historical_initial_publication_timestamp_certified":False,
      "post_event_stock_returns_read":False,
      "alpha_validated":False,"trade_authorized":False}
    Path("/tmp/v32_sse_margin_source_two_day.json").write_text(
      json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("V32_SSE_MARGIN_PROBE",json.dumps({
      "status":[r["status"] for r in reports],
      "unique":[r["unique_securities"] for r in reports],
      "common":len(common),"balance_check_exceptions":len(errors),
      "full_source_pages":complete,"alpha":False},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
