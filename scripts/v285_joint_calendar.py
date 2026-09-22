from __future__ import annotations

import hashlib
import json
from datetime import date,timedelta
from pathlib import Path

OUT=Path("v285_calendar/V2.8.5_JOINT_A_SHARE_TRADING_CALENDAR_2023_2024.json")
CLOSED={
  2023:{
    "2023-01-02",
    "2023-01-23","2023-01-24","2023-01-25","2023-01-26","2023-01-27",
    "2023-04-05",
    "2023-05-01","2023-05-02","2023-05-03",
    "2023-06-22","2023-06-23",
    "2023-09-29","2023-10-02","2023-10-03","2023-10-04","2023-10-05","2023-10-06",
  },
  2024:{
    "2024-01-01",
    "2024-02-09","2024-02-12","2024-02-13","2024-02-14","2024-02-15","2024-02-16",
    "2024-04-04","2024-04-05",
    "2024-05-01","2024-05-02","2024-05-03",
    "2024-06-10",
    "2024-09-16","2024-09-17",
    "2024-10-01","2024-10-02","2024-10-03","2024-10-04","2024-10-07",
  }
}
SOURCES={
  "SSE_2023":"https://www.sse.com.cn/disclosure/announcement/general/c/c_20221227_5714458.shtml",
  "SZSE_2023":"https://www.szse.cn/disclosure/notice/general/t20221227_598022.html",
  "SSE_2024":"https://www.sse.com.cn/disclosure/announcement/general/c/c_20231226_5733939.shtml",
  "SZSE_2024":"https://www.szse.cn/disclosure/notice/t20231226_605108.html",
}

def trading_days(y:int)->list[str]:
    d=date(y,1,1); out=[]
    while d.year==y:
        ds=d.isoformat()
        if d.weekday()<5 and ds not in CLOSED[y]:
            out.append(ds)
        d+=timedelta(days=1)
    return out

def stable_sha(obj)->str:
    return hashlib.sha256(
        json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()

def main():
    d23=trading_days(2023); d24=trading_days(2024)
    if len(d23)!=242 or len(d24)!=242:
        raise RuntimeError(f"CALENDAR_COUNT_MISMATCH:{len(d23)}:{len(d24)}")
    all_days=d23+d24
    obj={
      "schema":"AI_CORE_EVID_V2_8_5_JOINT_A_SHARE_TRADING_CALENDAR_2023_2024_V1",
      "version":"V2.8.5",
      "status":"PASS",
      "construction":"Monday-Friday minus official SSE/SZSE holiday closures; SSE and SZSE schedules agree for the frozen years.",
      "official_sources":SOURCES,
      "year_counts":{"2023":len(d23),"2024":len(d24)},
      "trading_day_count":len(all_days),
      "first_date":all_days[0],
      "last_date":all_days[-1],
      "trading_dates":all_days,
      "trading_dates_sorted_newline_sha256":hashlib.sha256(("\n".join(all_days)+"\n").encode()).hexdigest(),
    }
    obj["receipt_sha256"]=stable_sha(obj)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
      "status":"PASS",
      "year_counts":obj["year_counts"],
      "trading_day_count":obj["trading_day_count"],
      "trading_dates_sorted_newline_sha256":obj["trading_dates_sorted_newline_sha256"],
      "receipt_sha256":obj["receipt_sha256"],
    },ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
