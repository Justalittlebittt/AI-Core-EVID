from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from huggingface_hub import HfApi, hf_hub_download
from playwright.sync_api import sync_playwright

PIT_DATE = pd.Timestamp("2026-09-17")
OUT = Path("artifacts")
RAW = OUT / "raw"
NORM = OUT / "normalized"
RAW.mkdir(parents=True, exist_ok=True)
NORM.mkdir(parents=True, exist_ok=True)

SSE_PAGE = "https://www.sse.com.cn/assortment/stock/list/share/"
SZSE_PAGE = "https://www.szse.cn/market/product/stock/list/index.html"

ALLOWED_HOSTS = ("sse.com.cn", "szse.cn")
CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")

SSE_EXCHANGE_NAMES = {
    "Shanghai": "SSE",
    "Shanghai Stock Exchange": "SSE",
    "SHH": "SSE",
    "SH": "SSE",
}
SZSE_EXCHANGE_NAMES = {
    "Shenzhen": "SZSE",
    "Shenzhen Stock Exchange": "SZSE",
    "SHZ": "SZSE",
    "SZ": "SZSE",
}

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def safe_name(url: str, i: int, ct: str) -> str:
    ext = ".bin"
    lct = (ct or "").lower()
    if "json" in lct:
        ext = ".json"
    elif "excel" in lct or "spreadsheet" in lct:
        ext = ".xlsx"
    elif "csv" in lct:
        ext = ".csv"
    elif "html" in lct:
        ext = ".html"
    return f"{i:04d}_{hashlib.sha1(url.encode()).hexdigest()[:12]}{ext}"

