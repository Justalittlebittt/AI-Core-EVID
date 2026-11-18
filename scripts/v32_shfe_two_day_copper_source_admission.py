#!/usr/bin/env python3
"""Two-day exact-identity official SHFE CU2612 raw-data source admission.
Only finished 2026-11-16/17 settlement sessions; no stock prices or OOS.
"""
import hashlib,json,urllib.request
from pathlib import Path
from datetime import datetime,timezone
DAYS=("20261116","20261117")
CONTRACT="cu2612"
URL_PATTERN="https://www.shfe.com.cn/data/tradedata/future/dailydata/kx%s.dat"
HEADERS={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*",
         "Referer":"https://www.shfe.com.cn/"}
def main():
    out={"schema":"V32_SHFE_TWO_DAY_COPPER_OFFICIAL_BINARY_ADMISSION_V1",
         "captured_at_utc":datetime.now(timezone.utc).isoformat(),
         "contract":CONTRACT,"commodity":"copper","period":list(DAYS),
         "raw_source_admissible":False,"no_stock_return_read":True,
         "no_2026_122_or_e_layer_outcomes":True,"trade_authorized":False,
         "days":[]}
    for d in DAYS:
        url=URL_PATTERN%d
        item={"day":d,"source_url":url,"status":"UNAVAILABLE"}
        try:
            req=urllib.request.Request(url,headers=HEADERS)
            with urllib.request.urlopen(req,timeout=13) as response:
                raw=response.read(3_000_001)
                item["http_status"]=response.status
                item["content_type"]=response.headers.get("Content-Type","")
            item["bytes"]=len(raw)
            item["sha256"]=hashlib.sha256(raw).hexdigest()
            if len(raw)>3_000_000:raise ValueError("RESPONSE_OVER_SIZE_LIMIT")
            item["prefix"]=raw[:100].decode("utf8","replace")
            if raw.lstrip().startswith((b"<",b"<!")):
                item["status"]="HTML_CHALLENGE_NOT_EXCHANGE_JSON"
            else:
                obj=json.loads(raw)
                if not isinstance(obj,dict):raise ValueError("NOT_EXPECTED_JSON_OBJECT")
                # SHFE field naming is publicly known, but do not guess a field
                # or admit a plausible value without exact contract identity.
                item["top_level_keys"]=list(obj)[:30]
                arr=obj.get("o_curinstrument")
                if not isinstance(arr,list):
                    item["status"]="SHFE_EXPECTED_CONTRACT_ARRAY_MISSING"
                else:
                    item["total_contract_records"]=len(arr)
                    item["first_record_fields"]=list(arr[0]) if arr else []
                    item["first_record_sample"]={k:arr[0].get(k) for k in list(arr[0])[:20]} if arr else {}
                    item["copper_like_samples"]=[{k:v for k,v in x.items() if k.lower() in ("instrumentid","productid","deliverymonth","productname","variety","instrument_id")} for x in arr if isinstance(x,dict) and "cu" in str(x).lower()][:3]
                    hits=[x for x in arr if isinstance(x,dict)
                          and str(x.get("PRODUCTGROUPID","")).lower()=="cu"
                          and str(x.get("PRODUCTID","")).lower()=="cu_f"
                          and str(x.get("DELIVERYMONTH",""))=="2612"]
                    item["matching_contract_count"]=len(hits)
                    if len(hits)!=1:item["status"]="CU2612_IDENTITY_NOT_UNIQUE"
                    else:
                        rec=hits[0]
                        item["contract_keys"]=sorted(rec)
                        item["quoted_fields"]={k:rec.get(k) for k in
                          ("PRODUCTGROUPID","DELIVERYMONTH","PRODUCTID","CLOSEPRICE","SETTLEMENTPRICE",
                           "PRESETTLEMENTPRICE","VOLUME","OPENINTEREST")}
                        close=rec.get("CLOSEPRICE")
                        settlement=rec.get("SETTLEMENTPRICE")
                        if close in (None,"") or settlement in (None,""):
                            item["status"]="CU2612_PRICE_FIELDS_NOT_PRESENT"
                        else:
                            try:
                                close=float(close);settlement=float(settlement)
                                if close<=0 or settlement<=0:raise ValueError("BAD_NONPOSITIVE")
                            except (ValueError,TypeError):
                                item["status"]="NONNUMERIC_PRICE"
                            else:
                                item["status"]="SHFE_ORIGINAL_CONTRACT_DAY_FIELDS_READ"
                                item["close_cny_per_ton"]=close
                                item["settlement_cny_per_ton"]=settlement
        except (OSError,ValueError,json.JSONDecodeError,TypeError) as e:
            item["status"]="SOURCE_REQUEST_OR_SCHEMA_FAILURE"
            item["failure_type"]=type(e).__name__
            item["failure_note"]=str(e)[:150]
        out["days"].append(item)
        print("SHFE_TWO_DAY",json.dumps(item,ensure_ascii=False),flush=True)
    out["raw_source_admissible"]=all(r["status"]=="SHFE_ORIGINAL_CONTRACT_DAY_FIELDS_READ" for r in out["days"])
    print("SHFE_TWO_DAY_FINAL",json.dumps({"admissible":out["raw_source_admissible"],
           "statuses":[d["status"] for d in out["days"]],
           "no_stock_returns":True,"buy_authorized":False},ensure_ascii=False),flush=True)
    Path("/tmp/v32-shfe-two-day-admission.json").write_text(
        json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
if __name__=="__main__":main()
