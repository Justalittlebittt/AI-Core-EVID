from __future__ import annotations
import json, baostock as bs

CODE="sh.603273"; START="2023-10-23"; END="2024-12-31"
FIELDS=["date","code","open","high","low","close","preclose","adjustflag","tradestatus"]

def fetch(flag):
    rs=bs.query_history_k_data_plus(CODE,",".join(FIELDS),start_date=START,end_date=END,frequency="d",adjustflag=flag)
    if rs.error_code!="0": raise RuntimeError(f"{flag}:{rs.error_code}:{rs.error_msg}")
    rows=[]
    while rs.next(): rows.append(dict(zip(FIELDS,rs.get_row_data())))
    return rows

lg=bs.login()
if lg.error_code!="0": raise RuntimeError(lg.error_msg)
try:
    a=fetch("1"); n=fetch("3")
finally:
    bs.logout()

by3={r["date"]:r for r in n}
groups={"1":{"count":0,"equal_unadjusted":0,"first":"","last":""},"3":{"count":0,"equal_unadjusted":0,"first":"","last":""}}
mismatches=[]
for r in a:
    flag=r["adjustflag"]; g=groups.setdefault(flag,{"count":0,"equal_unadjusted":0,"first":"","last":""})
    g["count"]+=1
    g["first"]=g["first"] or r["date"]; g["last"]=r["date"]
    q=by3[r["date"]]
    eq=all(r[k]==q[k] for k in ("open","high","low","close","preclose"))
    if eq: g["equal_unadjusted"]+=1
    elif len(mismatches)<8:
        mismatches.append({"date":r["date"],"returned_flag":flag,"post_close":r["close"],"raw_close":q["close"]})
print(json.dumps({
  "requested_post_adjust_rows":len(a),
  "returned_flag_groups":groups,
  "sample_non_equal_dates":mismatches,
  "factor_or_forward_return_computed":False,
  "holdout_statistics_computed":False
},ensure_ascii=False,indent=2))
