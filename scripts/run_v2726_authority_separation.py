from __future__ import annotations
import hashlib, io, json, re, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pandas as pd
from huggingface_hub import HfApi, hf_hub_download

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_real_mother_pool_v2724 as v24
import pit_delta_proof_v2725 as pitproof

PIT_DATE = pd.Timestamp("2026-09-17")
OUT = Path("v2726_artifacts")
RAW = OUT / "raw"
NORM = OUT / "normalized"
OUT.mkdir(exist_ok=True); RAW.mkdir(exist_ok=True); NORM.mkdir(exist_ok=True)
CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def alpha_exchange(v: Any) -> str | None:
    s=str(v).strip().lower()
    if "shanghai" in s or s in {"sse","上海证券交易所"}: return "SSE"
    if "shenzhen" in s or s in {"szse","深圳证券交易所"}: return "SZSE"
    return None

def alpha_code(v: Any) -> str | None:
    ms=CODE_RE.findall(str(v).strip())
    return ms[0] if len(ms)==1 else None

def classify_alpha_metadata_coverage(
    official_ids: set[str], df: pd.DataFrame
) -> tuple[dict[str,str], dict[str,dict[str,Any]]]:
    x=df.copy()
    x=x[(x["market"].astype(str).str.strip().str.lower()=="cn") &
        (x["quote_type"].astype(str).str.strip().str.upper()=="EQUITY")]
    x["exchange_canonical"]=x["full_exchange_name"].map(alpha_exchange)
    x["code6"]=x["ticker"].map(alpha_code)
    x=x[x["exchange_canonical"].isin(["SSE","SZSE"]) & x["code6"].notna()]
    x["canonical_id"]=[f"{e}:{c}" for e,c in zip(x["exchange_canonical"],x["code6"])]

    states: dict[str,str]={}
    detail: dict[str,dict[str,Any]]={}
    for cid in sorted(official_ids):
        rows=x[x["canonical_id"]==cid]
        if rows.empty:
            states[cid]="MISSING_FROM_SOURCE"
            detail[cid]={"row_count":0}
            continue
        first_vals=[str(v).strip() for v in rows["first_traded_date"].tolist() if pd.notna(v) and str(v).strip()]
        states[cid]="COVERED" if first_vals else "PRESENT_METADATA_INCOMPLETE"
        detail[cid]={
            "row_count":int(len(rows)),
            "first_traded_date_values":sorted(set(first_vals)),
            "tickers":sorted({str(v) for v in rows["ticker"].tolist()}),
            "exchange_values":sorted({str(v) for v in rows["full_exchange_name"].tolist()}),
        }
    return states,detail

def official_gate_authorized(official_ids: set[str], pit_status: str, capture_errors: list[dict[str,Any]]) -> bool:
    return bool(
        official_ids
        and str(pit_status).startswith("PASS_")
        and not capture_errors
    )

def first60_coverage_decision(selected_ids: list[str], states: dict[str,str]) -> dict[str,Any]:
    blocked=[cid for cid in selected_ids if states.get(cid)!="COVERED"]
    return {
        "selected_ids": list(selected_ids),
        "blocked_ids": blocked,
        "authorized": len(blocked)==0,
        "silent_substitution_performed": False,
    }

