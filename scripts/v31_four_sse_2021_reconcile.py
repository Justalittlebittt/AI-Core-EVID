#!/usr/bin/env python3
"""Bounded independent Q3 text-reconciliation for exactly four frozen 2021 SSE picks.

Uses contemporaneous disclosure text mirrored by Sina, NOT issuer original PDF.
Separately probes one already discovered official SSE original PDF by literal URL.
Reads NO prices, returns, later evaluation-year values, benchmark or frozen E folds.
"""
import argparse
import hashlib
import html
import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

RECEIPT=Path("research/V3.1_2021_2022_FIXED_TOP10_SOURCE_ONLY_RECEIPT_20261117.json")
SOURCES={
 "600746.SH":"https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=7599890&stockid=600746",
 "603260.SH":"https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=7609651&stockid=603260",
 "603392.SH":"https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=7614298&stockid=603392",
 "600309.SH":"https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=7594015&stockid=600309",
}
OFFICIAL_SSE_PDF_603392="https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2021-10-28/603392_20211028_1_CwDXAYXG.pdf"

class Text(HTMLParser):
    def __init__(self):
        super().__init__();self.parts=[]
    def handle_data(self,data):self.parts.append(data)
    def plain(self):return " ".join(self.parts)
def get(url,limit):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"text/html,application/pdf,*/*"})
    with urllib.request.urlopen(req,timeout=18) as h:
        raw=h.read(limit+1)
    if len(raw)>limit:raise ValueError("RESPONSE_LIMIT_EXCEEDED")
    return raw
def reconcile(symbol,day,growth,roe,profit):
    url=SOURCES[symbol]
    out={"security_id":symbol,"2021_vendor_notice":day,"source_url":url,
         "source_class":"THIRD_PARTY_MIRROR_OF_DISCLOSURE_NOT_ORIGINAL_ISSUER_PDF",
         "matches":0,"required":3,"status":"SOURCE_UNVERIFIED"}
    try:
        raw=get(url,2_000_000)
        out["html_sha256"]=hashlib.sha256(raw).hexdigest()
        s=Text();s.feed(raw.decode("utf-8","replace"))
        text=html.unescape(s.plain())
        # The current site is known to have either UTF-8 or legacy GBK encodings.
        if "主要财务数据" not in text:
            s=Text();s.feed(raw.decode("gb18030","replace"))
            text=html.unescape(s.plain())
        text=re.sub(r"\s+"," ",text)
        if symbol[:6] not in text or "2021年第三季度报告" not in text:
            raise ValueError("REPORT_ISSUER_YEAR_TITLE_MISMATCH")
        if "公告日期:2021-10-" not in text and "公告日期: 2021-10-" not in text:
            raise ValueError("DATE_NOT_FOUND")
        published=re.search(r"公告日期:\s*(2021-10-\d\d)",text)
        if not published or published.group(1).replace("-","")!=str(day):
            raise ValueError("VENDOR_DISCLOSURE_DAY_MISMATCH")
        pos=text.find("主要会计数据和财务指标")
        start=text.find("营业收入",pos)
        stop=text.find("本报告期末",start)
        if pos<0 or start<0 or stop<0 or stop-start>2000:
            raise ValueError("UNSAFE_Q3_TABLE_BOUNDARY")
        segment=text[start:stop].replace(",","")
        # Bind expected values to their respective accounting labels, not anywhere in page.
        keys=(
          ("or_yoy",r"营业收入\s+[^\n]{0,120}?"+re.escape(f"{growth:.2f}"),f"{growth:.2f}"),
          ("profit_dedt",r"归属于上市公司股东的扣除非经常性损益(?:后)?的净利润\s+[^\n]{0,130}?"+re.escape(f"{profit:.2f}"),f"{profit:.2f}"),
          ("roe_waa",r"加权平均净资产收益率（%）\s+[^\n]{0,120}?"+re.escape(f"{roe:g}"),f"{roe:g}")
        )
        matches={}
        for field,pattern,value in keys:
            matches[field]=bool(re.search(pattern,segment))
        out["field_matches"]=matches
        out["matches"]=sum(matches.values())
        out["status"]="MIRRORED_TEXT_3_FIELDS_MATCH" if out["matches"]==3 else "MIRRORED_TEXT_FIELD_MISMATCH"
    except (OSError,UnicodeError,ValueError) as exc:
        out["status"]="SOURCE_QUERY_OR_IDENTITY_ERROR"
        out["error_type"]=type(exc).__name__
        out["error_detail"]=str(exc)[:140]
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);args=p.parse_args()
    raw=RECEIPT.read_bytes();frozen=json.loads(raw)
    lookup={x[0]:x for x in frozen["year_2021"]}
    if set(SOURCES)-set(lookup):raise ValueError("FROZEN_SOURCE_MEMBERSHIP_CHANGED")
    rows=[reconcile(code,*lookup[code][1:]) for code in SOURCES]
    pdf={"security_id":"603392.SH","url":OFFICIAL_SSE_PDF_603392,"status":"NOT_TESTED"}
    try:
        binary=get(OFFICIAL_SSE_PDF_603392,8_000_000)
        pdf["size_bytes"]=len(binary)
        pdf["sha256"]=hashlib.sha256(binary).hexdigest()
        pdf["status"]="OFFICIAL_SSE_PDF_BYTES_RETRIEVED_NOT_CONTENT_AUTHENTICATED" if binary.startswith(b"%PDF-") else "RESPONSE_NOT_PDF"
    except (OSError,ValueError) as exc:
        pdf["status"]="OFFICIAL_PDF_FETCH_UNAVAILABLE"
        pdf["error_type"]=type(exc).__name__
    result={"schema":"V31_FOUR_SSE_2021_SOURCE_TEXT_RECONCILIATION_V1",
            "fixed_receipt_sha256":hashlib.sha256(raw).hexdigest(),
            "rows":rows,"sse_original_pdf_probe":pdf,
            "mirror_text_3of3_count":sum(r["matches"]==3 for r in rows),
            "source_status":"MIRRORED_TEXT_CHECK_ONLY",
            "all_four_exchange_pdf_contents_authenticated":False,
            "outcomes_or_prices_read":False,"trade_authorized":False}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FOUR_SSE_Q3_SOURCE_STATUS="+json.dumps({"counts":[(r["security_id"],r["status"],r["matches"]) for r in rows],
          "sse_pdf":pdf["status"],"outcomes_or_prices_read":False},ensure_ascii=False))
if __name__=="__main__":main()
