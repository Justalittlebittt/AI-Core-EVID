from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import tempfile
from pathlib import Path

import v284_effective_e_state_resolver as er

PIT_ROOT=Path("evidence/v283_pit_authority")
CID_RE=re.compile(r"^(SSE|SZSE):\d{6}$")

def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def load_u_authority(signal_date:str,root:Path=PIT_ROOT)->tuple[set[str],dict]:
    ap=root/f"{signal_date}_PIT_DATE_AUTHORITY.json"
    if not ap.exists():
        raise RuntimeError("BLOCK_NO_PIT_U_AUTHORITY")
    obj=json.loads(ap.read_text(encoding="utf-8"))
    if obj.get("signal_date")!=signal_date or obj.get("status")!="PASS":
        raise RuntimeError("BLOCK_U_AUTHORITY")
    raw=str(obj.get("universe_snapshot_file") or "").strip()
    expected=str(obj.get("universe_snapshot_sha256") or "").strip()
    if not raw or not re.fullmatch(r"[0-9a-f]{64}",expected):
        raise RuntimeError("BLOCK_U_AUTHORITY")
    up=Path(raw)
    if not up.exists() or sha_file(up)!=expected:
        raise RuntimeError("BLOCK_U_AUTHORITY")
    rows=list(csv.DictReader(up.read_text(encoding="utf-8").splitlines()))
    if not rows or "canonical_security_id" not in rows[0]:
        raise RuntimeError("BLOCK_U_AUTHORITY")
    ids=[str(r.get("canonical_security_id") or "").strip() for r in rows]
    if any(not CID_RE.fullmatch(x) for x in ids) or len(ids)!=len(set(ids)):
        raise RuntimeError("BLOCK_U_AUTHORITY")
    return set(ids),{
        "authority_file":str(ap),
        "universe_snapshot_file":str(up),
        "universe_snapshot_sha256":expected,
        "universe_count":len(ids),
    }

def assess(canonical_security_id:str,signal_date:str,u_ids:set[str],e_rows:list[dict]|None=None)->dict:
    if not CID_RE.fullmatch(canonical_security_id):
        raise RuntimeError("BLOCK_INVALID_CANONICAL_SECURITY_ID")
    if canonical_security_id not in u_ids:
        return {
            "status":"BLOCK_NOT_IN_U_D",
            "canonical_security_id":canonical_security_id,
            "signal_date":signal_date,
            "u_member":False,
            "e_state":"NOT_EVALUATED",
            "setup_emission_authorized":False,
            "episode_emission_authorized":False,
            "first60_append_authorized":False,
            "live_authorized":False,
            "price_or_return_data_consumed":False,
        }
    e=er.resolve(canonical_security_id,signal_date,e_rows)
    estate=e["classification_state"]
    status="PASS_DRY_AI_CORE_CANDIDATE" if estate=="ELIGIBLE_AI_CORE" else "BLOCK_E_NOT_ELIGIBLE"
    return {
        "status":status,
        "canonical_security_id":canonical_security_id,
        "signal_date":signal_date,
        "u_member":True,
        "e_state":estate,
        "effective_e_event":e.get("effective_event"),
        "setup_emission_authorized":False,
        "episode_emission_authorized":False,
        "first60_append_authorized":False,
        "live_authorized":False,
        "price_or_return_data_consumed":False,
    }

def evaluate(canonical_security_id:str,signal_date:str,root:Path=PIT_ROOT)->dict:
    u_ids,u=load_u_authority(signal_date,root)
    out=assess(canonical_security_id,signal_date,u_ids)
    out["u_authority"]=u
    return out