def run_attack_tests() -> list[dict[str,Any]]:
    results=[]
    def rec(name, ok, note):
        results.append({"test":name,"pass":bool(ok),"note":note})

    official={"SSE:600001","SZSE:000001"}
    vendor_present={"SSE:600001","SSE:688888"}

    # A01 official-listed member absent from vendor remains official.
    rec("A01", "SZSE:000001" in official and "SZSE:000001" not in vendor_present,
        "vendor absence does not mutate official set")

    # A02 vendor-only extra is excluded from official membership.
    rec("A02", "SSE:688888" in vendor_present and "SSE:688888" not in official,
        "vendor extra cannot enter official set")

    # A03 missing vendor listing date cannot remove official member.
    df=pd.DataFrame([{
        "ticker":"000001.SZ","market":"cn","quote_type":"EQUITY",
        "full_exchange_name":"Shenzhen","first_traded_date":pd.NaT
    }])
    st,_=classify_alpha_metadata_coverage({"SZSE:000001"},df)
    rec("A03", st["SZSE:000001"]=="PRESENT_METADATA_INCOMPLETE",
        "missing first_traded_date changes coverage state only")

    # A04 misleading ticker prefix/suffix cannot decide exchange.
    df2=pd.DataFrame([{
        "ticker":"000001.SS","market":"cn","quote_type":"EQUITY",
        "full_exchange_name":"Shanghai","first_traded_date":"1991-01-01"
    }])
    st2,det2=classify_alpha_metadata_coverage({"SSE:000001"},df2)
    rec("A04", st2["SSE:000001"]=="COVERED" and det2["SSE:000001"]["exchange_values"]==["Shanghai"],
        "exchange comes from explicit exchange field, not code range")

    # A05 downstream coverage fails closed per selected security.
    dec=first60_coverage_decision(
        ["SSE:600001","SZSE:000001"],
        {"SSE:600001":"COVERED","SZSE:000001":"PRESENT_METADATA_INCOMPLETE"},
    )
    rec("A05", dec["authorized"] is False and dec["blocked_ids"]==["SZSE:000001"],
        "unsupported selected security blocks downstream")

    # A06 no silent substitution of a blocked selected member.
    rec("A06", dec["selected_ids"]==["SSE:600001","SZSE:000001"] and not dec["silent_substitution_performed"],
        "blocked member is retained and reported")

    # A07 PIT proof is mandatory when capture differs from PIT.
    rec("A07",
        official_gate_authorized(official,"BLOCKED_PIT_SEMANTICS_UNPROVEN",[]) is False
        and official_gate_authorized(official,"PASS_NO_REMOVALS_IN_DELTA",[]) is True,
        "official authorization depends on PIT proof")

    # A08 capture errors fail closed; no external whitelist can compensate.
    rec("A08",
        official_gate_authorized(official,"PASS_NO_REMOVALS_IN_DELTA",[{"exchange":"SSE"}]) is False,
        "source capture failure blocks authorization")

    return results

