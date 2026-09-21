from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

OUT = Path("v282_capco_sector_probe")
RAW = OUT / "raw"
OUT.mkdir(exist_ok=True)
RAW.mkdir(exist_ok=True)

SOURCES = [
    {
        "label": "2024H1",
        "publication_date": "2024-09-30",
        "page_url": "https://www.capco.org.cn/xhgg/hyfl/hyfljg/202409/20240930/j_2024093015525600017276828969068447.html",
    },
    {
        "label": "2024H2",
        "publication_date": "2025-04-18",
        "page_url": "https://www.capco.org.cn/xhgg/hyfl/hyfljg/202504/20250418/j_2025041815003000017449597508305299.html",
    },
    {
        "label": "2025H1",
        "publication_date": "2025-09-30",
        "page_url": "https://www.capco.org.cn/xhgg/hyfl/hyfljg/202509/20250930/j_2025093014371200017592143530187679.html",
    },
    {
        "label": "2025H2",
        "publication_date": "2026-04-03",
        "page_url": "https://www.capco.org.cn/xhgg/hyfl/hyfljg/202604/20260403/j_2026040315001700017751997384265508.html",
    },
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)
CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_json_sha(obj: dict) -> str:
    b = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return sha_bytes(b)


def deterministic_tar_gz(files: list[Path], dest: Path) -> None:
    with dest.open("wb") as raw_out:
        with gzip.GzipFile(fileobj=raw_out, mode="wb", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tf:
                for p in sorted(files, key=lambda x: x.name):
                    data = p.read_bytes()
                    ti = tarfile.TarInfo(name=f"raw/{p.name}")
                    ti.size = len(data)
                    ti.mtime = 0
                    ti.mode = 0o644
                    ti.uid = 0
                    ti.gid = 0
                    ti.uname = ""
                    ti.gname = ""
                    tf.addfile(ti, io.BytesIO(data))


def find_stock_sorted_pdf(page_url: str, html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(" ", strip=True).split())
        href = a["href"].strip()
        if ".pdf" in href.lower():
            candidates.append((text, urljoin(page_url, href)))
    exact = [
        (text, url)
        for text, url in candidates
        if "按股票代码排序" in text
    ]
    if len(exact) != 1:
        raise RuntimeError(
            f"{page_url}: expected exactly one stock-code-sorted PDF, "
            f"found {len(exact)} candidates={candidates}"
        )
    return exact[0]


def pdf_text_diagnostics(pdf_bytes: bytes) -> dict:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    texts = []
    sample_lines = []
    codes = set()
    for page in reader.pages:
        text = page.extract_text() or ""
        texts.append(text)
        for line in text.splitlines():
            line = " ".join(line.split())
            found = CODE_RE.findall(line)
            if found:
                codes.update(found)
                if len(sample_lines) < 30:
                    sample_lines.append(line)
    full = "\n".join(texts)
    return {
        "pages": len(reader.pages),
        "text_chars": len(full),
        "unique_six_digit_codes": len(codes),
        "sample_lines": sample_lines,
    }


def main() -> None:
    started = datetime.now(timezone.utc)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        }
    )

    inventory = []
    samples = {}
    failures = []
    raw_files = []

    for src in SOURCES:
        label = src["label"]
        page_url = src["page_url"]
        try:
            page = session.get(page_url, timeout=30)
            page.raise_for_status()
            page.encoding = page.apparent_encoding or page.encoding
            html = page.text
            anchor_text, pdf_url = find_stock_sorted_pdf(page_url, html)

            pdf_resp = session.get(
                pdf_url,
                timeout=60,
                headers={"Referer": page_url, "User-Agent": UA},
            )
            pdf_resp.raise_for_status()
            pdf_bytes = pdf_resp.content
            if not pdf_bytes.startswith(b"%PDF"):
                raise RuntimeError(
                    f"{label}: resolved artifact is not a PDF; "
                    f"content_type={pdf_resp.headers.get('content-type')}"
                )

            raw_path = RAW / f"{label}_CAPCO_BY_STOCK_CODE.pdf"
            raw_path.write_bytes(pdf_bytes)
            raw_files.append(raw_path)

            diag = pdf_text_diagnostics(pdf_bytes)
            samples[label] = diag.pop("sample_lines")

            rec = {
                "label": label,
                "publication_date": src["publication_date"],
                "page_url": page_url,
                "page_http_status": page.status_code,
                "page_sha256": sha_bytes(page.content),
                "anchor_text": anchor_text,
                "pdf_url": pdf_url,
                "pdf_http_status": pdf_resp.status_code,
                "pdf_content_type": pdf_resp.headers.get("content-type", ""),
                "pdf_bytes": len(pdf_bytes),
                "pdf_sha256": sha_bytes(pdf_bytes),
                **diag,
            }
            rec["download_pass"] = (
                rec["pdf_bytes"] > 10000
                and rec["pages"] >= 1
                and rec["text_chars"] >= 10000
                and rec["unique_six_digit_codes"] >= 4000
            )
            if not rec["download_pass"]:
                failures.append(
                    f"{label}: completeness/text guard failed "
                    f"bytes={rec['pdf_bytes']} pages={rec['pages']} "
                    f"text_chars={rec['text_chars']} "
                    f"codes={rec['unique_six_digit_codes']}"
                )
            inventory.append(rec)
        except Exception as exc:
            failures.append(f"{label}: {type(exc).__name__}: {exc}")
            inventory.append(
                {
                    "label": label,
                    "publication_date": src["publication_date"],
                    "page_url": page_url,
                    "download_pass": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    inv = pd.DataFrame(inventory)
    inv_path = OUT / "V2.8.2_CAPCO_SECTOR_SOURCE_INVENTORY.csv"
    inv.to_csv(inv_path, index=False, lineterminator="\n")

    samples_path = OUT / "V2.8.2_CAPCO_SECTOR_TEXT_SAMPLES.json"
    samples_path.write_text(
        json.dumps(samples, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    tar_path = OUT / "V2.8.2_CAPCO_SECTOR_RAW_PDFS.tar.gz"
    deterministic_tar_gz(raw_files, tar_path)

    receipt = {
        "schema": "AI_CORE_EVID_V2_8_2_CAPCO_SECTOR_SOURCE_PROBE_RECEIPT_V1",
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_count": len(SOURCES),
        "downloaded_pdf_count": len(raw_files),
        "all_source_guards_pass": len(failures) == 0 and len(raw_files) == len(SOURCES),
        "completeness_guard": {
            "pdf_bytes_min": 10000,
            "pages_min": 1,
            "extractable_text_chars_min": 10000,
            "unique_six_digit_codes_min": 4000,
            "role": "implementation/source-completeness guard only; not a strategy promotion threshold",
        },
        "inventory_sha256": sha_bytes(inv_path.read_bytes()),
        "text_samples_sha256": sha_bytes(samples_path.read_bytes()),
        "raw_pdf_tar_sha256": sha_bytes(tar_path.read_bytes()),
        "raw_pdf_tar_bytes": tar_path.stat().st_size,
        "failures": failures,
        "next_step": (
            "BUILD_DETERMINISTIC_CAPCO_TABLE_PARSER"
            if len(failures) == 0 and len(raw_files) == len(SOURCES)
            else "FIX_SOURCE_MATERIALIZATION_OR_TEXT_EXTRACTION"
        ),
    }
    receipt["receipt_sha256"] = stable_json_sha(receipt)
    receipt_path = OUT / "V2.8.2_CAPCO_SECTOR_SOURCE_PROBE_RECEIPT.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)
    print(inv.to_string(index=False), flush=True)
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
