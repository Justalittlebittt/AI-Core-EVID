from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import tarfile
import tempfile
import time as time_module
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASELINE = Path("evidence/V2.7.31_FORWARD_CERTIFIED_UNIVERSE.csv")
BASELINE_SHA = "8815cd4ff5fb1f82e7c49b2a142ceb8e12138a4068d7a21c8ae144b57cc3f92d"
INTERVALS = Path("evidence/V2.8.1_PIT_MEMBERSHIP_INTERVALS.csv")
INTERVALS_SHA = "52087fa1e68577fae214f8fa18f1b20a0b30f41b6b6bf5592327c25c2800cfc1"
CAL2026 = Path("evidence/V2.7.32_JOINT_A_SHARE_TRADING_CALENDAR_2026.json")
FIRST_SIGNAL_DATE = date(2026, 9, 22)
TZ = ZoneInfo("Asia/Shanghai")
CODE_RE = re.compile(r"^\d{6}$")

SSE_ENDPOINT = "https://query.sse.com.cn/sseQuery/commonQuery.do"
SSE_REFERER = "https://www.sse.com.cn/assortment/stock/list/share/"
SZSE_ENDPOINT = "https://www.szse.cn/api/report/ShowReport"
SZSE_REFERER = "https://www.szse.cn/market/product/stock/list/index.html"

def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()

def stable_json_sha(obj) -> str:
    b = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(b).hexdigest()

def load_calendar() -> set[date]:
    obj = json.loads(CAL2026.read_text(encoding="utf-8"))
    return {date.fromisoformat(x["date"]) for x in obj["dates"] if x["is_joint_a_share_trading_day"]}

def parse_date(v) -> date:
    s = str(v or "").strip()
    if re.fullmatch(r"\d{8}", s):
        s = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return date.fromisoformat(s)

def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})

def load_baseline() -> pd.DataFrame:
    if sha_file(BASELINE) != BASELINE_SHA:
        raise RuntimeError("baseline certified universe SHA mismatch")
    x = pd.read_csv(BASELINE, dtype=str).fillna("")
    req = {"canonical_security_id", "exchange", "security_code", "security_short_name", "official_list_date"}
    if not req.issubset(x.columns):
        raise RuntimeError(f"baseline columns missing {req-set(x.columns)}")
    return x[list(req)].copy()

def load_intervals() -> dict[str, str]:
    if sha_file(INTERVALS) != INTERVALS_SHA:
        raise RuntimeError("historical PIT intervals SHA mismatch")
    x = pd.read_csv(INTERVALS, dtype=str).fillna("")
    return dict(zip(x["canonical_security_id"], x["official_delist_date"]))

def latest_previous_universe(out_root: Path, d: date) -> tuple[str, pd.DataFrame]:
    candidates = []
    if out_root.exists():
        for p in out_root.glob("*_PIT_DATE_AUTHORITY.json"):
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
                sd = date.fromisoformat(obj["signal_date"])
                if sd < d and obj.get("status") == "PASS":
                    snap = Path(obj["universe_snapshot_file"])
                    if snap.exists() and sha_file(snap) == obj["universe_snapshot_sha256"]:
                        candidates.append((sd, p, snap))
            except Exception:
                continue
    if candidates:
        sd, p, snap = max(candidates, key=lambda x: x[0])
        return sd.isoformat(), pd.read_csv(snap, dtype=str).fillna("")
    return "V2.7.31_BASELINE", load_baseline()

def decode_json_or_jsonp(b: bytes):
    s = b.decode("utf-8", "ignore").strip()
    try:
        return json.loads(s)
    except Exception:
        m = re.match(r"^[A-Za-z_$][\w$]*\((.*)\)\s*;?\s*$", s, re.S)
        if not m:
            raise
        return json.loads(m.group(1))

