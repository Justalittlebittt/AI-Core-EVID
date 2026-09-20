from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

EPOCH_ID = "AI_CORE_EVID_FORWARD_EPOCH_001"
T0_UTC = "2026-09-20T07:17:16Z"
T0_DT = datetime.fromisoformat(T0_UTC.replace("Z", "+00:00"))

BASELINE_ISSUER = Path("evidence/V2.7.27_SECURITY_ISSUER_PIT_MAP.csv")
BASELINE_ISSUER_SHA = "769960860eaeb97f34780eca3b8cdb2618a4e3afd580e97f59fe6435da8b25a8"
BASELINE_LOCATOR = Path("evidence/V2.7.29_PRIMARY_LOCATOR_INVENTORY.csv")
BASELINE_LOCATOR_SHA = "6f497c81f99344596ba19e7ef62c54a23d373c07f80877d79af6f70f19f4a4f4"
BASELINE_LOCATOR_ORIGINAL_OBSERVED = "2026-09-20T06:36:51.251465+00:00"

OUT = Path("v2731_forward_bootstrap")
RAW = OUT / "raw"
SSE_RAW = RAW / "sse"
SZSE_RAW = RAW / "szse"
for p in (OUT, RAW, SSE_RAW, SZSE_RAW):
    p.mkdir(parents=True, exist_ok=True)

SSE_ENDPOINT = "https://query.sse.com.cn/sseQuery/commonQuery.do"
SSE_REFERER = "https://www.sse.com.cn/assortment/stock/list/share/"
SZSE_JSON_ENDPOINT = "https://www.szse.cn/api/report/ShowReport/data"
SZSE_REFERER = "https://www.szse.cn/market/product/stock/list/index.html"
CODE_RE = re.compile(r"^\d{6}$")
TAG_RE = re.compile(r"<[^>]+>")

def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def ensure_after_t0(ts: datetime, label: str) -> None:
    if ts <= T0_DT:
        raise RuntimeError(f"{label}={ts.isoformat()} is not after T0={T0_UTC}")

def decode_json_or_jsonp(b: bytes):
    s = b.decode("utf-8", "ignore").strip()
    try:
        return json.loads(s)
    except Exception:
        m = re.match(r"^[A-Za-z_$][\w$]*\((.*)\)\s*;?\s*$", s, re.S)
        if not m:
            raise
        return json.loads(m.group(1))

def clean_html_text(v) -> str:
    return TAG_RE.sub("", str(v or "")).strip()

def load_csv_exact(path: Path, expected_sha: str) -> list[dict]:
    b = path.read_bytes()
    actual = sha(b)
    if actual != expected_sha:
        raise RuntimeError(f"{path}: SHA mismatch {actual} != {expected_sha}")
    return list(csv.DictReader(b.decode("utf-8").splitlines()))

def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})

def request_once(session: requests.Session, url: str, *, params: dict, timeout: int, label: str):
    try:
        r = session.get(url, params=params, timeout=timeout)
    except Exception as e:
        raise RuntimeError(f"{label}: transport error {type(e).__name__}: {e}") from e
    if r.status_code != 200:
        raise RuntimeError(f"{label}: HTTP {r.status_code}")
    return r