def capture_page(page_url: str, exchange: str) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    exchange_dir = RAW / exchange.lower()
    exchange_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
            locale="zh-CN",
        )
        page = context.new_page()

        def on_response(resp):
            try:
                url = resp.url
                if not any(h in url for h in ALLOWED_HOSTS):
                    return
                ct = resp.headers.get("content-type", "")
                # Keep potentially useful official response bytes only.
                if not any(x in ct.lower() for x in (
                    "json", "excel", "spreadsheet", "csv", "octet-stream"
                )):
                    return
                body = resp.body()
                if not body:
                    return
                i = len(recs) + 1
                fn = safe_name(url, i, ct)
                p = exchange_dir / fn
                p.write_bytes(body)
                recs.append({
                    "exchange": exchange,
                    "url": url,
                    "status": resp.status,
                    "content_type": ct,
                    "path": str(p),
                    "bytes": len(body),
                    "sha256": sha256_bytes(body),
                    "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                recs.append({
                    "exchange": exchange,
                    "capture_error": repr(e),
                    "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                })

        page.on("response", on_response)
        page.goto(page_url, wait_until="domcontentloaded", timeout=90000)
        # Give dynamic tables enough time to load and trigger a couple of scrolls.
        page.wait_for_timeout(8000)
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(3000)
        page.mouse.wheel(0, -3000)
        page.wait_for_timeout(2000)
        # Save rendered HTML as supplemental evidence, not canonical raw API bytes.
        html = page.content().encode("utf-8")
        hp = exchange_dir / "rendered_page.html"
        hp.write_bytes(html)
        recs.append({
            "exchange": exchange,
            "url": page_url,
            "status": 200,
            "content_type": "text/html-rendered",
            "path": str(hp),
            "bytes": len(html),
            "sha256": sha256_bytes(html),
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "supplemental": True,
        })
        browser.close()
    return recs

def decode_json_or_jsonp_bytes(b: bytes) -> Any:
    txt = b.decode("utf-8", errors="ignore").strip()
    try:
        return json.loads(txt)
    except Exception:
        m = re.match(r"^[A-Za-z_$][\\w$]*\\((.*)\\)\\s*;?\\s*$", txt, re.S)
        if not m:
            raise
        return json.loads(m.group(1))

def expand_complete_official_sources(captures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    extra: list[dict[str, Any]] = []

    # SSE: use the exact page-generated official query, changing only documented
    # pagination fields already present in that request.
    sse_first = next((c for c in captures if c.get("exchange") == "SSE"
                      and "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L" in c.get("url", "")
                      and c.get("path")), None)
    if sse_first:
        first_obj = decode_json_or_jsonp_bytes(Path(sse_first["path"]).read_bytes())
        ph = first_obj.get("pageHelp", {}) if isinstance(first_obj, dict) else {}
        total = int(ph.get("total") or 0)
        page_size = int(ph.get("pageSize") or 25)
        pages = max(1, math.ceil(total / page_size))
        parsed = urlparse(sse_first["url"])
        q = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
        sess = requests.Session()
        sess.headers.update({"User-Agent": "Mozilla/5.0", "Referer": SSE_PAGE})
        for page_no in range(1, pages + 1):
            qq = dict(q)
            qq["pageHelp.pageNo"] = str(page_no)
            qq["pageHelp.beginPage"] = str(page_no)
            qq["pageHelp.endPage"] = str(page_no)
            url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(qq), ""))
            r = sess.get(url, timeout=30)
            r.raise_for_status()
            p = RAW / "sse" / f"paged_{page_no:04d}.json"
            p.write_bytes(r.content)
            extra.append({
                "exchange": "SSE", "url": url, "status": r.status_code,
                "content_type": r.headers.get("content-type", ""),
                "path": str(p), "bytes": len(r.content),
                "sha256": sha256_bytes(r.content),
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "pagination_expansion": True,
            })

    # SZSE: the page response itself declares CATALOGID=1110 as “A股列表”
    # and declares excel=xlsx. Fetch the corresponding official full XLSX export.
    sz_meta = None
    for c in captures:
        if c.get("exchange") != "SZSE" or not c.get("path"):
            continue
        try:
            obj = decode_json_or_jsonp_bytes(Path(c["path"]).read_bytes())
            if isinstance(obj, list) and obj and isinstance(obj[0], dict):
                meta = obj[0].get("metadata", {})
                if str(meta.get("catalogid")) == "1110":
                    sz_meta = meta
                    break
        except Exception:
            pass
    if sz_meta:
        params = {"SHOWTYPE": "xlsx", "CATALOGID": "1110", "TABKEY": "tab1"}
        r = requests.get(
            "https://www.szse.cn/api/report/ShowReport",
            params=params,
            headers={"User-Agent": "Mozilla/5.0", "Referer": SZSE_PAGE},
            timeout=60,
        )
        r.raise_for_status()
        p = RAW / "szse" / "A_SHARE_LIST_FULL.xlsx"
        p.write_bytes(r.content)
        extra.append({
            "exchange": "SZSE", "url": r.url, "status": r.status_code,
            "content_type": r.headers.get("content-type", ""),
            "path": str(p), "bytes": len(r.content),
            "sha256": sha256_bytes(r.content),
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "full_export": True,
        })
    return captures + extra

def collect_records_from_json(obj: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        # Treat any dict with a six-digit-like field as candidate row.
        vals = {str(k): v for k, v in obj.items()}
        if any(CODE_RE.fullmatch(str(v).strip()) for v in vals.values() if v is not None):
            out.append(vals)
        for v in obj.values():
            out.extend(collect_records_from_json(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(collect_records_from_json(v))
    return out

def read_candidate_rows(p: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        if p.suffix.lower() == ".json":
            obj = decode_json_or_jsonp_bytes(p.read_bytes())
            return collect_records_from_json(obj)
        if p.suffix.lower() in {".xlsx", ".xls"}:
            sheets = pd.read_excel(p, sheet_name=None, dtype=str)
            for _, df in sheets.items():
                rows.extend(df.fillna("").to_dict("records"))
            return rows
        if p.suffix.lower() == ".csv":
            df = pd.read_csv(p, dtype=str)
            return df.fillna("").to_dict("records")
    except Exception:
        return []
    return rows

def extract_code(row: dict[str, Any]) -> str | None:
    # Prefer semantically named code fields, then fall back to exact six-digit values.
    keys = list(row.keys())
    preferred = [
        k for k in keys
        if any(t in str(k).lower() for t in ("code", "stock", "security", "证券代码", "股票代码", "公司代码", "a股代码"))
    ]
    for k in preferred + keys:
        v = row.get(k)
        if v is None:
            continue
        s = str(v).strip()
        m = CODE_RE.fullmatch(s)
        if m:
            return m.group(1)
    return None

def row_text(row: dict[str, Any]) -> str:
    return " | ".join(f"{k}={v}" for k, v in row.items())

def classify_official_rows(exchange: str, rows: list[dict[str, Any]]) -> tuple[set[str], list[dict[str, Any]]]:
    ids: set[str] = set()
    accepted: list[dict[str, Any]] = []
    for r in rows:
        code = extract_code(r)
        if not code:
            continue
        txt = row_text(r)

        # Reject clear non-equity rows when the source mixes products.
        reject_tokens = ("B股", "基金", "ETF", "REIT", "债券", "可转债", "期权", "存托凭证")
        if any(t in txt for t in reject_tokens):
            continue

        # We do NOT infer board/exchange from ticker prefix. The exchange is inherited from
        # the official page/source identity. Board is non-canonical metadata only.
        cid = f"{exchange}:{code}"
        ids.add(cid)
        accepted.append({"canonical_id": cid, "raw": r})
    return ids, accepted

def normalize_official(captures: list[dict[str, Any]]) -> tuple[set[str], dict[str, Any]]:
    by_ex: dict[str, list[dict[str, Any]]] = {"SSE": [], "SZSE": []}
    file_stats = []
    for c in captures:
        if c.get("supplemental") or "path" not in c:
            continue
        p = Path(c["path"])
        rows = read_candidate_rows(p)
        file_stats.append({"path": str(p), "rows_parsed": len(rows), "sha256": c.get("sha256")})
        by_ex[c["exchange"]].extend(rows)

    sse_ids, sse_rows = classify_official_rows("SSE", by_ex["SSE"])
    sz_ids, sz_rows = classify_official_rows("SZSE", by_ex["SZSE"])

    # Fail closed if either exchange yields implausibly few candidates.
    # These are integrity sanity bounds, not universe-selection thresholds.
    plausibility = {
        "sse_count": len(sse_ids),
        "szse_count": len(sz_ids),
        "sse_ok": len(sse_ids) > 1000,
        "szse_ok": len(sz_ids) > 1000,
    }
    official = sse_ids | sz_ids
    pd.DataFrame({"canonical_id": sorted(official)}).to_csv(
        NORM / "OFFICIAL_CURRENT_CANONICAL.csv", index=False
    )
    return official, {
        "file_stats": file_stats,
        "plausibility": plausibility,
        "status": "PASS" if plausibility["sse_ok"] and plausibility["szse_ok"]
                  else "BLOCKED_OFFICIAL_NORMALIZATION_IMPLAUSIBLE",
    }

def freeze_alphadojo() -> tuple[set[str], dict[str, Any]]:
    api = HfApi()
    info = api.dataset_info("AlphaDojo/dojo_stock_info")
    revision = info.sha
    p = Path(hf_hub_download(
        "AlphaDojo/dojo_stock_info",
        "data.parquet",
        repo_type="dataset",
        revision=revision,
    ))
    b = p.read_bytes()
    frozen = RAW / "alphadojo" / "data.parquet"
    frozen.parent.mkdir(parents=True, exist_ok=True)
    frozen.write_bytes(b)

    df = pd.read_parquet(io.BytesIO(b))
    required = {
        "ticker", "market", "quote_type", "full_exchange_name",
        "first_traded_date", "delisted_at"
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise RuntimeError(f"AlphaDojo missing required columns: {missing}")

    x = df.copy()
    x["market_norm"] = x["market"].astype(str).str.lower()
    x["quote_norm"] = x["quote_type"].astype(str).str.upper()
    x["first_dt"] = pd.to_datetime(x["first_traded_date"], errors="coerce", utc=True).dt.tz_convert(None)
    x["delist_dt"] = pd.to_datetime(x["delisted_at"], errors="coerce", utc=True).dt.tz_convert(None)

    x = x[(x["market_norm"] == "cn") & (x["quote_norm"] == "EQUITY")]
    x = x[(x["first_dt"].notna()) & (x["first_dt"] <= PIT_DATE)]
    x = x[(x["delist_dt"].isna()) | (x["delist_dt"] > PIT_DATE)]

    def exmap(s: Any) -> str | None:
        v = str(s).strip()
        lv = v.lower()
        if "shanghai" in lv or v in {"上海证券交易所", "SSE"}:
            return "SSE"
        if "shenzhen" in lv or v in {"深圳证券交易所", "SZSE"}:
            return "SZSE"
        return None

    x["exchange_canonical"] = x["full_exchange_name"].map(exmap)
    x = x[x["exchange_canonical"].isin(["SSE", "SZSE"])]

    def norm_ticker(v: Any) -> str | None:
        s = str(v).strip()
        m = CODE_RE.fullmatch(s)
        return m.group(1) if m else None

    x["code6"] = x["ticker"].map(norm_ticker)
    x = x[x["code6"].notna()]
    x["canonical_id"] = [
        f"{ex}:{code}" for ex, code in zip(x["exchange_canonical"].tolist(), x["code6"].tolist())
    ]
    ids = set(x["canonical_id"])

    outcsv = NORM / "ALPHADOJO_SHSZ_A_PIT_20260917.csv"
    x[["canonical_id", "ticker", "full_exchange_name", "first_traded_date", "delisted_at"]].drop_duplicates(
        "canonical_id"
    ).sort_values("canonical_id").to_csv(outcsv, index=False)

    return ids, {
        "repo_revision": revision,
        "raw_sha256": sha256_bytes(b),
        "raw_bytes": len(b),
        "source_rows": int(len(df)),
        "pit_rows": int(len(x)),
        "canonical_count": int(len(ids)),
        "frozen_path": str(frozen),
    }

def main() -> int:
    run_started = datetime.now(timezone.utc)
    captures = []
    capture_errors = []

    for url, ex in ((SSE_PAGE, "SSE"), (SZSE_PAGE, "SZSE")):
        try:
            captures.extend(capture_page(url, ex))
        except Exception as e:
            capture_errors.append({"exchange": ex, "error": repr(e)})

    captures = expand_complete_official_sources(captures)

    (OUT / "OFFICIAL_CAPTURE_MANIFEST.json").write_text(
        json.dumps({
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "captures": captures,
            "capture_errors": capture_errors,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    receipt: dict[str, Any] = {
        "schema": "AI_CORE_REAL_MOTHER_POOL_GATE_V2_7_24",
        "pit_date": "2026-09-17",
        "run_started_at_utc": run_started.isoformat(),
        "capture_errors": capture_errors,
        "gate": {
            "status": "INGEST_BLOCKED",
            "blocker_cleared": False,
        },
    }

    try:
        official_ids, official_meta = normalize_official(captures)
        receipt["official"] = official_meta
    except Exception as e:
        receipt["official"] = {"status": "BLOCKED", "error": repr(e)}
        official_ids = set()

    try:
        alpha_ids, alpha_meta = freeze_alphadojo()
        receipt["alphadojo"] = alpha_meta
    except Exception as e:
        receipt["alphadojo"] = {"status": "BLOCKED", "error": repr(e)}
        alpha_ids = set()

    official_ok = (
        receipt.get("official", {}).get("status") == "PASS"
        and len(official_ids) > 0
    )
    alpha_ok = (
        "canonical_count" in receipt.get("alphadojo", {})
        and len(alpha_ids) > 0
    )

    if official_ok and alpha_ok:
        o_minus_a = sorted(official_ids - alpha_ids)
        a_minus_o = sorted(alpha_ids - official_ids)
        sym = sorted(official_ids ^ alpha_ids)

        pd.DataFrame({"canonical_id": o_minus_a}).to_csv(
            NORM / "OFFICIAL_MINUS_ALPHADOJO.csv", index=False
        )
        pd.DataFrame({"canonical_id": a_minus_o}).to_csv(
            NORM / "ALPHADOJO_MINUS_OFFICIAL.csv", index=False
        )

        receipt["reconciliation"] = {
            "official_count": len(official_ids),
            "alphadojo_count": len(alpha_ids),
            "official_minus_alphadojo_count": len(o_minus_a),
            "alphadojo_minus_official_count": len(a_minus_o),
            "symmetric_diff_count": len(sym),
            "exact_equal": official_ids == alpha_ids,
        }

        # This run is on/after 2026-09-18, while the frozen PIT date is 2026-09-17.
        # A current-list equality is diagnostic unless official bytes prove historical PIT.
        capture_date_utc = datetime.now(timezone.utc).date().isoformat()
        receipt["pit_proof"] = {
            "required_pit_date": "2026-09-17",
            "capture_date_utc": capture_date_utc,
            "historical_official_pit_proven": False,
            "status": "BLOCKED_PIT_SEMANTICS_UNPROVEN",
            "note": (
                "Current official list capture can support diagnostic exact-diff, "
                "but cannot authorize 2026-09-17 PIT without historical official-list proof."
            ),
        }

        if len(sym) == 0:
            receipt["gate"] = {
                "status": "PIT_PROOF_BLOCKED_DIAGNOSTIC_EXACT_EQUAL",
                "blocker_cleared": False,
            }
        else:
            receipt["gate"] = {
                "status": "MISMATCH_BLOCKED",
                "blocker_cleared": False,
            }
    else:
        receipt["reconciliation"] = {"status": "NOT_RUN_INPUT_BLOCKED"}

    receipt["run_finished_at_utc"] = datetime.now(timezone.utc).isoformat()

    # Seal receipt over its content before receipt_sha256 field is added.
    canonical = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    receipt["receipt_sha256"] = sha256_bytes(canonical)
    rp = OUT / "REAL_MOTHER_POOL_GATE_RECEIPT_V2.7.24.json"
    rp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    # Action success means execution completed and artifacts were produced.
    # Authorization is represented only inside the receipt, never by process exit 0/1.
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