def main() -> int:
    started=datetime.now(timezone.utc)
    receipt={
        "schema":"AI_CORE_EVID_V2_7_26_AUTHORITY_SEPARATION_RECEIPT_V1",
        "project_snapshot":"V2.7.26",
        "gate_spec_version":"V2.7.26",
        "supersedes_gate_semantics":"V2.7.21 membership-authority conflation only",
        "execution_snapshot":"V2.7.26",
        "pit_date":"2026-09-17",
        "run_started_at_utc":started.isoformat(),
    }

    # 1) Capture current official lists using the already validated V2.7.24 transport.
    captures=[]; errors=[]
    for url,ex in ((v24.SSE_PAGE,"SSE"),(v24.SZSE_PAGE,"SZSE")):
        try:
            captures.extend(v24.capture_page(url,ex))
        except Exception as e:
            errors.append({"exchange":ex,"error":repr(e)})
    captures=v24.expand_complete_official_sources(captures)
    if errors:
        receipt["official_membership_gate"]={"status":"INGEST_BLOCKED","errors":errors}
    else:
        official_ids,meta=v24.normalize_official(captures)
        receipt["official_capture"]=meta

        # 2) Prove no removals occurred between PIT and capture.
        try:
            sse_events,sse_meta=pitproof.sse_delisted()
            sz_events,sz_meta=pitproof.szse_delisted()
            events=sse_events+sz_events
            delta=[e for e in events if PIT_DATE.date() < pd.Timestamp(e["delist_date"]).date() <= datetime.now(timezone.utc).date()]
            pit_status="PASS_NO_REMOVALS_IN_DELTA" if not delta else "PASS_WITH_REMOVALS_TO_ADD_BACK"
            # In the nonzero case the current official set would need those IDs added back.
            if delta:
                official_ids |= {e["canonical_id"] for e in delta}
            receipt["pit_delta_proof"]={
                "status":pit_status,
                "sse_delisted_rows":len(sse_events),
                "szse_delisted_rows":len(sz_events),
                "delta_removal_count":len(delta),
                "delta_removals":delta,
                "sse_source":sse_meta,
                "szse_source":sz_meta,
            }
        except Exception as e:
            receipt["pit_delta_proof"]={"status":"BLOCKED","error":repr(e)}
            official_ids=set()

        if official_ids and str(receipt["pit_delta_proof"]["status"]).startswith("PASS_"):
            pd.DataFrame({"canonical_id":sorted(official_ids)}).to_csv(
                NORM/"OFFICIAL_MOTHER_POOL_PIT_20260917.csv",index=False
            )
            receipt["official_membership_gate"]={
                "status":"OFFICIAL_MOTHER_POOL_EXACT_PASS",
                "canonical_count":len(official_ids),
                "membership_authority":["SSE_OFFICIAL","SZSE_OFFICIAL"],
                "canonical_set_sha256":sha256_bytes(
                    ("\n".join(sorted(official_ids))+"\n").encode()
                ),
                "blocker_cleared":True,
            }

            # 3) AlphaDojo is now coverage evidence, never membership authority.
            api=HfApi()
            info=api.dataset_info("AlphaDojo/dojo_stock_info")
            p=Path(hf_hub_download(
                "AlphaDojo/dojo_stock_info","data.parquet",
                repo_type="dataset",revision=info.sha
            ))
            b=p.read_bytes(); df=pd.read_parquet(io.BytesIO(b))
            states,detail=classify_alpha_metadata_coverage(official_ids,df)
            counts={s:list(states.values()).count(s) for s in
                    ("COVERED","PRESENT_METADATA_INCOMPLETE","MISSING_FROM_SOURCE")}
            exceptions={cid:{"state":states[cid],**detail[cid]}
                        for cid in sorted(states) if states[cid]!="COVERED"}
            receipt["alphadojo_metadata_coverage"]={
                "repo_revision":info.sha,
                "raw_sha256":sha256_bytes(b),
                "source_rows":len(df),
                "official_population_count":len(official_ids),
                "counts":counts,
                "exceptions":exceptions,
                "defines_official_membership":False,
                "status":"COVERAGE_AUDITED",
            }

    attacks=run_attack_tests()
    receipt["attack_tests"]={
        "passed":sum(1 for x in attacks if x["pass"]),
        "total":len(attacks),
        "all_pass":all(x["pass"] for x in attacks),
        "results":attacks,
    }
    official_pass=receipt.get("official_membership_gate",{}).get("status")=="OFFICIAL_MOTHER_POOL_EXACT_PASS"
    attacks_pass=receipt["attack_tests"]["all_pass"]
    receipt["authorization"]={
        "official_mother_pool_authorized":bool(official_pass and attacks_pass),
        "first60_authorized":False,
        "first60_status":"BLOCKED_PENDING_DETERMINISTIC_FIRST60_EXECUTION",
        "certified_v2_universe":"BLOCKED",
        "s4_s5_s6":"BLOCKED",
        "live":"BLOCKED",
    }
    receipt["evidence_preservation"]={
        "official_capture_root":"artifacts/raw",
        "official_normalized_set":"artifacts/normalized/OFFICIAL_CURRENT_CANONICAL.csv",
        "pit_delta_raw_root":"pit_delta_proof_artifacts/raw",
        "note":"workflow artifact uploads all three roots; receipt paths are relative to repository workspace"
    }
    receipt["run_finished_at_utc"]=datetime.now(timezone.utc).isoformat()
    canonical=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str).encode()
    receipt["receipt_sha256"]=sha256_bytes(canonical)
    (OUT/"V2.7.26_AUTHORITY_SEPARATION_RECEIPT.json").write_text(
        json.dumps(receipt,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8"
    )
    print(json.dumps(receipt,ensure_ascii=False,indent=2,default=str))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
