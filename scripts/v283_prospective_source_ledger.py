from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import HfApi

OUT = Path("evidence/v283_source_pins")
TRACKED = [
    ("AlphaDojo/dojo_stock_kline", "data.parquet"),
    ("AlphaDojo/dojo_benchmark_kline", "data.parquet"),
]

def stable_sha256(obj) -> str:
    b = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(b).hexdigest()

def normalize_lfs(lfs):
    if isinstance(lfs, dict):
        return {k: lfs.get(k) for k in ("sha256", "size", "pointer_size") if lfs.get(k) is not None}
    if lfs is None:
        return {}
    return {
        k: getattr(lfs, k)
        for k in ("sha256", "size", "pointer_size")
        if getattr(lfs, k, None) is not None
    }

def repo_pin(api: HfApi, repo_id: str, target_file: str) -> dict:
    info = api.dataset_info(repo_id=repo_id, files_metadata=True)
    target = next((s for s in (info.siblings or []) if s.rfilename == target_file), None)
    if target is None:
        raise RuntimeError(f"{repo_id}: target file missing: {target_file}")
    lfs = normalize_lfs(getattr(target, "lfs", None))
    sha = str(lfs.get("sha256") or "")
    if len(sha) != 64:
        raise RuntimeError(f"{repo_id}: target LFS sha256 unavailable")
    return {
        "repo_id": repo_id,
        "repo_type": "dataset",
        "revision_sha": str(info.sha),
        "repo_last_modified": str(info.last_modified),
        "target_file": target_file,
        "target_size": int(getattr(target, "size", 0) or lfs.get("size") or 0),
        "target_lfs_sha256": sha,
    }

def identity_tuple(receipt: dict):
    rows = receipt.get("sources") or []
    return tuple(
        (r["repo_id"], r["revision_sha"], r["target_lfs_sha256"])
        for r in sorted(rows, key=lambda x: x["repo_id"])
    )

def existing_receipts() -> list[dict]:
    if not OUT.exists():
        return []
    rows = []
    for p in sorted(OUT.glob("*.json")):
        obj = json.loads(p.read_text(encoding="utf-8"))
        obj["_path"] = str(p)
        rows.append(obj)
    return rows

def build_receipt(api: HfApi) -> dict:
    observed = datetime.now(timezone.utc).isoformat()
    sources = [repo_pin(api, repo, target) for repo, target in TRACKED]
    core = {
        "schema": "AI_CORE_EVID_V2_8_3_SOURCE_PIN_RECEIPT_V1",
        "version": "V2.8.3",
        "runner_observed_at_utc_descriptive": observed,
        "authoritative_observation_time_rule": "GitHub committed_at timestamp of this capture-file creation commit",
        "sources": sources,
        "no_full_parquet_download": True,
        "confirmatory_result_effect": "NONE",
    }
    core["source_identity_sha256"] = stable_sha256({"sources": sources})
    core["receipt_sha256"] = stable_sha256(core)
    return core

def capture() -> None:
    api = HfApi()
    receipt = build_receipt(api)
    prior = existing_receipts()
    if prior and identity_tuple(prior[-1]) == identity_tuple(receipt):
        print(json.dumps({
            "status": "NO_CHANGE",
            "latest": prior[-1]["_path"],
            "source_identity_sha256": receipt["source_identity_sha256"],
        }, ensure_ascii=False, indent=2))
        return
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = receipt["source_identity_sha256"][:16]
    p = OUT / f"{stamp}_{suffix}.json"
    if p.exists():
        raise RuntimeError("capture filename collision")
    p.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "NEW_SOURCE_IDENTITY_FROZEN",
        "path": str(p),
        "source_identity_sha256": receipt["source_identity_sha256"],
    }, ensure_ascii=False, indent=2))

class FakeSibling:
    def __init__(self, name, size, lfs):
        self.rfilename = name
        self.size = size
        self.lfs = lfs

class FakeInfo:
    def __init__(self, sha, modified, siblings):
        self.sha = sha
        self.last_modified = modified
        self.siblings = siblings

class FakeApi:
    def dataset_info(self, repo_id, files_metadata=True):
        token = "a" if repo_id.endswith("stock_kline") else "b"
        return FakeInfo(
            token * 40,
            "2026-09-21 00:00:00+00:00",
            [FakeSibling("data.parquet", 123, {"sha256": token * 64, "size": 123, "pointer_size": 130})],
        )

def self_test() -> None:
    tests = []
    def check(name, condition):
        tests.append({"name": name, "pass": bool(condition)})
    api = FakeApi()
    a = repo_pin(api, *TRACKED[0])
    b = repo_pin(api, *TRACKED[1])
    check("S01_stock_pin_revision", a["revision_sha"] == "a" * 40)
    check("S02_stock_pin_lfs", a["target_lfs_sha256"] == "a" * 64)
    check("S03_benchmark_pin_revision", b["revision_sha"] == "b" * 40)
    check("S04_identity_order_invariant",
          identity_tuple({"sources": [a, b]}) == identity_tuple({"sources": [b, a]}))
    r = {
        "schema": "AI_CORE_EVID_V2_8_3_SOURCE_PIN_RECEIPT_V1",
        "sources": [a, b],
    }
    check("S05_stable_hash_deterministic", stable_sha256(r) == stable_sha256(r))
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    forbidden_calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
        if name == "hf_hub_download":
            forbidden_calls.append(name)
    check("S06_no_full_download_path", not forbidden_calls)
    result = {
        "schema": "AI_CORE_EVID_V2_8_3_SOURCE_LEDGER_RUNNER_SELFTEST_V1",
        "tests": tests,
        "passed": sum(1 for x in tests if x["pass"]),
        "total": len(tests),
        "all_pass": all(x["pass"] for x in tests),
    }
    result["receipt_sha256"] = stable_sha256(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["self-test", "capture"])
    args = ap.parse_args()
    if args.command == "self-test":
        self_test()
    else:
        capture()

if __name__ == "__main__":
    main()
