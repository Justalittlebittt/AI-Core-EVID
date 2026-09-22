from __future__ import annotations
import json, math, baostock as bs

CODE="sh.603273"; START="2023-10-23"; END="2024-12-31"
FIELDS=["date","code","open","high","low","close","preclose","adjustflag","tradestatus"]
PRICE_KEYS=("open","high","low","close","preclose")

def fetch(flag):
    rs=bs.query_history_k_data_plus(CODE,",".join(FIELDS),start_date=START,end_date=END,frequency="d",adjustflag=flag)
    if rs.error_code!="0": raise RuntimeError(f"{flag}:{rs.error_code}:{rs.error_msg}")
    rows=[]
    while rs.next(): rows.append(dict(zip(FIELDS,rs.get_row_data())))
    return rows

def eq_num(a,b):
    for k in PRICE_KEYS:
        try: x=float(a[k]); y=float(b[k])
        except: return False
        if not (math.isfinite(x) and math.isfinite(y) and abs(x-y)<=1e-12*max(1.0,abs(x),abs(y))):
            return False
    return True

lg=bs.login()
if lg.error_code!="0": raise RuntimeError(lg.error_msg)
try:
    post=fetch("1"); raw=fetch("3")
finally:
    bs.logout()
byraw={r["date"]:r for r in raw}
groups={}
examples=[]
for r in post:
    f=r["adjustflag"]; q=byraw[r["date"]]
    g=groups.setdefault(f,{"count":0,"numeric_equal_raw":0,"numeric_different_raw":0,"first":"","last":""})
    g["count"]+=1; g["first"]=g["first"] or r["date"]; g["last"]=r["date"]
    if eq_num(r,q): g["numeric_equal_raw"]+=1
    else:
        g["numeric_different_raw"]+=1
        if len(examples)<8:
            examples.append({"date":r["date"],"returned_flag":f,"post_close":float(r["close"]),"raw_close":float(q["close"])})
print(json.dumps({
    "requested_adjustflag":"1",
    "row_groups":groups,
    "all_returned_flag3_rows_numerically_equal_raw":groups.get("3",{}).get("numeric_different_raw",0)==0,
    "returned_flag1_has_at_least_one_numeric_adjustment":groups.get("1",{}).get("numeric_different_raw",0)>0,
    "sample_numeric_adjustment_dates":examples,
    "factor_or_forward_return_computed":False,
    "holdout_statistics_computed":False
},ensure_ascii=False,indent=2))