def fetch_sse(d: date, raw: Path) -> tuple[pd.DataFrame, list[dict]]:
    raw.mkdir(parents=True, exist_ok=True)
    retry = Retry(
        total=3, connect=3, read=3, status=2,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    sess = requests.Session()
    sess.mount("https://", HTTPAdapter(max_retries=retry))
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
        "Referer": SSE_REFERER,
        "Accept": "*/*",
    })
    try:
        sess.get(SSE_REFERER, timeout=20)
    except requests.RequestException:
        pass
    rows = []
    captures = []
    for stock_type, board in (("1", "SSE_MAIN_A"), ("8", "SSE_STAR")):
        base = {
            "jsonCallBack": f"jsonpCallback283{stock_type}",
            "STOCK_TYPE": stock_type,
            "REG_PROVINCE": "",
            "CSRC_CODE": "",
            "STOCK_CODE": "",
            "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
            "COMPANY_STATUS": "2,4,5,7,8",
            "type": "inParams",
            "isPagination": "true",
            "pageHelp.cacheSize": "1",
            "pageHelp.pageSize": "100",
            "_": str(int(time_module.time() * 1000)),
        }
        q = {**base, "pageHelp.beginPage": "1", "pageHelp.pageNo": "1", "pageHelp.endPage": "1"}
        first = sess.get(SSE_ENDPOINT, params=q, timeout=30)
        first.raise_for_status()
        obj = decode_json_or_jsonp(first.content)
        ph = obj.get("pageHelp", {}) if isinstance(obj, dict) else {}
        total = int(ph.get("total") or 0)
        page_size = int(ph.get("pageSize") or 100)
        if total <= 0 or page_size <= 0:
            raise RuntimeError(f"SSE {board}: invalid total/page_size {total}/{page_size}")
        pages = max(1, math.ceil(total / page_size))
        for n in range(1, pages + 1):
            qq = {**base, "pageHelp.beginPage": str(n), "pageHelp.pageNo": str(n), "pageHelp.endPage": str(n)}
            r = first if n == 1 else sess.get(SSE_ENDPOINT, params=qq, timeout=30)
            r.raise_for_status()
            p = raw / f"{board}_{n:03d}.json"
            p.write_bytes(r.content)
            captures.append({"file": str(p), "sha256": sha_file(p), "bytes": p.stat().st_size, "url": r.url})
            o = decode_json_or_jsonp(r.content)
            block = o.get("result") or (o.get("pageHelp") or {}).get("data") or []
            for x in block:
                code = str(x.get("A_STOCK_CODE") or "").strip()
                if not CODE_RE.fullmatch(code):
                    continue
                try:
                    ld = parse_date(x.get("LIST_DATE"))
                except Exception:
                    continue
                if ld > d:
                    continue
                rows.append({
                    "canonical_security_id": f"SSE:{code}",
                    "exchange": "SSE",
                    "security_code": code,
                    "security_short_name": str(x.get("COMPANY_ABBR") or "").strip(),
                    "official_list_date": ld.isoformat(),
                    "official_source": board,
                })
    df = pd.DataFrame(rows).drop_duplicates("canonical_security_id")
    if len(df) <= 1000:
        raise RuntimeError(f"SSE normalized count implausible {len(df)}")
    return df, captures

def fetch_szse(d: date, raw: Path) -> tuple[pd.DataFrame, list[dict]]:
    raw.mkdir(parents=True, exist_ok=True)
    retry = Retry(
        total=4, connect=4, read=4, status=4,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    sess = requests.Session()
    sess.mount("https://", HTTPAdapter(max_retries=retry))
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
        "Referer": SZSE_REFERER,
        "Accept": "*/*",
    })
    try:
        sess.get(SZSE_REFERER, timeout=20)
    except requests.RequestException:
        pass
    r = sess.get(
        SZSE_ENDPOINT,
        params={"SHOWTYPE": "xlsx", "CATALOGID": "1110", "TABKEY": "tab1"},
        timeout=60,
    )
    r.raise_for_status()
    p = raw / "SZSE_A_SHARE_LIST_FULL.xlsx"
    p.write_bytes(r.content)
    captures = [{"file": str(p), "sha256": sha_file(p), "bytes": p.stat().st_size, "url": r.url}]
    sheets = pd.read_excel(p, sheet_name=None, dtype=str)
    rows = []
    for df in sheets.values():
        df = df.fillna("")
        if "A股代码" not in df.columns or "A股上市日期" not in df.columns:
            continue
        for _, x in df.iterrows():
            code = str(x.get("A股代码") or "").strip()
            if not CODE_RE.fullmatch(code):
                continue
            board = str(x.get("板块") or "").strip()
            if board not in {"主板", "创业板"}:
                continue
            try:
                ld = parse_date(x.get("A股上市日期"))
            except Exception:
                continue
            if ld > d:
                continue
            rows.append({
                "canonical_security_id": f"SZSE:{code}",
                "exchange": "SZSE",
                "security_code": code,
                "security_short_name": str(x.get("A股简称") or "").strip(),
                "official_list_date": ld.isoformat(),
                "official_source": "SZSE_CATALOG_1110",
            })
    out = pd.DataFrame(rows).drop_duplicates("canonical_security_id")
    if len(out) <= 1000:
        raise RuntimeError(f"SZSE normalized count implausible {len(out)}")
    return out, captures

