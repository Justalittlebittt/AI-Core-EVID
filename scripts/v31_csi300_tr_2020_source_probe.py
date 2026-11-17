#!/usr/bin/env python3
"""2020 ONLY CSI official H00300 total-return index source discovery.

Never opens preregistered 2021/2022 evaluation-period benchmark or stocks.
Endpoint read is exploratory source admission, not trading authorization.
"""
import argparse
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

URL = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
PARAMS = {"indexCode": "H00300", "startDate": "20201102", "endDate": "20201215"}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AShareSourceCheck/1.0)", "Accept": "application/json"}
def inspect(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return {"status":"MISSING_EXPECTED_JSON_DATA_LIST","count":0}
    items = payload["data"]
    accepted = []
    for row in items:
        if not isinstance(row, dict):
            return {"status":"UNEXPECTED_ROW_SHAPE","count":len(items)}
        day = str(row.get("tradeDate", ""))
        idx = str(row.get("indexCode", ""))
        if idx != "H00300":
            return {"status":"INDEX_IDENTITY_MISMATCH","count":len(items),"observed_index_code":idx}
        digits = day.replace("-", "")
        if len(digits) != 8 or not digits.isdigit() or not ("20201102" <= digits <= "20201215"):
            return {"status":"DATE_OUTSIDE_SOURCE_ADMISSION_WINDOW","count":len(items)}
        try:
            close = float(row["close"])
        except (ValueError, KeyError, TypeError):
            return {"status":"INVALID_CLOSE_POINT","count":len(items)}
        if not (close > 0 and close < 1e10):
            return {"status":"NONPOSITIVE_INDEX_LEVEL","count":len(items)}
        accepted.append((day,close))
    if not accepted:
        return {"status":"OFFICIAL_ENDPOINT_NO_2020_DATA","count":0}
    if len(set(day for day,_ in accepted))!=len(accepted):
        return {"status":"DUPLICATE_OFFICIAL_DATE","count":len(items)}
    return {"status":"SOURCE_2020_TOTAL_RETURN_IDENTITY_PASS","count":len(accepted),
            "first_day":min(day for day,_ in accepted),"last_day":max(day for day,_ in accepted)}
def main():
    a=argparse.ArgumentParser()
    a.add_argument("--output",type=Path,required=True)
    args=a.parse_args()
    url=URL+"?"+urllib.parse.urlencode(PARAMS)
    result={"schema":"V31_CSI300_TR_OFFICIAL_2020_SOURCE_ADMISSION_V1",
            "requested_index":"H00300","requested_2020_only":True,
            "preregistered_evaluation_2021_2022_not_accessed":True,
            "stock_price_outcomes_not_accessed":True,"trade_authorized":False,
            "official_endpoint":URL,"query":PARAMS}
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers=HEADERS),timeout=25) as response:
            raw=response.read(3*1024*1024+1)
            http_code=response.status
        result["http_status"]=http_code
        if len(raw)>3*1024*1024:
            result["status"]="OFFICIAL_RESPONSE_TOO_LARGE"
        else:
            result["response_sha256"]=hashlib.sha256(raw).hexdigest()
            result.update(inspect(json.loads(raw)))
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        result["status"]="OFFICIAL_ENDPOINT_UNAVAILABLE"
        result["failure_type"]=type(exc).__name__
        result["failure_detail"]=str(exc)[:250]
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("CSI300_TR_2020_SOURCE_ADMISSION="+json.dumps(result,ensure_ascii=False))
if __name__=="__main__":
    main()
