from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CAL=Path("evidence/V2.7.32_JOINT_A_SHARE_TRADING_CALENDAR_2026.json")
TZ=ZoneInfo("Asia/Shanghai")

def trading_days()->list[date]:
    obj=json.loads(CAL.read_text(encoding="utf-8"))
    return [date.fromisoformat(x["date"]) for x in obj["dates"] if x["is_joint_a_share_trading_day"]]

def effective_date(observed_at:str)->date:
    dt=datetime.fromisoformat(observed_at.replace("Z","+00:00")).astimezone(TZ)
    o=dt.date()
    for d in trading_days():
        if d>o:
            return d
    raise RuntimeError("EFFECTIVE_DATE_OUTSIDE_FROZEN_CALENDAR")

def self_test():
    tests=[]
    def ck(n,ts,expected):
        got=effective_date(ts).isoformat()
        tests.append({"name":n,"pass":got==expected,"expected":expected,"actual":got})
    ck("T01_normal_trading_day","2026-09-22T01:00:00Z","2026-09-23")
    ck("T02_same_day_late_commit_still_next_day","2026-09-22T12:00:00Z","2026-09-23")
    ck("T03_pre_mid_autumn","2026-09-24T02:00:00Z","2026-09-28")
    ck("T04_holiday_observation","2026-09-25T04:00:00Z","2026-09-28")
    ck("T05_weekend_observation","2026-09-27T04:00:00Z","2026-09-28")
    ck("T06_pre_national_day","2026-09-30T02:00:00Z","2026-10-08")
    result={"schema":"AI_CORE_EVID_V2_8_4_E_LAYER_EFFECTIVE_DATE_SELFTEST_V1",
            "tests":tests,"passed":sum(x["pass"] for x in tests),"total":len(tests),
            "all_pass":all(x["pass"] for x in tests)}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]: raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("command",choices=["self-test","resolve"])
    ap.add_argument("--observed-at")
    a=ap.parse_args()
    if a.command=="self-test": self_test()
    else:
        if not a.observed_at: raise SystemExit("--observed-at required")
        print(json.dumps({"effective_signal_date":effective_date(a.observed_at).isoformat()}))

if __name__=="__main__":
    main()