def reconcile(previous: pd.DataFrame, current: pd.DataFrame, delist_map: dict[str, str], d: date) -> dict:
    if previous["canonical_security_id"].duplicated().any() or current["canonical_security_id"].duplicated().any():
        raise RuntimeError("duplicate canonical id in universe reconciliation")
    prev = set(previous["canonical_security_id"])
    cur = set(current["canonical_security_id"])
    added = sorted(cur - prev)
    removed = sorted(prev - cur)
    resolved = []
    unresolved = []
    for cid in removed:
        raw = str(delist_map.get(cid) or "").strip()
        if raw:
            try:
                dd = parse_date(raw)
                if dd <= d:
                    resolved.append({"canonical_security_id": cid, "official_delist_date": dd.isoformat()})
                    continue
            except Exception:
                pass
        unresolved.append(cid)
    return {
        "added": added,
        "removed": removed,
        "resolved_removals": resolved,
        "unresolved_removals": unresolved,
        "status": "PASS" if not unresolved else "BLOCKED_UNRESOLVED_REMOVAL",
    }

def raw_bundle(out_root: Path, d: date, raw_dir: Path) -> tuple[Path, str]:
    p = out_root / f"{d.isoformat()}_PIT_RAW_OFFICIAL.tar.gz"
    with tarfile.open(p, "w:gz", compresslevel=9) as tf:
        for f in sorted(raw_dir.rglob("*")):
            if f.is_file():
                tf.add(f, arcname=str(f.relative_to(raw_dir)))
    return p, sha_file(p)

