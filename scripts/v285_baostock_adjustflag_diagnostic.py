from __future__ import annotations
import hashlib, json
import baostock as bs

CODE="sh.603273"
START="2022-09-01"
END="2024-12-31"
FIELDS=["date","code","open","high","low","close","preclose","volume","amount","adjustflag","tradestatus"]

def sha(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def fetch(flag):
    rs=bs.query_history_k_data_plus(CODE,",".join(FIELDS),start_date=START,end_date=END,frequency="d",adjustflag=flag)
    if rs.error_code!="0": raise RuntimeError(f"QUERY:{flag}:{rs.error_code}:{rs.error_msg}")
    rows=[]
    while rs.next(): rows.append(dict(zip(FIELDS,rs.get_row_data())))
    return rows

lg=bs.login()
if lg.error_code!="0": raise RuntimeError(lg.error_msg)
try:
    out={}
    for flag in ("1","2","3"):
        rows=fetch(flag)
        prices=[{k:r[k] for k in ("date","open","high","low","close","preclose","tradestatus")} for r in rows]
        out[flag]={
            "rows":len(rows),
            "returned_flags":sorted({r["adjustflag"] for r in rows}),
            "min_date":rows[0]["date"] if rows else "",
            "max_date":rows[-1]["date"] if rows else "",
            "price_sha256":sha(prices),
            "full_sha256":sha(rows),
        }
finally:
    bs.logout()
out["comparisons"]={
    "requested_1_equals_3_price_bytes":out["1"]["price_sha256"]==out["3"]["price_sha256"],
    "requested_1_equals_2_price_bytes":out["1"]["price_sha256"]==out["2"]["price_sha256"],
}
out["factor_or_forward_return_computed"]=False
out["holdout_statistics_computed"]=False
print(json.dumps(out,ensure_ascii=False,indent=2))
