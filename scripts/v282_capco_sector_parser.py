from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

OUT = Path("v282_capco_sector_parser")
OUT.mkdir(exist_ok=True)

RAW_TAR = Path("evidence/V2.8.2_CAPCO_SECTOR_RAW_PDFS.tar.gz")
RAW_TAR_SHA = "cf7c8ce0614fc3ea5a85effa4df8daeaf7cd143d8650ec3e9850cd5480539c5c"
SOURCE_RECEIPT = Path("evidence/V2.8.2_CAPCO_SECTOR_SOURCE_PROBE_RECEIPT.json")
SOURCE_RECEIPT_SEAL = "0b252b00764c0b252d8f377d83acebde9e32541f9ac1e60c7b1f1aecc8575a10"
SOURCE_INVENTORY = Path("evidence/V2.8.2_CAPCO_SECTOR_SOURCE_INVENTORY.csv")
PIT_PATH = Path("evidence/V2.8.1_PIT_MEMBERSHIP_INTERVALS.csv")
PIT_SHA = "52087fa1e68577fae214f8fa18f1b20a0b30f41b6b6bf5592327c25c2800cfc1"
CAL2025 = Path("evidence/V2.8.1_JOINT_A_SHARE_CALENDAR_2025_CONTRACT.json")
CAL2026 = Path("evidence/V2.7.32_JOINT_A_SHARE_TRADING_CALENDAR_2026.json")
SAMPLE_START = date(2025, 1, 2)
SAMPLE_END = date(2026, 9, 9)

TOP_NAMES = {
    "A": "农、林、牧、渔业",
    "B": "采矿业",
    "C": "制造业",
    "D": "电力、热力、燃气及水生产和供应业",
    "E": "建筑业",
    "F": "批发和零售业",
    "G": "交通运输、仓储和邮政业",
    "H": "住宿和餐饮业",
    "I": "信息传输、软件和信息技术服务业",
    "J": "金融业",
    "K": "房地产业",
    "L": "租赁和商务服务业",
    "M": "科学研究和技术服务业",
    "N": "水利、环境和公共设施管理业",
    "O": "居民服务、修理和其他服务业",
    "P": "教育",
    "Q": "卫生和社会工作",
    "R": "文化、体育和娱乐业",
    "S": "综合",
}
CODE_START_RE = re.compile(r"^(\d{6})(?!\d)\s*(.*)$")
STANDALONE_TOP_RE = re.compile(r"(?:^|\s)([A-S])(?=\s)")
SUBCODE_RE = re.compile(r"^C[A-Z]$")
MAJOR_RE = re.compile(r"^\d{2}$")


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def stable_json_sha(obj: dict) -> str:
    b = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return sha_bytes(b)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_source_receipt() -> dict:
    obj = read_json(SOURCE_RECEIPT)
    embedded = obj.get("receipt_sha256")
    unsigned = dict(obj)
    unsigned.pop("receipt_sha256", None)
    computed = stable_json_sha(unsigned)
    if embedded != SOURCE_RECEIPT_SEAL or computed != SOURCE_RECEIPT_SEAL:
        raise RuntimeError(
            f"source receipt seal mismatch embedded={embedded} computed={computed}"
        )
    if not obj.get("all_source_guards_pass"):
        raise RuntimeError("source probe receipt is not PASS")
    return obj


def build_joint_calendar() -> list[date]:
    c25 = read_json(CAL2025)
    closed: set[date] = set()
    for r in c25["closure_ranges"]:
        d0 = date.fromisoformat(r["start"])
        d1 = date.fromisoformat(r["end"])
        d = d0
        while d <= d1:
            closed.add(d)
            d += timedelta(days=1)
    for x in c25.get("explicit_weekend_closures", []):
        closed.add(date.fromisoformat(x))

    dates25 = []
    d = date(2025, 1, 1)
    while d <= date(2025, 12, 31):
        if d.weekday() < 5 and d not in closed:
            dates25.append(d)
        d += timedelta(days=1)

    c26 = read_json(CAL2026)
    dates26 = [
        date.fromisoformat(x["date"])
        for x in c26["dates"]
        if x["is_joint_a_share_trading_day"]
    ]
    cal = sorted(set(dates25 + dates26))
    if not cal or cal[0] != SAMPLE_START:
        raise RuntimeError(f"unexpected joint calendar start {cal[:3]}")
    return [d for d in cal if SAMPLE_START <= d <= SAMPLE_END]


