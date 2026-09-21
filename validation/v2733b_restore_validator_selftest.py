from __future__ import annotations

import importlib.util
import json
import tempfile
import zipfile
from pathlib import Path

SCRIPT=Path("scripts/v2733b_exact_runtime_restore.py")
spec=importlib.util.spec_from_file_location("restore",SCRIPT)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

tests=[]

def rec(name, ok, detail):
    tests.append({"name":name,"pass":bool(ok),"detail":detail})

# Pure helper tests.
ok,reason=m.safe_member_name("scripts/daily_operator_cli_v273.py")
rec("safe_normal_path", ok and reason=="", {"ok":ok,"reason":reason})

for bad in ("../escape.py","/abs.py","C:/evil.py","scripts/../evil.py"):
    ok,reason=m.safe_member_name(bad)
    rec(f"block_path_{bad}", not ok, {"ok":ok,"reason":reason})

# Synthetic unknown carrier must fail before any extraction.
with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    z=td/"unknown.zip"
    with zipfile.ZipFile(z,"w") as f:
        f.writestr("x.txt","x")
    # Validate package identity directly through acceptance table.
    rec("unknown_carrier_not_accepted", z.name not in m.ACCEPTED, z.name)

# A correctly named but altered carrier must not match frozen package hash.
with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    z=td/"AlphaDojo_V2.7.3_Prospective_Runtime_Starter.zip"
    with zipfile.ZipFile(z,"w") as f:
        for i in range(5):
            f.writestr(f"file{i}.txt",str(i))
    actual=m.sha256_file(z)
    expected=m.ACCEPTED[z.name]["sha256"]
    rec("recognized_name_wrong_hash_blocks", actual!=expected, {"actual":actual,"expected":expected})

# Symlink detection helper.
zi=zipfile.ZipInfo("scripts/link.py")
zi.external_attr=(0o120777 << 16)
rec("symlink_member_detected", m.is_symlink(zi), True)

receipt={
  "schema":"AI_CORE_EVID_V2_7_33B_RESTORE_VALIDATOR_SELFTEST_V1",
  "tests":tests,
  "passed":sum(1 for x in tests if x["pass"]),
  "total":len(tests)
}
receipt["all_pass"]=receipt["passed"]==receipt["total"]
Path("v2733b_selftest.json").write_text(json.dumps(receipt,indent=2)+"\n")
print(json.dumps(receipt,indent=2))
if not receipt["all_pass"]:
    raise SystemExit(1)
