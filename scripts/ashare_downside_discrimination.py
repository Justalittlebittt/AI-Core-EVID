"""Retrospective candidate-only downside discrimination with fixed 20-session windows."""
from __future__ import annotations
import argparse,json,math,statistics
from datetime import date
from pathlib import Path
from ashare_market_risk_descriptive import load_rows

INDICES=('000300.SH','000688.SH')
def max_drawdown(prices):
    if not prices or any(not math.isfinite(p) or p<=0 for p in prices):raise ValueError('INVALID_PRICES')
    peak=prices[0];worst=0.0
    for p in prices[1:]:
        peak=max(peak,p)
        worst=min(worst,p/peak-1)
    return worst

def study(path):
    data,digest=load_rows(Path(path))
    if set(data)!=set(INDICES):raise ValueError('INDEX_SET')
    result={'schema':'ASHARE_DOWNSIDE_DISCRIMINATION_EXPLORATORY_V1',
            'snapshot_sha256':digest,'candidate_only':True,'pit_verified':False,
            'predictive_skill_verified':False,'trading_authorized':False,
            'start_index':271,'step_sessions':20,'horizon_sessions':20,'indices':{}}
    calendars=[]
    sources=set()
    for idx in INDICES:
        rows=sorted(data[idx],key=lambda x:x[0])
        dates=[x[0] for x in rows];prices=[x[1] for x in rows]
        if len(dates)!=len(set(dates)):raise ValueError('DUPLICATE')
        calendars.append(dates);sources.update(x[2] for x in rows)
        if len(prices)<292:raise ValueError('SHORT_HISTORY')
        logret=[math.log(prices[i]/prices[i-1]) for i in range(1,len(prices))]
        rv={t:statistics.stdev(logret[t-20:t])*math.sqrt(252) for t in range(20,len(prices))}
        windows=[]
        for t in range(271,len(prices)-20,20):
            historical=[rv[i] for i in range(20,t+1)]
            cutoff=statistics.median(historical)
            risk_high=rv[t]>cutoff
            forward_mdd=max_drawdown(prices[t:t+21])
            windows.append({'asof':dates[t].isoformat(),'end':dates[t+20].isoformat(),
                'historical_rv20_median':cutoff,'rv20_at_asof':rv[t],
                'predicted_high_volatility':risk_high,'future_max_drawdown':forward_mdd})
        high=[w['future_max_drawdown'] for w in windows if w['predicted_high_volatility']]
        low=[w['future_max_drawdown'] for w in windows if not w['predicted_high_volatility']]
        result['indices'][idx]={'windows':windows,'count':len(windows),
            'high_count':len(high),'low_count':len(low),
            'high_mean_mdd':statistics.mean(high) if high else None,
            'low_mean_mdd':statistics.mean(low) if low else None,
            'assessment':'INSUFFICIENT_NONOVERLAP_WINDOWS' if len(windows)<20 or min(len(high),len(low))<10 else 'EXPLORATORY_ONLY'}
    if calendars[0]!=calendars[1]:raise ValueError('CALENDAR_MISMATCH')
    if len(sources)!=1:raise ValueError('MIXED_SOURCES')
    result['source_id']=next(iter(sources))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--input-csv',type=Path,required=True)
    p.add_argument('--output-json',type=Path)
    args=p.parse_args()
    report=study(args.input_csv)
    output=json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+'\n'
    if args.output_json:
        if args.output_json.exists():raise FileExistsError('IMMUTABLE_OUTPUT')
        args.output_json.write_text(output,encoding='utf8')
    print(output)