def capture(d: date, out_root: Path) -> None:
    calendar = load_calendar()
    if d < FIRST_SIGNAL_DATE or d not in calendar:
        print(json.dumps({"status": "NO_AUTHORITY_REQUIRED", "signal_date": d.isoformat()}, ensure_ascii=False))
        return

    now = datetime.now(timezone.utc).astimezone(TZ)
    close = datetime.combine(d, time(15, 0, 0), TZ)
    cutoff = datetime.combine(d + timedelta(days=1), time(23, 59, 59), TZ)
    if not (close < now <= cutoff):
        raise RuntimeError(f"capture time {now.isoformat()} outside frozen D window")

    out_root.mkdir(parents=True, exist_ok=True)
    previous_ref, previous = latest_previous_universe(out_root, d)
    delist_map = load_intervals()

    with tempfile.TemporaryDirectory() as td:
        raw = Path(td)
        sse, sc = fetch_sse(d, raw / "sse")
        sz, zc = fetch_szse(d, raw / "szse")
        current = pd.concat([sse, sz], ignore_index=True).sort_values("canonical_security_id")
        if current["canonical_security_id"].duplicated().any():
            raise RuntimeError("cross-exchange canonical duplication")
        rec = reconcile(previous, current, delist_map, d)

        normalized = out_root / f"{d.isoformat()}_OFFICIAL_CURRENT_NORMALIZED.csv"
        current.to_csv(normalized, index=False, lineterminator="\n")
        delta = out_root / f"{d.isoformat()}_PIT_DELTA.json"
        delta.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        bundle, bundle_sha = raw_bundle(out_root, d, raw)

        authority = {
            "schema": "AI_CORE_EVID_V2_8_3_PIT_DATE_AUTHORITY_V1",
            "version": "V2.8.3",
            "signal_date": d.isoformat(),
            "runner_observed_at_utc_descriptive": datetime.now(timezone.utc).isoformat(),
            "authoritative_observation_time_rule": "GitHub committed_at timestamp of this authority-file creation commit",
            "status": rec["status"],
            "previous_universe_reference": previous_ref,
            "official_current_count": int(len(current)),
            "sse_count": int((current["exchange"] == "SSE").sum()),
            "szse_count": int((current["exchange"] == "SZSE").sum()),
            "added_count": len(rec["added"]),
            "removed_count": len(rec["removed"]),
            "resolved_removal_count": len(rec["resolved_removals"]),
            "unresolved_removals": rec["unresolved_removals"],
            "official_current_normalized_file": str(normalized),
            "official_current_normalized_sha256": sha_file(normalized),
            "raw_official_bundle_file": str(bundle),
            "raw_official_bundle_sha256": bundle_sha,
            "source_capture_count": len(sc) + len(zc),
            "H1_H2_interim_statistics_computed": False,
        }
        if rec["status"] == "PASS":
            universe = out_root / f"{d.isoformat()}_PIT_UNIVERSE.csv"
            fields = ["canonical_security_id", "exchange", "security_code", "security_short_name", "official_list_date"]
            current[fields].to_csv(universe, index=False, lineterminator="\n")
            authority["universe_snapshot_file"] = str(universe)
            authority["universe_snapshot_sha256"] = sha_file(universe)
        authority["receipt_sha256"] = stable_json_sha(authority)
        ap = out_root / f"{d.isoformat()}_PIT_DATE_AUTHORITY.json"
        ap.write_text(json.dumps(authority, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(authority, ensure_ascii=False, indent=2))

def self_test() -> None:
    tests=[]
    def check(name, cond, detail=None):
        tests.append({"name":name,"pass":bool(cond),"detail":detail})
    d=date(2026,9,22)
    prev=pd.DataFrame([
      {"canonical_security_id":"SSE:600001","exchange":"SSE","security_code":"600001","security_short_name":"A","official_list_date":"2000-01-01"},
      {"canonical_security_id":"SZSE:000001","exchange":"SZSE","security_code":"000001","security_short_name":"B","official_list_date":"2000-01-01"},
    ])
    cur_same=prev.copy()
    r=reconcile(prev,cur_same,{},d)
    check("P01_no_delta_pass",r["status"]=="PASS")
    cur_add=pd.concat([cur_same,pd.DataFrame([{"canonical_security_id":"SSE:600002","exchange":"SSE","security_code":"600002","security_short_name":"C","official_list_date":d.isoformat()}])],ignore_index=True)
    r2=reconcile(prev,cur_add,{},d)
    check("P02_addition_allowed",r2["status"]=="PASS" and r2["added"]==["SSE:600002"],r2["added"])
    cur_removed=prev[prev["canonical_security_id"]!="SSE:600001"].copy()
    r3=reconcile(prev,cur_removed,{},d)
    check("P03_unresolved_removal_blocks",r3["status"]=="BLOCKED_UNRESOLVED_REMOVAL",r3)
    r4=reconcile(prev,cur_removed,{"SSE:600001":"2026-09-22"},d)
    check("P04_resolved_delist_pass",r4["status"]=="PASS" and len(r4["resolved_removals"])==1,r4)
    r5=reconcile(prev,cur_removed,{"SSE:600001":"2026-09-23"},d)
    check("P05_future_delist_does_not_resolve_D",r5["status"]=="BLOCKED_UNRESOLVED_REMOVAL",r5)
    dup=pd.concat([prev,prev.iloc[[0]]],ignore_index=True)
    blocked=False
    try: reconcile(dup,cur_same,{},d)
    except RuntimeError: blocked=True
    check("P06_duplicate_identity_blocks",blocked)
    check("P07_first_signal_boundary",date(2026,9,21)<FIRST_SIGNAL_DATE)
    filt_dates=[date(2026,9,22),date(2026,9,23)]
    check("P08_future_listing_filter_semantics",min(filt_dates)==d)
    res={"schema":"AI_CORE_EVID_V2_8_3_PIT_DATE_AUTHORITY_SELFTEST_V1","tests":tests,
         "passed":sum(1 for x in tests if x["pass"]),"total":len(tests),"all_pass":all(x["pass"] for x in tests)}
    res["receipt_sha256"]=stable_json_sha(res)
    print(json.dumps(res,ensure_ascii=False,indent=2))
    if not res["all_pass"]: raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="command",required=True)
    sub.add_parser("self-test")
    c=sub.add_parser("capture")
    c.add_argument("--signal-date",required=True)
    c.add_argument("--out",default="evidence/v283_pit_authority")
    args=ap.parse_args()
    if args.command=="self-test": self_test()
    else: capture(date.fromisoformat(args.signal_date),Path(args.out))

if __name__=="__main__":
    main()