def fetch_sse(asof_date):
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
        "Referer": SSE_REFERER,
    })
    membership = {}
    captures = []

    for stock_type, label in (("1", "main_a"), ("8", "star")):
        callback = f"jsonpCallback2731{stock_type}"
        base = {
            "jsonCallBack": callback,
            "STOCK_TYPE": stock_type,
            "REG_PROVINCE": "",
            "CSRC_CODE": "",
            "STOCK_CODE": "",
            "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
            "COMPANY_STATUS": "2,4,5,7,8",
            "type": "inParams",
            "isPagination": "true",
            "pageHelp.cacheSize": "1",
            "pageHelp.pageSize": "25",
            "_": str(int(time.time() * 1000)),
        }

        first_params = {
            **base,
            "pageHelp.beginPage": "1",
            "pageHelp.pageNo": "1",
            "pageHelp.endPage": "1",
        }
        first = request_once(
            session, SSE_ENDPOINT, params=first_params, timeout=30,
            label=f"SSE {label} page 1"
        )
        first_obj = decode_json_or_jsonp(first.content)
        ph = first_obj.get("pageHelp", {}) if isinstance(first_obj, dict) else {}
        total = int(ph.get("total") or 0)
        page_size = int(ph.get("pageSize") or 25)
        if total <= 0:
            raise RuntimeError(f"SSE {label}: invalid total={total}")
        pages = max(1, math.ceil(total / page_size))

        for n in range(1, pages + 1):
            params = {
                **base,
                "pageHelp.beginPage": str(n),
                "pageHelp.pageNo": str(n),
                "pageHelp.endPage": str(n),
            }
            r = first if n == 1 else request_once(
                session, SSE_ENDPOINT, params=params, timeout=30,
                label=f"SSE {label} page {n}"
            )
            p = SSE_RAW / f"{label}_{n:04d}.json"
            p.write_bytes(r.content)
            captures.append({
                "exchange": "SSE",
                "board": label,
                "page": n,
                "url": r.url,
                "status": r.status_code,
                "bytes": len(r.content),
                "sha256": sha(r.content),
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            })

            obj = decode_json_or_jsonp(r.content)
            rows = obj.get("result") or []
            if not isinstance(rows, list):
                raise RuntimeError(f"SSE {label} page {n}: result is not a list")

            for x in rows:
                code = str(x.get("A_STOCK_CODE") or "").strip()
                st = str(x.get("STOCK_TYPE") or "").strip()
                if not CODE_RE.fullmatch(code) or st not in {"1", "8"}:
                    continue
                ld = pd.to_datetime(x.get("LIST_DATE"), errors="coerce")
                if pd.isna(ld) or pd.Timestamp(ld).date() > asof_date:
                    continue
                cid = f"SSE:{code}"
                rec = {
                    "canonical_security_id": cid,
                    "exchange": "SSE",
                    "security_code": code,
                    "security_short_name": str(x.get("COMPANY_ABBR") or "").strip(),
                    "official_list_date": pd.Timestamp(ld).date().isoformat(),
                    "official_board_code": str(x.get("LIST_BOARD") or "").strip(),
                    "membership_source_path": str(p.relative_to(OUT)),
                    "membership_source_sha256": sha(r.content),
                    "membership_source_type": "SSE_OFFICIAL_JSON",
                }
                if cid in membership:
                    old = membership[cid]
                    stable = ("security_short_name", "official_list_date", "official_board_code")
                    if any(old[k] != rec[k] for k in stable):
                        raise RuntimeError(f"SSE membership identity conflict {cid}")
                else:
                    membership[cid] = rec

    if len(membership) <= 1000:
        raise RuntimeError(f"SSE normalized count implausible {len(membership)}")
    return membership, captures

def szse_payload_obj(b: bytes):
    obj = json.loads(b.decode("utf-8"))
    if not isinstance(obj, list):
        raise RuntimeError("SZSE JSON root is not a list")
    for part in obj:
        if not isinstance(part, dict):
            continue
        meta = part.get("metadata") or {}
        data = part.get("data")
        if str(meta.get("catalogid")) == "1110" and str(meta.get("tabkey")) == "tab1" and isinstance(data, list):
            return meta, data
    raise RuntimeError("SZSE JSON did not contain CATALOGID=1110/tab1 data")

