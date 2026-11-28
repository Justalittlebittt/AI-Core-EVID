"""Development-only end-of-day descriptive inputs; never a trading or OOS gate."""
import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from v285_joint_calendar import trading_days

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "research/v4_data_foundation_20261126"
def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))

def blob_sha(path):
    b = path.read_bytes()
    return hashlib.sha1(("blob %d\0" % len(b)).encode() + b).hexdigest()

def require(ok, message):
    if not ok:
        raise ValueError(message)

def load(purpose="DESCRIPTIVE_DEVELOPMENT", root=ROOT):
    require(purpose == "DESCRIPTIVE_DEVELOPMENT", "No PIT-certified, independent OOS or live decision permission")
    base = root / BASE.relative_to(ROOT)
    m = read_json(base / "DATASET_MANIFEST.json")
    roster = read_json(root / m["roster_source"])["sample_years"]
    cal = {str(y): trading_days(y) for y in (2023, 2024)}
    stocks, benchmarks, gaps, events = {}, {}, {}, {}
    for entry in m["panel_files"]:
        path = root / entry["path"]
        require(blob_sha(path) == entry["git_blob_sha"], f"source mismatch: {path}")
        with path.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                y, sid, d = (r[k] for k in ("frame_year", "security_id", "session"))
                require(d in cal[y], f"off-calendar {sid} {d}")
                require(r["adjustment"] == "UNADJUSTED_FQT0", "unexpected adjustment")
                o,c,h,l,v,a = (float(r[k]) for k in ("open_cny_or_index_points","close_cny_or_index_points","high_cny_or_index_points","low_cny_or_index_points","volume_vendor_units","turnover_vendor_units"))
                require(all(map(math.isfinite,(o,c,h,l,v,a))) and 0 < l <= min(o,c) <= max(o,c) <= h and v > 0 and a >= 0, f"invalid bar {sid} {d}")
                require(r["series_type"] in ("STOCK","BENCHMARK_PRICE"), "unknown series")
                target = stocks if r["series_type"] == "STOCK" else benchmarks
                key = (y,sid,d) if target is stocks else (y,d)
                require(key not in target, f"duplicate {key}")
                target[key] = (o,c,h,l,v,a,entry["path"])
    require(set(benchmarks)=={(y,d) for y in cal for d in cal[y]}, "benchmark/calendar mismatch")
    with (base/"GAP_STATUS.csv").open(newline="",encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = tuple(r[k] for k in ("frame_year","security_id","session"))
            require(key not in gaps and r["status"] in ("UNRESOLVED_NO_BAR","CONFIRMED_SUSPENSION","POST_DELISTING"), "bad gap")
            gaps[key] = r["status"]
    for y in cal:
        path = base / f"ACTION_NORMALIZED_{y}.json"
        for e in read_json(path)["events_list"]:
            key = (y,e["id"],e["ex_date"])
            require(key in stocks and e["structural_status"]=="VENDOR_TERMS_MATCH", "action mismatch")
            events.setdefault(key,[]).append(e)
    expected = {(y,sid,d) for y in cal for sid in roster[y]["ids"] for d in cal[y]}
    require(not set(stocks)&set(gaps) and set(stocks)|set(gaps)==expected, "roster coverage mismatch")
    require(len(stocks)==m["stock_rows"] and len(benchmarks)==m["benchmark_rows"], "manifest counts")
    require(Counter(gaps.values())==m["gap_counts"], "gap count mismatch")
    require(sum(map(len,events.values()))==m["corporate_action_layer"]["event_count"], "action count mismatch")
    for y in sorted(cal):
        for sid in sorted(roster[y]["ids"]):
            for d in cal[y]:
                k=(y,sid,d)
                q=stocks.get(k)
                row=dict(frame_year=y,security_id=sid,session=d,observation_status="OBSERVED_BAR" if q else gaps[k],research_use=purpose,decision_time="AFTER_SESSION_CLOSE_ASSUMED",vintage_status="RETROSPECTIVE_NOT_PIT_CERTIFIED",execution_status="UNKNOWN",membership_status="FIXED_HISTORICAL_ROSTER_NOT_DAILY_PIT_CERTIFIED",independent_oos=False,action_status="VENDOR_EVENT_UNCERTIFIED_VINTAGE" if k in events else "NO_RECORDED_EVENT_NOT_CERTIFIED_ZERO",economic_return=None,raw_open=None,raw_close=None,intraday_return=None,range_over_open=None,volume_vendor_units=None,turnover_vendor_units=None,source_path=None)
                if q:
                    o,c,h,l,v,a,src=q
                    row.update(raw_open=o,raw_close=c,intraday_return=c/o-1,range_over_open=(h-l)/o,volume_vendor_units=v,turnover_vendor_units=a,source_path=src)
                yield row

def screen(session, root=ROOT):
    """Unranked historical descriptive candidates only; no buy or future labels."""
    return [r for r in load(root=root) if r["session"]==session and r["observation_status"]=="OBSERVED_BAR"]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--session")
    p.add_argument("--purpose",default="DESCRIPTIVE_DEVELOPMENT")
    a=p.parse_args()
    rows=list(load(a.purpose))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(json.dumps({"rows":len(rows),"status":dict(Counter(r["observation_status"] for r in rows)),"screen_count":len(screen(a.session)) if a.session else None,"independent_oos":False,"economic_returns":False,"purpose":a.purpose}))

if __name__=="__main__":
    main()