def write_synthetic_u(root:Path,d:str,ids:list[str],wrong_date:str|None=None,bad_hash:bool=False):
    root.mkdir(parents=True,exist_ok=True)
    up=root/f"{d}_PIT_UNIVERSE.csv"
    with up.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["canonical_security_id"],lineterminator="\n")
        w.writeheader()
        for cid in ids:
            w.writerow({"canonical_security_id":cid})
    h=sha_file(up)
    obj={
        "signal_date":wrong_date or d,
        "status":"PASS",
        "universe_snapshot_file":str(up),
        "universe_snapshot_sha256":("0"*64 if bad_hash else h),
    }
    (root/f"{d}_PIT_DATE_AUTHORITY.json").write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def self_test():
    tests=[]
    def ck(name,cond): tests.append({"name":name,"pass":bool(cond)})

    cid="SZSE:300634"
    u={cid}
    before=assess(cid,"2026-09-22",u)
    on=assess(cid,"2026-09-23",u)
    ck("G01_real_E_before_effective_blocks",before["status"]=="BLOCK_E_NOT_ELIGIBLE" and before["e_state"]=="NOT_ESTABLISHED")
    ck("G02_real_E_on_effective_passes_dry",on["status"]=="PASS_DRY_AI_CORE_CANDIDATE" and on["e_state"]=="ELIGIBLE_AI_CORE")
    ck("G03_not_in_U_blocks_before_E",assess(cid,"2026-09-23",set())["status"]=="BLOCK_NOT_IN_U_D")
    ck("G04_unknown_E_defaults_block",assess("SSE:600000","2026-09-23",{"SSE:600000"})["status"]=="BLOCK_E_NOT_ELIGIBLE")

    nontrading=False
    try: assess(cid,"2026-09-26",u)
    except RuntimeError: nontrading=True
    ck("G05_nontrading_signal_date_fails_closed",nontrading)

    bad_cid=False
    try: assess("300634","2026-09-23",{"300634"})
    except RuntimeError: bad_cid=True
    ck("G06_noncanonical_id_blocks",bad_cid)

    ck("G07_pass_never_authorizes_emission",
       on["setup_emission_authorized"] is False and
       on["episode_emission_authorized"] is False and
       on["first60_append_authorized"] is False and
       on["live_authorized"] is False)
    ck("G08_no_price_or_return_data",on["price_or_return_data_consumed"] is False)

    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        write_synthetic_u(root,"2026-09-23",[cid])
        ids,meta=load_u_authority("2026-09-23",root)
        ck("G09_PASS_U_authority_loads",cid in ids and meta["universe_count"]==1)

        root2=Path(td)/"dup"
        write_synthetic_u(root2,"2026-09-23",[cid,cid])
        dup=False
        try: load_u_authority("2026-09-23",root2)
        except RuntimeError as e: dup=str(e)=="BLOCK_U_AUTHORITY"
        ck("G10_duplicate_U_identity_blocks",dup)

        root3=Path(td)/"hash"
        write_synthetic_u(root3,"2026-09-23",[cid],bad_hash=True)
        bad=False
        try: load_u_authority("2026-09-23",root3)
        except RuntimeError as e: bad=str(e)=="BLOCK_U_AUTHORITY"
        ck("G11_U_snapshot_hash_mismatch_blocks",bad)

        root4=Path(td)/"date"
        write_synthetic_u(root4,"2026-09-23",[cid],wrong_date="2026-09-22")
        wrong=False
        try: load_u_authority("2026-09-23",root4)
        except RuntimeError as e: wrong=str(e)=="BLOCK_U_AUTHORITY"
        ck("G12_U_authority_date_mismatch_blocks",wrong)

        missing=False
        try: load_u_authority("2026-09-24",root)
        except RuntimeError as e: missing=str(e)=="BLOCK_NO_PIT_U_AUTHORITY"
        ck("G13_missing_U_authority_blocks",missing)

    result={
        "schema":"AI_CORE_EVID_V2_8_4_DRY_SETUP_ELIGIBILITY_GATE_SELFTEST_V1",
        "tests":tests,
        "passed":sum(x["pass"] for x in tests),
        "total":len(tests),
        "all_pass":all(x["pass"] for x in tests),
        "real_E_event_integration_tested":True,
        "real_PIT_U_authority_required_for_actual_evaluate":True,
        "setup_or_episode_emission_authorized":False,
        "live_authorized":False,
    }
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("self-test")
    e=sub.add_parser("evaluate")
    e.add_argument("--canonical-security-id",required=True)
    e.add_argument("--signal-date",required=True)
    e.add_argument("--pit-root",default=str(PIT_ROOT))
    a=ap.parse_args()
    if a.cmd=="self-test":
        self_test()
    else:
        print(json.dumps(evaluate(a.canonical_security_id,a.signal_date,Path(a.pit_root)),ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