def fetch_szse(asof_date):
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
        "Referer": SZSE_REFERER,
        "Accept": "application/json,text/plain,*/*",
    })

    def params_for(page_no: int):
        p = {
            "SHOWTYPE": "JSON",
            "CATALOGID": "1110",
            "TABKEY": "tab1",
            "PAGENO": str(page_no),
            "random": f"{time.time() % 1:.16f}",
        }
        if page_no == 1:
            p["loading"] = "first"
        return p

    first = request_once(
        session, SZSE_JSON_ENDPOINT, params=params_for(1), timeout=30,
        label="SZSE A-share JSON page 1"
    )
    first_meta, _ = szse_payload_obj(first.content)
    pagecount = int(first_meta.get("pagecount") or 0)
    recordcount = int(first_meta.get("recordcount") or 0)
    pagesize = int(first_meta.get("pagesize") or 0)
    if pagecount <= 0 or recordcount <= 1000 or pagesize <= 0:
        raise RuntimeError(
            f"SZSE metadata implausible pagecount={pagecount} recordcount={recordcount} pagesize={pagesize}"
        )

    membership = {}
    captures = []
    fetched_rows = 0

    for n in range(1, pagecount + 1):
        r = first if n == 1 else request_once(
            session, SZSE_JSON_ENDPOINT, params=params_for(n), timeout=30,
            label=f"SZSE A-share JSON page {n}"
        )
        p = SZSE_RAW / f"a_share_{n:04d}.json"
        p.write_bytes(r.content)
        meta, rows = szse_payload_obj(r.content)
        reported_page = int(meta.get("pageno") or 0)
        if reported_page and reported_page != n:
            raise RuntimeError(f"SZSE page mismatch requested={n} reported={reported_page}")
        captures.append({
            "exchange": "SZSE",
            "page": n,
            "url": r.url,
            "status": r.status_code,
            "bytes": len(r.content),
            "sha256": sha(r.content),
            "rows": len(rows),
            "reported_recordcount": int(meta.get("recordcount") or 0),
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        })
        fetched_rows += len(rows)

        for x in rows:
            board = str(x.get("bk") or "").strip()
            code = str(x.get("agdm") or "").strip()
            if board not in {"主板", "创业板"} or not CODE_RE.fullmatch(code):
                continue
            ld = pd.to_datetime(x.get("agssrq"), errors="coerce")
            if pd.isna(ld) or pd.Timestamp(ld).date() > asof_date:
                continue
            cid = f"SZSE:{code}"
            rec = {
                "canonical_security_id": cid,
                "exchange": "SZSE",
                "security_code": code,
                "security_short_name": clean_html_text(x.get("agjc")),
                "official_list_date": pd.Timestamp(ld).date().isoformat(),
                "official_board_code": board,
                "membership_source_path": str(p.relative_to(OUT)),
                "membership_source_sha256": sha(r.content),
                "membership_source_type": "SZSE_OFFICIAL_JSON",
            }
            if cid in membership:
                old = membership[cid]
                stable = ("security_short_name", "official_list_date", "official_board_code")
                if any(old[k] != rec[k] for k in stable):
                    raise RuntimeError(f"SZSE membership identity conflict {cid}")
            else:
                membership[cid] = rec

    if fetched_rows != recordcount:
        raise RuntimeError(f"SZSE pagination did not close: fetched={fetched_rows} recordcount={recordcount}")
    if len(membership) <= 1000:
        raise RuntimeError(f"SZSE normalized count implausible {len(membership)}")
    return membership, captures, {
        "pagecount": pagecount,
        "recordcount": recordcount,
        "pagesize": pagesize,
        "fetched_rows": fetched_rows,
    }

def build_raw_manifest():
    excluded = {
        "V2.7.31_FORWARD_RAW_EVIDENCE.tar.gz",
        "V2.7.31_FORWARD_RAW_MANIFEST.csv",
        "V2.7.31_FORWARD_CERTIFIED_UNIVERSE.csv",
        "V2.7.31_FORWARD_CERTIFIED_UNIVERSE_RECEIPT.json",
        "V2.7.31_FORWARD_CURRENT_ISSUER_MAP.csv",
        "V2.7.31_FORWARD_MEMBERSHIP_DELTA.csv",
        "V2.7.31_FORWARD_MEMBERSHIP_SNAPSHOT.csv",
    }
    rows = []
    for p in sorted(OUT.rglob("*")):
        if not p.is_file() or p.name in excluded:
            continue
        b = p.read_bytes()
        rows.append({"path": str(p.relative_to(OUT)), "bytes": len(b), "sha256": sha(b)})
    manifest = OUT / "V2.7.31_FORWARD_RAW_MANIFEST.csv"
    write_csv(manifest, rows, ["path", "bytes", "sha256"])
    bundle = OUT / "V2.7.31_FORWARD_RAW_EVIDENCE.tar.gz"
    with tarfile.open(bundle, "w:gz", compresslevel=9) as tf:
        for row in rows:
            tf.add(OUT / row["path"], arcname=row["path"])
    return manifest, bundle, rows

