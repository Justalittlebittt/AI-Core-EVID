"""Outcome-blind feature buckets versus subsequent 20-session outcomes.

EXPLORATORY ONLY. This does not select predictive thresholds or claim alpha.
Uses non-overlapping evaluation windows and makes no PIT / trading claims.
"""
from __future__ import annotations
import argparse,csv,json,math,statistics
from datetime import date
from pathlib import Path
from ashare_market_risk_descriptive import load_rows

INDEXES=("000300.SH","000688.SH")
H=20
MIN_TRAIN=272

def study(path:Path,split:date=date(2026,4,1))->dict:
    grouped,digest=load_rows(path)
    if set(grouped)!=set(INDEXES):raise ValueError("REQUIRE_TWO_INDICES")
    arrays={}
    for idx in INDEXES:
        arr=sorted(grouped[idx],key=lambda row:row[0])
        if len({x[0] for x in arr})!=len(arr):raise ValueError("DUPLICATE_DATES")
        arrays[idx]=arr
    if [r[0] for r in arrays[INDEXES[0]]]!=[r[0] for r in arrays[INDEXES[1]]]:
        raise ValueError("CROSS_INDEX_CALENDAR_DISAGREEMENT")
    sources={r[2] for idx in INDEXES for r in arrays[idx]}
    if len(sources)!=1:raise ValueError("MIXED_SOURCE_BLOCK")
    output={"schema":"AI_CORE_EVID_ASHARE_STATE_OUTCOME_EXPLORATION_V1",
            "input_sha256":digest,"source_id":next(iter(sources)),"split_date":split.isoformat(),
            "forecast_horizon_sessions":H,"split_status":"RETROSPECTIVE_NOT_PREREGISTERED",
            "candidate_only":True,"PIT_verified":False,"predictive_efficacy_verified":False,
            "trade_authorized":False,"indices":{}}
    for idx in INDEXES:
        arr=arrays[idx];ds=[r[0] for r in arr];close=[r[1] for r in arr]
        start=next((i for i in range(MIN_TRAIN-1,len(close)-H) if ds[i]>=split),None)
        windows=[]
        if start is not None:
            for i in range(start,len(close)-H,H):
                # All feature data end at i; all outcome returns start after i.
                past=[math.log(close[j]/close[j-1]) for j in range(i-19,i+1)]
                forward=[math.log(close[j]/close[j-1]) for j in range(i+1,i+H+1)]
                prev=close[i-20]
                windows.append({"asof":ds[i].isoformat(),"outcome_end":ds[i+H].isoformat(),
                    "rv20_at_asof":statistics.stdev(past)*math.sqrt(252),
                    "past_20_return":close[i]/prev-1,
                    "future_20_return":close[i+H]/close[i]-1,
                    "future_rv20":statistics.stdev(forward)*math.sqrt(252)})
        # Never optimize/select thresholds on held-out data.
        output["indices"][idx]={"total_closes":len(close),"nonoverlap_windows":len(windows),
            "assessment":"INSUFFICIENT_NONOVERLAP_WINDOWS" if len(windows)<20 else "EXPLORATORY_NOT_VALIDATED",
            "windows":windows}
    return output

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--input-csv",type=Path,required=True)
    p.add_argument("--split",default="2026-04-01")
    p.add_argument("--output-json",type=Path)
    a=p.parse_args()
    result=study(a.input_csv,date.fromisoformat(a.split))
    text=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    if a.output_json:
        if a.output_json.exists():raise FileExistsError("IMMUTABLE_OUTPUT")
        a.output_json.write_text(text,encoding="utf8")
    print(text)
