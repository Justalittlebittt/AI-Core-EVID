from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

ACCEPTED = {
    "AlphaDojo_V2.7.3_Prospective_Runtime_Starter.zip": {
        "sha256": "4e4e13276c2e68b7b834fccf0a710a31d020ddad3985711a9d1aabfb826ce22f",
        "members": 5,
    },
    "AlphaDojo_Model_Rebuild_V2.7.3.zip": {
        "sha256": "60c3aee8577693ee85ae8de46810ce7b2ed238a666ce0ae9f5aea2de85ad47ee",
        "members": 51,
    },
}

CRITICAL = {
    "scripts/daily_operator_cli_v273.py": "259bc9c481b7165388767ad73aa5de2e35ba987b62b568ce9013e3157a0b5fd8",
    "scripts/daily_source_gate_v273.py": "e2a2a52da20fccd32b2f85be794a93d98fb74a88276c57cd9e7b4da7b1e8b7f9",
    "scripts/append_only_ledgers_v273.py": "8a6e05e0d52d6fa5e3811b10fcc3985aa69a9fb3e16c03513825731d97cfc6b8",
    "scripts/init_runtime_v273.py": "8f2bfc4c289af2306d10f38f6609a8d09382b5e9091ae060364adc47a075501d",
    "scripts/setup_engine_v273.py": "97b8befb2d4b04992c87edec708471f433ed9735a5f0dbf3aa73c64e0b345830",
    "scripts/prospective_daily_runner_v1.py": "6a76dfa51b1446918581f0b4fe7022a73a4f9f0bb491b23467a7edfc62dd5ce2",
}

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def safe_member_name(name: str) -> tuple[bool, str]:
    p = PurePosixPath(name)
    if not name or name.startswith("/") or name.startswith("\\"):
        return False, "ABSOLUTE_OR_EMPTY_PATH"
    if any(part in ("", ".", "..") for part in p.parts):
        return False, "TRAVERSAL_OR_EMPTY_COMPONENT"
    if ":" in p.parts[0]:
        return False, "DRIVE_PATH"
    return True, ""

def is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True, dest="zip_path")
    ap.add_argument("--out", default="recovery_work/v2733b")
    args = ap.parse_args()

    carrier = Path(args.zip_path)
    out = Path(args.out)
    staging = out / "staging"
    if out.exists():
        shutil.rmtree(out)
    staging.mkdir(parents=True)

    result = {
        "schema": "AI_CORE_EVID_V2_7_33B_EXACT_BYTE_RESTORE_RECEIPT_V1",
        "carrier": str(carrier),
        "carrier_filename": carrier.name,
        "gate_a_exact_bytes": {},
        "critical_members": {},
        "member_manifest": [],
        "promotion_authorized": False,
        "activation_authorized": False,
    }

    expected = ACCEPTED.get(carrier.name)
    if expected is None:
        result["gate_a_exact_bytes"] = {
            "status": "BLOCKED_NOT_ORIGINAL_BYTES",
            "reason": "UNRECOGNIZED_CARRIER_FILENAME",
        }
        (out / "V2.7.33B_RESTORE_RECEIPT.json").write_text(json.dumps(result, indent=2) + "\n")
        return 2

    actual_zip_sha = sha256_file(carrier)
    result["carrier_sha256"] = actual_zip_sha
    result["expected_carrier_sha256"] = expected["sha256"]
    if actual_zip_sha != expected["sha256"]:
        result["gate_a_exact_bytes"] = {
            "status": "BLOCKED_NOT_ORIGINAL_BYTES",
            "reason": "CARRIER_SHA256_MISMATCH",
        }
        (out / "V2.7.33B_RESTORE_RECEIPT.json").write_text(json.dumps(result, indent=2) + "\n")
        return 3

    with zipfile.ZipFile(carrier, "r") as zf:
        infos = zf.infolist()
        if len(infos) != expected["members"]:
            result["gate_a_exact_bytes"] = {
                "status": "BLOCKED_NOT_ORIGINAL_BYTES",
                "reason": "ZIP_MEMBER_COUNT_MISMATCH",
                "actual": len(infos),
                "expected": expected["members"],
            }
            (out / "V2.7.33B_RESTORE_RECEIPT.json").write_text(json.dumps(result, indent=2) + "\n")
            return 4

        bad_crc = zf.testzip()
        if bad_crc is not None:
            result["gate_a_exact_bytes"] = {
                "status": "BLOCKED_NOT_ORIGINAL_BYTES",
                "reason": "ZIP_CRC_FAILURE",
                "member": bad_crc,
            }
            (out / "V2.7.33B_RESTORE_RECEIPT.json").write_text(json.dumps(result, indent=2) + "\n")
            return 5

        names = [i.filename for i in infos]
        if len(set(names)) != len(names):
            result["gate_a_exact_bytes"] = {
                "status": "BLOCKED_NOT_ORIGINAL_BYTES",
                "reason": "DUPLICATE_MEMBER_PATH",
            }
            (out / "V2.7.33B_RESTORE_RECEIPT.json").write_text(json.dumps(result, indent=2) + "\n")
            return 6

        for info in infos:
            ok, reason = safe_member_name(info.filename)
            if not ok or is_symlink(info):
                result["gate_a_exact_bytes"] = {
                    "status": "BLOCKED_NOT_ORIGINAL_BYTES",
                    "reason": reason or "SYMLINK_MEMBER",
                    "member": info.filename,
                }
                (out / "V2.7.33B_RESTORE_RECEIPT.json").write_text(json.dumps(result, indent=2) + "\n")
                return 7

            b = zf.read(info.filename)
            member_sha = sha256_bytes(b)
            result["member_manifest"].append({
                "path": info.filename,
                "bytes": len(b),
                "sha256": member_sha,
            })
            if info.filename in CRITICAL:
                expected_sha = CRITICAL[info.filename]
                result["critical_members"][info.filename] = {
                    "expected_sha256": expected_sha,
                    "actual_sha256": member_sha,
                    "pass": member_sha == expected_sha,
                }
                if member_sha != expected_sha:
                    result["gate_a_exact_bytes"] = {
                        "status": "BLOCKED_NOT_ORIGINAL_BYTES",
                        "reason": "CRITICAL_MEMBER_SHA256_MISMATCH",
                        "member": info.filename,
                    }
                    (out / "V2.7.33B_RESTORE_RECEIPT.json").write_text(json.dumps(result, indent=2) + "\n")
                    return 8

        zf.extractall(staging)

    result["gate_a_exact_bytes"] = {
        "status": "EXACT_ORIGINAL_BYTES_PASS",
        "carrier_sha256_match": True,
        "member_count_match": True,
        "crc_pass": True,
        "path_safety_pass": True,
        "critical_members_present_and_checked": sorted(result["critical_members"]),
    }
    result["gate_b_compatibility_static_audit"] = {
        "status": "PENDING_STATIC_AUDIT",
        "note": "Recovered bytes are staged only. Do not execute or promote until a separate compatibility audit passes.",
    }
    result["promotion_authorized"] = False
    result["activation_authorized"] = False
    (out / "V2.7.33B_RESTORE_RECEIPT.json").write_text(json.dumps(result, indent=2) + "\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