def main():
    started = datetime.now(timezone.utc)
    ensure_after_t0(started, "run_started_at_utc")
    asof_date = started.astimezone(timezone.utc).date()

    baseline_issuer_rows = load_csv_exact(BASELINE_ISSUER, BASELINE_ISSUER_SHA)
    baseline_locator_rows = load_csv_exact(BASELINE_LOCATOR, BASELINE_LOCATOR_SHA)
    baseline_issuer = {r["canonical_security_id"]: r for r in baseline_issuer_rows}
    baseline_locator = {r["canonical_security_id"]: r for r in baseline_locator_rows}
    if set(baseline_issuer) != set(baseline_locator):
        raise RuntimeError("baseline issuer/locator identity sets differ")
    baseline_ids = set(baseline_issuer)

    sse_membership, sse_caps = fetch_sse(asof_date)
    sz_membership, sz_caps, sz_meta = fetch_szse(asof_date)
    current_membership = {**sse_membership, **sz_membership}
    current_ids = set(current_membership)
    observed_at = datetime.now(timezone.utc)
    ensure_after_t0(observed_at, "official_membership_observed_at_utc")

    added = sorted(current_ids - baseline_ids)
    removed = sorted(baseline_ids - current_ids)
    unchanged = sorted(current_ids & baseline_ids)

    print(
        f"CURRENT count={len(current_ids)} SSE={len(sse_membership)} SZSE={len(sz_membership)} "
        f"unchanged={len(unchanged)} added={len(added)} removed={len(removed)}",
        flush=True,
    )
    if added:
        print("ADDED " + json.dumps(added, ensure_ascii=False), flush=True)
    if removed:
        print("REMOVED " + json.dumps(removed, ensure_ascii=False), flush=True)

    snapshot_fields = [
        "canonical_security_id", "exchange", "security_code", "security_short_name",
        "official_list_date", "official_board_code", "membership_source_type",
        "membership_source_path", "membership_source_sha256",
    ]
    membership_snapshot = OUT / "V2.7.31_FORWARD_MEMBERSHIP_SNAPSHOT.csv"
    write_csv(
        membership_snapshot,
        [current_membership[cid] for cid in sorted(current_membership)],
        snapshot_fields,
    )

    delta_path = OUT / "V2.7.31_FORWARD_MEMBERSHIP_DELTA.csv"
    delta_rows = []
    for cid in added:
        delta_rows.append({"canonical_security_id": cid, "delta": "ADDED", **current_membership[cid]})
    for cid in removed:
        b = baseline_issuer[cid]
        delta_rows.append({
            "canonical_security_id": cid,
            "delta": "REMOVED",
            "exchange": b["exchange"],
            "security_code": b["security_code"],
            "security_short_name": b["security_short_name"],
            "official_list_date": b["official_list_date"],
            "official_board_code": b["official_board_code"],
            "membership_source_type": "V2.7.27_BASELINE",
            "membership_source_path": b["source_path"],
            "membership_source_sha256": b["source_sha256"],
        })
    write_csv(delta_path, delta_rows, ["canonical_security_id", "delta"] + snapshot_fields[1:])

    direct_manifest = OUT / "V2.7.31_OFFICIAL_DIRECT_CAPTURE_MANIFEST.json"
    direct_manifest.write_text(
        json.dumps({
            "sse": sse_caps,
            "szse": sz_caps,
            "szse_metadata": sz_meta,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    certified_at = None
    universe_path = OUT / "V2.7.31_FORWARD_CERTIFIED_UNIVERSE.csv"
    issuer_path = OUT / "V2.7.31_FORWARD_CURRENT_ISSUER_MAP.csv"

    # If there are no additions, every current member already has a frozen exact
    # issuer identity and terminal locator. Re-adopt those artifacts at T0; do not
    # re-query CNInfo or re-download PDFs.
    if not added:
        certified_at = datetime.now(timezone.utc)
        ensure_after_t0(certified_at, "certified_at_utc")

        issuer_fields = [
            "canonical_security_id", "exchange", "security_code",
            "official_issuer_query_key", "official_issuer_query_key_type",
            "issuer_legal_name", "security_short_name", "official_list_date",
            "official_board_code", "issuer_provenance",
            "baseline_source_path", "baseline_source_sha256",
        ]
        issuer_rows = []
        universe = []
        for cid in sorted(current_ids):
            member = current_membership[cid]
            issuer = baseline_issuer[cid]
            loc = baseline_locator[cid]

            issuer_rows.append({
                "canonical_security_id": cid,
                "exchange": member["exchange"],
                "security_code": member["security_code"],
                "official_issuer_query_key": issuer["official_issuer_query_key"],
                "official_issuer_query_key_type": issuer["official_issuer_query_key_type"],
                "issuer_legal_name": issuer["issuer_legal_name"],
                "security_short_name": member["security_short_name"],
                "official_list_date": member["official_list_date"],
                "official_board_code": member["official_board_code"],
                "issuer_provenance": "BASELINE_ADOPTED_AT_T0",
                "baseline_source_path": issuer["source_path"],
                "baseline_source_sha256": issuer["source_sha256"],
            })

            if not loc.get("announcement_id") or not loc.get("adjunct_url"):
                raise RuntimeError(f"{cid}: baseline terminal locator incomplete")

            universe.append({
                "epoch_id": EPOCH_ID,
                "epoch_t0_utc": T0_UTC,
                "certified_at_utc": certified_at.isoformat(),
                "canonical_security_id": cid,
                "exchange": member["exchange"],
                "security_code": member["security_code"],
                "issuer_legal_name": issuer["issuer_legal_name"],
                "security_short_name": member["security_short_name"],
                "official_list_date": member["official_list_date"],
                "official_board_code": member["official_board_code"],
                "membership_provenance": "FORWARD_OBSERVED_AFTER_T0",
                "membership_observed_at_utc": observed_at.isoformat(),
                "issuer_provenance": "BASELINE_ADOPTED_AT_T0",
                "locator_provenance": "BASELINE_ADOPTED_AT_T0",
                "locator_original_first_observed_at_utc": BASELINE_LOCATOR_ORIGINAL_OBSERVED,
                "resolution": loc.get("resolution", ""),
                "document_type": loc.get("document_type", ""),
                "title": loc.get("title", ""),
                "disclosure_date": loc.get("disclosure_date", ""),
                "period_end": loc.get("period_end", ""),
                "revision": loc.get("revision", ""),
                "announcement_id": loc.get("announcement_id", ""),
                "adjunct_url": loc.get("adjunct_url", ""),
                "org_id": loc.get("org_id", ""),
                "locator_source": loc.get("source", ""),
                "pdf_materialization_status": "ON_DEMAND_NOT_REQUIRED_FOR_UNIVERSE_ENTRY",
                "universe_entry_status": "CERTIFIED",
            })

        write_csv(issuer_path, issuer_rows, issuer_fields)
        write_csv(universe_path, universe, list(universe[0].keys()))

    manifest, bundle, raw_rows = build_raw_manifest()
    set_hash = sha(("\n".join(sorted(current_ids)) + "\n").encode())

    if added:
        gate_status = "FORWARD_MEMBERSHIP_DELTA_PASS_NEEDS_TARGETED_ADDITION_RESOLUTION"
        certified_status = "BLOCKED_ADDED_MEMBERS_NEED_ISSUER_AND_LOCATOR"
        first60 = "BLOCKED_PENDING_ADDED_MEMBER_RESOLUTION"
    else:
        gate_status = "FORWARD_CERTIFIED_UNIVERSE_BOOTSTRAP_PASS"
        certified_status = "PASS"
        first60 = "READY_FOR_DETERMINISTIC_EPISODE_START_NOT_STARTED"

    receipt = {
        "schema": "AI_CORE_EVID_V2_7_31_FORWARD_CERTIFIED_UNIVERSE_RECEIPT_V2",
        "epoch_id": EPOCH_ID,
        "epoch_t0_utc": T0_UTC,
        "run_started_at_utc": started.isoformat(),
        "official_membership_observed_at_utc": observed_at.isoformat(),
        "asof_date_utc": asof_date.isoformat(),
        "transport": {
            "sse": "DIRECT_REUSED_OFFICIAL_JSON_API_CONTRACT",
            "szse": "DIRECT_OFFICIAL_JSON_PAGINATION",
            "webpage_navigation": False,
            "xlsx_export": False,
            "chromium_required": False,
        },
        "baseline": {
            "count": len(baseline_ids),
            "issuer_map_sha256": BASELINE_ISSUER_SHA,
            "primary_locator_inventory_sha256": BASELINE_LOCATOR_SHA,
            "adoption_semantics": "BASELINE_ADOPTED_AT_T0_FOR_POST_T0_DECISIONS_ONLY",
        },
        "current_official_membership": {
            "count": len(current_ids),
            "sse_count": len(sse_membership),
            "szse_count": len(sz_membership),
            "canonical_sorted_newline_sha256": set_hash,
            "szse_server_recordcount": sz_meta["recordcount"],
            "szse_fetched_rows": sz_meta["fetched_rows"],
        },
        "delta": {
            "unchanged_count": len(unchanged),
            "added_count": len(added),
            "removed_count": len(removed),
            "added_ids": added,
            "removed_ids": removed,
        },
        "outputs": {
            "membership_snapshot_sha256": sha(membership_snapshot.read_bytes()),
            "membership_delta_sha256": sha(delta_path.read_bytes()),
            "raw_manifest_sha256": sha(manifest.read_bytes()),
            "raw_bundle_sha256": sha(bundle.read_bytes()),
            "raw_bundle_bytes": bundle.stat().st_size,
            "raw_file_count": len(raw_rows),
        },
        "temporal_governance": {
            "pre_t0_decisions_authorized": False,
            "historical_2026_09_17_prospective_relabeling": "FORBIDDEN",
        },
        "downstream": {
            "certified_v2_universe": certified_status,
            "first60": first60,
            "filing_content_materialization": "ON_DEMAND_V2.7.30",
            "vendor_price_coverage": "SEPARATE_PER_SECURITY_EXECUTION_GATE",
            "s4_s5_s6": "BLOCKED_PENDING_FIRST60_AND_LATER_GATES",
            "live": "BLOCKED",
        },
        "gate": {
            "status": gate_status,
            "current_membership_exact": True,
            "targeted_added_member_resolution_required": bool(added),
        },
    }

    if certified_at is not None:
        receipt["certified_at_utc"] = certified_at.isoformat()
        receipt["issuer_identity"] = {
            "terminal_identity_count": len(current_ids),
            "baseline_adopted_count": len(current_ids),
            "forward_targeted_resolution_count": 0,
            "missing_count": 0,
        }
        receipt["primary_locator"] = {
            "terminal_locator_count": len(current_ids),
            "baseline_adopted_count": len(current_ids),
            "forward_targeted_resolution_count": 0,
            "missing_count": 0,
        }
        receipt["outputs"]["current_issuer_map_sha256"] = sha(issuer_path.read_bytes())
        receipt["outputs"]["certified_universe_sha256"] = sha(universe_path.read_bytes())

    canonical = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    receipt["receipt_sha256"] = sha(canonical)
    (OUT / "V2.7.31_FORWARD_CERTIFIED_UNIVERSE_RECEIPT.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
