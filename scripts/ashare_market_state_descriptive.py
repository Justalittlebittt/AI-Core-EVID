"""Descriptive market states using existing validated RV20/RV60 machinery; no trading labels."""
import argparse,csv,hashlib,json,math,statistics
from datetime import date
from pathlib import Path
from ashare_market_risk_descriptive import evaluate as risk_evaluate,load_rows

def evaluate(path,as_of):
    base=risk_evaluate(path,as_of)
    groups,digest=load_rows(path)
    if set(groups)!={'000300.SH','000688.SH'}:raise ValueError('MISSING_INDEX')
    dates=[];sources=set();out={}
    for idx,rows in sorted(groups.items()):
        used=sorted((r for r in rows if r[0]<=as_of),key=lambda r:r[0])
        if len(used)<272:raise ValueError('INSUFFICIENT_HISTORY')
        dates.append([r[0] for r in used]);sources.update(r[2] for r in used)
        p=[r[1] for r in used]
        def ret(n):return p[-1]/p[-1-n]-1
        peak=p[-60];worst=0.0
        for v in p[-60:]:peak=max(peak,v);worst=min(worst,v/peak-1)
        descriptive=base['indices'][idx]
        if descriptive['status']!='DESCRIPTIVE_ONLY':raise ValueError('RISK_BLOCK')
        out[idx]={'last_date':used[-1][0].isoformat(),'close':p[-1],
            'rv20_annualized':descriptive['rv20_annualized'],
            'rv60_annualized':descriptive['rv60_annualized'],
            'rv20_percentile_252':descriptive['rv20_percentile_252'],
            'return_20_sessions':ret(20),'return_60_sessions':ret(60),
            'max_drawdown_60_closes':worst,
            'distance_from_60_close_mean':p[-1]/statistics.mean(p[-60:])-1}
    if dates[0]!=dates[1]:raise ValueError('INDEX_CALENDAR_MISMATCH')
    if len(sources)!=1:raise ValueError('MIXED_SOURCE_BLOCK')
    return {'schema':'AI_CORE_EVID_ASHARE_MARKET_STATE_DESCRIPTIVE_V1',
        'as_of':as_of.isoformat(),'input_sha256':digest,'source_id':next(iter(sources)),
        'status':'DESCRIPTIVE_ONLY','state_label':'UNASSIGNED_NO_EMPIRICAL_VALIDATION',
        'no_trading_signal':True,'historical_PIT_verified':False,
        'predictive_skill_verified':False,'trading_authorized':False,
        'indices':out}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input-csv',type=Path,required=True);p.add_argument('--as-of',required=True);p.add_argument('--output-json',type=Path)
    a=p.parse_args();result=json.dumps(evaluate(a.input_csv,date.fromisoformat(a.as_of)),indent=2,allow_nan=False)+'\n'
    if a.output_json:
        if a.output_json.exists():raise FileExistsError('IMMUTABLE_OUTPUT')
        a.output_json.write_text(result)
    print(result)