def effective_date(publication_date: date, calendar: list[date]) -> date:
    if publication_date < calendar[0]:
        return calendar[0]
    candidates = [d for d in calendar if d > publication_date]
    if not candidates:
        raise RuntimeError(f"no research effective date after {publication_date}")
    return candidates[0]


def normalize_line(s: str) -> str:
    s = s.replace("\u3000", " ").replace("\xa0", " ")
    return " ".join(s.split())


def is_noise_line(line: str) -> bool:
    if not line:
        return True
    compact = line.replace(" ", "")
    if compact.isdigit() and len(compact) <= 4:
        return True
    noise = (
        "上市公司行业分类结果",
        "股票代码",
        "股票简称",
        "门类代码",
        "门类名称",
        "制造业次类",
        "大类代码",
        "大类名称",
        "中国上市公司协会",
    )
    return any(x in compact for x in noise)


def extract_logical_rows(pdf_bytes: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    rows: list[str] = []
    for page in reader.pages:
        current = None
        text = page.extract_text() or ""
        for raw in text.splitlines():
            line = normalize_line(raw)
            if not line:
                continue
            m = CODE_START_RE.match(line)
            if m:
                if current is not None:
                    rows.append(current)
                current = line
            elif current is not None and not is_noise_line(line):
                current = f"{current} {line}"
        if current is not None:
            rows.append(current)
    return rows


def locate_top_code(tail: str) -> tuple[str, int, int]:
    padded = " " + tail
    for m in STANDALONE_TOP_RE.finditer(padded):
        code = m.group(1)
        after = padded[m.end():].replace(" ", "")
        prefix = TOP_NAMES[code].replace(" ", "")[:2]
        if after.startswith(prefix):
            start = max(0, m.start() - 1)
            end = max(0, m.end() - 1)
            return code, start, end
    raise ValueError("cannot locate top-level industry code")


def parse_row(label: str, publication_date: str, row: str) -> dict:
    m = CODE_START_RE.match(row)
    if not m:
        raise ValueError("row does not start with six-digit code")
    code = m.group(1)
    tail = normalize_line(m.group(2))
    top_code, start, end = locate_top_code(tail)
    company_name = tail[:start].replace(" ", "").strip()
    if not company_name:
        raise ValueError("empty company name")

    after = normalize_line(tail[end:])
    tokens = after.split()
    top_name = TOP_NAMES[top_code]

    subcode = ""
    subname = ""
    major_code = ""
    major_name = ""

    if top_code == "C":
        sub_i = next((i for i, t in enumerate(tokens) if SUBCODE_RE.fullmatch(t)), None)
        if sub_i is None:
            raise ValueError("manufacturing row missing subcode")
        major_i = next(
            (i for i in range(sub_i + 1, len(tokens)) if MAJOR_RE.fullmatch(tokens[i])),
            None,
        )
        if major_i is None:
            raise ValueError("manufacturing row missing major code")
        subcode = tokens[sub_i]
        subname = "".join(tokens[sub_i + 1:major_i]).strip()
        major_code = tokens[major_i]
        major_name = "".join(tokens[major_i + 1:]).strip()
        if not subname:
            raise ValueError("manufacturing row missing subname")
        context_code = subcode
        context_name = subname
    else:
        major_i = next(
            (i for i, t in enumerate(tokens) if MAJOR_RE.fullmatch(t)),
            None,
        )
        if major_i is not None:
            major_code = tokens[major_i]
            major_name = "".join(tokens[major_i + 1:]).strip()
        context_code = top_code
        context_name = top_name

    return {
        "snapshot_label": label,
        "publication_date": publication_date,
        "security_code": code,
        "company_name": company_name,
        "top_code": top_code,
        "top_name": top_name,
        "manufacturing_subcode": subcode,
        "manufacturing_subname": subname,
        "major_code": major_code,
        "major_name": major_name,
        "context_code": context_code,
        "context_name": context_name,
        "raw_logical_row": row,
    }


def main() -> None:
    started = datetime.now(timezone.utc)
    verify_source_receipt()
    if sha_file(RAW_TAR) != RAW_TAR_SHA:
        raise RuntimeError("frozen CAPCO raw tar SHA mismatch")
    if sha_file(PIT_PATH) != PIT_SHA:
        raise RuntimeError("PIT membership interval SHA mismatch")

    inventory = pd.read_csv(SOURCE_INVENTORY, dtype=str).fillna("")
    expected_labels = inventory["label"].tolist()
    calendar = build_joint_calendar()

    pdf_by_label: dict[str, bytes] = {}
    with tarfile.open(RAW_TAR, "r:gz") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            name = Path(member.name).name
            m = re.match(r"^(\d{4}H[12])_CAPCO_BY_STOCK_CODE\.pdf$", name)
            if not m:
                continue
            f = tf.extractfile(member)
            if f is None:
                continue
            pdf_by_label[m.group(1)] = f.read()

    rows = []
    failures = []
    parse_diag = []
    effective = []

    for _, src in inventory.iterrows():
        label = src["label"]
        pub = date.fromisoformat(src["publication_date"])
        if label not in pdf_by_label:
            raise RuntimeError(f"missing frozen PDF for {label}")
        pdf = pdf_by_label[label]
        if sha_bytes(pdf) != src["pdf_sha256"]:
            raise RuntimeError(f"{label} PDF SHA mismatch")

        logical_rows = extract_logical_rows(pdf)
        parsed = []
        local_failures = []
        for row in logical_rows:
            try:
                parsed.append(parse_row(label, src["publication_date"], row))
            except Exception as exc:
                local_failures.append(
                    {
                        "snapshot_label": label,
                        "raw_logical_row": row,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        p = pd.DataFrame(parsed)
        duplicate_codes = (
            int(p["security_code"].duplicated().sum()) if len(p) else 0
        )
        unique_codes = int(p["security_code"].nunique()) if len(p) else 0
        context_missing = int(
            (p["context_code"].astype(str).str.len() == 0).sum()
        ) if len(p) else 0

        probe_unique = int(src["unique_six_digit_codes"])
        diag = {
            "snapshot_label": label,
            "logical_rows": len(logical_rows),
            "parsed_rows": len(parsed),
            "parse_failures": len(local_failures),
            "duplicate_security_codes": duplicate_codes,
            "unique_parsed_codes": unique_codes,
            "probe_unique_six_digit_codes": probe_unique,
            "context_missing": context_missing,
            "exact_code_cardinality_match_probe": unique_codes == probe_unique,
        }
        parse_diag.append(diag)
        failures.extend(local_failures)
        rows.extend(parsed)

        eff = effective_date(pub, calendar)
        effective.append(
            {
                "snapshot_label": label,
                "publication_date": pub.isoformat(),
                "research_effective_date": eff.isoformat(),
            }
        )

    parsed_df = pd.DataFrame(rows)
    fail_df = pd.DataFrame(
        failures,
        columns=["snapshot_label", "raw_logical_row", "error"],
    )
    diag_df = pd.DataFrame(parse_diag)

    if expected_labels != [x["snapshot_label"] for x in effective]:
        raise RuntimeError("source label order mismatch")

    for i, rec in enumerate(effective):
        start = date.fromisoformat(rec["research_effective_date"])
        next_start = (
            date.fromisoformat(effective[i + 1]["research_effective_date"])
            if i + 1 < len(effective)
            else None
        )
        active_end = SAMPLE_END if next_start is None else max(
            d for d in calendar if d < next_start
        )
        rec["research_effective_end_date"] = active_end.isoformat()

    intervals = pd.DataFrame(effective)

    pit = pd.read_csv(PIT_PATH, dtype=str).fillna("")
    required = {
        "canonical_security_id",
        "exchange",
        "security_code",
        "official_list_date",
        "official_delist_date",
    }
    if not required.issubset(pit.columns):
        raise RuntimeError(f"PIT columns missing {required - set(pit.columns)}")
    pit = pit[pit["exchange"].isin(["SSE", "SZSE"])].copy()
    pit["list_date"] = pd.to_datetime(pit["official_list_date"], errors="raise").dt.date
    pit["delist_date"] = pd.to_datetime(
        pit["official_delist_date"].replace("", pd.NA), errors="coerce"
    ).dt.date

    coverage = []
    for rec in effective:
        label = rec["snapshot_label"]
        eff = date.fromisoformat(rec["research_effective_date"])
        active = pit[
            (pit["list_date"] <= eff)
            & (pit["delist_date"].isna() | (pit["delist_date"] >= eff))
        ]
        codes = set(
            parsed_df.loc[
                parsed_df["snapshot_label"].eq(label), "security_code"
            ].astype(str)
        )
        active_codes = set(active["security_code"].astype(str))
        mapped = active_codes & codes
        missing = sorted(active_codes - codes)
        coverage.append(
            {
                "snapshot_label": label,
                "research_effective_date": eff.isoformat(),
                "active_official_sse_szse_codes": len(active_codes),
                "mapped_active_codes": len(mapped),
                "missing_active_codes": len(missing),
                "active_code_coverage": (
                    len(mapped) / len(active_codes) if active_codes else 0.0
                ),
                "missing_examples": "|".join(missing[:30]),
            }
        )
    coverage_df = pd.DataFrame(coverage)

    structural_pass = bool(
        len(failures) == 0
        and len(diag_df) == len(expected_labels)
        and diag_df["duplicate_security_codes"].eq(0).all()
        and diag_df["context_missing"].eq(0).all()
        and diag_df["exact_code_cardinality_match_probe"].all()
    )

    rows_path = OUT / "V2.8.2_CAPCO_SECTOR_SNAPSHOT_ROWS.csv"
    intervals_path = OUT / "V2.8.2_CAPCO_SECTOR_EFFECTIVE_INTERVALS.csv"
    fail_path = OUT / "V2.8.2_CAPCO_SECTOR_PARSE_FAILURES.csv"
    coverage_path = OUT / "V2.8.2_CAPCO_SECTOR_PIT_COVERAGE.csv"

    parsed_df.to_csv(rows_path, index=False, lineterminator="\n")
    intervals.to_csv(intervals_path, index=False, lineterminator="\n")
    fail_df.to_csv(fail_path, index=False, lineterminator="\n")
    coverage_df.to_csv(coverage_path, index=False, lineterminator="\n")

    receipt = {
        "schema": "AI_CORE_EVID_V2_8_2_CAPCO_SECTOR_PARSER_RECEIPT_V1",
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_probe_receipt_seal": SOURCE_RECEIPT_SEAL,
        "raw_tar_sha256": RAW_TAR_SHA,
        "pit_membership_sha256": PIT_SHA,
        "calendar_2025_file_sha256": sha_file(CAL2025),
        "calendar_2026_file_sha256": sha_file(CAL2026),
        "snapshot_count": len(expected_labels),
        "parsed_row_count": int(len(parsed_df)),
        "parse_failure_count": int(len(fail_df)),
        "structural_parser_pass": structural_pass,
        "diagnostics": parse_diag,
        "pit_coverage": coverage,
        "rows_sha256": sha_file(rows_path),
        "effective_intervals_sha256": sha_file(intervals_path),
        "parse_failures_sha256": sha_file(fail_path),
        "pit_coverage_sha256": sha_file(coverage_path),
        "sector_context_rule": "Use manufacturing subcategory code when top_code=C; otherwise use CAPCO top-level category code.",
        "temporal_rule": "A snapshot is usable only from the first joint A-share trading date strictly after publication; pre-sample publication is usable from sample start.",
        "missing_sector_policy_for_later_analysis": "Do not backfill from a future CAPCO snapshot. Preserve unmapped active securities as UNKNOWN context and report coverage.",
        "next_step": (
            "BUILD_V2_8_2_MARKET_AND_SECTOR_CONDITIONAL_DIAGNOSTIC"
            if structural_pass
            else "FIX_CAPCO_PARSER_IMPLEMENTATION"
        ),
    }
    receipt["receipt_sha256"] = stable_json_sha(receipt)
    receipt_path = OUT / "V2.8.2_CAPCO_SECTOR_PARSER_RECEIPT.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)
    print(diag_df.to_string(index=False), flush=True)
    print(coverage_df.to_string(index=False), flush=True)

    if not structural_pass:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
