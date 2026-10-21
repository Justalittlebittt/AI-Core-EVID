"""No-network source-adapter regression: mock both index feeds and verify no partial snapshot."""
import csv
import json
import importlib.metadata
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ashare_market_risk_akshare_fetch as adapter


class Frame:
    empty = False
    columns = ["日期", "收盘"]
    def iterrows(self):
        for n in range(3):
            yield n, {"日期": f"2024-01-0{n+2}", "收盘": 1000 + n}


def main():
    mock = types.ModuleType("akshare")
    mock.index_zh_a_hist = lambda **kw: Frame()
    old_module = sys.modules.get("akshare")
    sys.modules["akshare"] = mock
    old_version = importlib.metadata.version
    importlib.metadata.version = lambda _: "synthetic-test"
    try:
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "snapshot.csv"
            sys.argv = ["fetch", "--start-date", "2024-01-01", "--end-date",
                        "2024-01-05", "--output-csv", str(target)]
            assert adapter.main() == 0
            rows = list(csv.DictReader(target.open(encoding="utf-8")))
            assert len(rows) == 6
            assert {r["index_id"] for r in rows} == {"000300.SH", "000688.SH"}
            manifest = target.with_name(target.name + ".manifest.json")
            assert manifest.exists()
            meta = json.loads(manifest.read_text(encoding="utf-8"))
            assert meta["captured_at_utc"]
            assert all(r["retrieved_at_utc"] == meta["captured_at_utc"] for r in rows)
            assert all(r["retrieved_at_utc"] for r in rows)

            # An existing manifest must never be overwritten, even if the CSV is absent.
            target.unlink()
            before = manifest.read_bytes()
            try:
                adapter.main()
                raise AssertionError("existing manifest must reject acquisition")
            except FileExistsError as ex:
                assert "IMMUTABLE_SNAPSHOT_MANIFEST_ALREADY_EXISTS" in str(ex)
            assert manifest.read_bytes() == before
            assert not target.exists()

            def failure(**kw):
                return None if kw["symbol"] == "000688" else Frame()
            mock.index_zh_a_hist = failure
            target2 = Path(td) / "failure.csv"
            sys.argv[-1] = str(target2)
            try:
                adapter.main()
                raise AssertionError("second source failure must block")
            except RuntimeError as ex:
                assert "INDEX_SOURCE_UNAVAILABLE:000688" in str(ex)
            assert not target2.exists()
            assert not target2.with_name(target2.name + ".manifest.json").exists()
    finally:
        importlib.metadata.version = old_version
        if old_module is None:
            del sys.modules["akshare"]
        else:
            sys.modules["akshare"] = old_module
    print("ASHARE_FREE_SOURCE_ADAPTER_MOCK: PASS (no provider contacted)")


if __name__ == "__main__":
    main()
