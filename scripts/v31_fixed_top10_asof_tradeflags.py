#!/usr/bin/env python3
"""Check fixed 2021/2022 growth picks' historical as-of trading flags, without returns.

Source: BaoStock historical daily isST / tradestatus only, at Nov 15 decision date.
Never requests any price, volume, turnover or post-decision session. Not a fill check.
"""
import argparse
import hashlib
import json
from pathlib import Path
import baostock as bs

RECEIPT = Path("research/V3.1_2021_2022_FIXED_TOP10_SOURCE_ONLY_RECEIPT_20261117.json")
DATES = {2021: "2021-11-15", 2022: "2022-11-15"}
FIELDS = "date,code,tradestatus,isST"


def get_records(result):
    if result.error_code != "0":
        raise ValueError("BAOSTOCK_QUERY_ERROR:" + str(result.error_msg))
    rows = []
    while result.next():
        vals = result.get_row_data()
        rows.append(dict(zip(result.fields, vals)))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = RECEIPT.read_bytes()
    picked = json.loads(raw)
    if picked["schema"] != "V31_FIXED_Q3_EVALUATION_CANDIDATE_SOURCE_ONLY_RECEIPT_V1":
        raise ValueError("WRONG_FROZEN_CANDIDATE_RECEIPT")
    if picked["limits"]["prices_or_outcomes_read"] is not False or picked["limits"]["trade_authorized"] is not False:
        raise ValueError("UNAUTHORIZED_RECEIPT_STATUS")
    session = bs.login()
    if session.error_code != "0":
        raise ValueError("BAOSTOCK_LOGIN_ERROR:" + str(session.error_msg))
    rows = []
    try:
        for year, decision_day in DATES.items():
            candidates = picked["year_" + str(year)]
            if len(candidates) != 10:
                raise ValueError("FROZEN_TOP10_COUNT_CHANGED")
            for rank, item in enumerate(candidates, 1):
                symbol = item[0]
                code = symbol[-2:].lower() + "." + symbol[:6]
                historical = get_records(bs.query_history_k_data_plus(
                    code, FIELDS, start_date=decision_day, end_date=decision_day,
                    frequency="d", adjustflag="3"))
                if len(historical) != 1:
                    status = "UNKNOWN_MISSING_OR_MULTIPLE_BARS"
                    flag, trade = None, None
                elif historical[0]["date"] != decision_day or historical[0]["code"] != code:
                    raise ValueError("HISTORICAL_CODE_DATE_IDENTITY_MISMATCH:" + symbol)
                else:
                    trade = historical[0].get("tradestatus")
                    flag = historical[0].get("isST")
                    status = ("PROVISIONALLY_NON_ST_TRADING" if trade == "1" and flag == "0"
                              else "RISK_FLAG_OR_SUSPENSION" if trade in ("0","1") and flag in ("0","1")
                              else "UNKNOWN_VENDOR_STATUS")
                rows.append({"year": year, "rank": rank, "security_id": symbol,
                             "decision_date": decision_day,
                             "provider_tradestatus": trade, "provider_isST": flag,
                             "status": status})
    finally:
        bs.logout()
    by_year = {}
    for year in DATES:
        year_rows = [r for r in rows if r["year"] == year]
        by_year[str(year)] = {
            "total": len(year_rows),
            "provisionally_non_st_trading": sum(r["status"] == "PROVISIONALLY_NON_ST_TRADING" for r in year_rows),
            "risk_or_suspension": sum(r["status"] == "RISK_FLAG_OR_SUSPENSION" for r in year_rows),
            "unknown": sum(r["status"].startswith("UNKNOWN") for r in year_rows),
        }
    output = {
        "schema": "V31_FIXED_TOP10_DECISION_DAY_ST_TRADING_STATUS_PREFLIGHT_V1",
        "candidate_receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "provider": "BaoStock historical unadjusted daily isST/tradestatus at decision date",
        "requested_fields": FIELDS.split(","),
        "provider_not_independently_certified_as_published": True,
        "post_decision_dates_requested": False,
        "prices_or_outcomes_requested": False,
        "entry_open_fill_eligibility_certified": False,
        "original_issuer_finance_for_all_selected_certified": False,
        "trade_authorized": False,
        "by_year": by_year,
        "rows": rows,
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("HISTORICAL_ASOF_TRADING_FLAG_ONLY=" + json.dumps({"by_year": by_year, "flags": [
        {"year":r["year"], "security_id":r["security_id"],"status":r["status"]}
        for r in rows if r["status"] != "PROVISIONALLY_NON_ST_TRADING"],
        "prices_or_outcomes_requested":False, "trade_authorized":False}, ensure_ascii=False))

if __name__ == "__main__":
    main()
