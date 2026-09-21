from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from scripts.v280_scale_invariant_features import (
    PRICE_SCALE_INVARIANT,
    add_cross_sectional_ranks,
    build_features,
)

def fixture(n=320):
    d = pd.bdate_range("2025-01-02", periods=n)
    rows=[]
    for j,cid in enumerate(["SSE:600000","SZSE:000001","SSE:688981"]):
        base=10.0 + j*7.0
        for i,dt in enumerate(d):
            # deterministic non-linear path, no randomness.
            close=base*(1.0+0.0012*i+0.025*math.sin(i/11.0+j))
            prev=base*(1.0+0.0012*max(i-1,0)+0.025*math.sin(max(i-1,0)/11.0+j))
            open_=close*(1.0+0.002*math.sin(i/7.0))
            high=max(open_,close)*1.012
            low=min(open_,close)*0.988
            rows.append({
              "canonical_security_id":cid,
              "bar_date":dt.date().isoformat(),
              "open":open_,"high":high,"low":low,"close":close,
              "amount":1e8*(1+j*0.2)*(1+0.1*math.sin(i/9.0))
            })
    return pd.DataFrame(rows)

def finite_close(a,b,tol=1e-11):
    aa=np.asarray(a,dtype=float)
    bb=np.asarray(b,dtype=float)
    mask=np.isfinite(aa)&np.isfinite(bb)
    return bool(np.allclose(aa[mask],bb[mask],rtol=tol,atol=tol,equal_nan=True))

def main():
    tests=[]
    base=fixture()
    f0=build_features(base)

    # A01: future mutation must not alter features at an earlier D.
    cutoff=pd.Timestamp("2026-01-15").date()
    mutated=base.copy()
    mask=pd.to_datetime(mutated["bar_date"]).dt.date > cutoff
    mutated.loc[mask,["open","high","low","close"]]*=17.0
    f1=build_features(mutated)
    a=f0[f0["bar_date"]==cutoff].sort_values("canonical_security_id")
    b=f1[f1["bar_date"]==cutoff].sort_values("canonical_security_id")
    ok=all(finite_close(a[c],b[c]) for c in PRICE_SCALE_INVARIANT)
    tests.append({"name":"A01_future_rows_do_not_change_D_features","pass":ok})

    # A02: uniform OHLC scale must preserve all price-scale-invariant features.
    scaled=base.copy()
    scaled[["open","high","low","close"]]*=7.3
    fs=build_features(scaled)
    ok=all(finite_close(f0[c],fs[c]) for c in PRICE_SCALE_INVARIANT)
    tests.append({"name":"A02_uniform_price_scale_invariance","pass":ok})

    # A03: amount-only changes must not affect price feature family.
    am=base.copy()
    am["amount"]*=3.0
    fa=build_features(am)
    ok=all(finite_close(f0[c],fa[c]) for c in PRICE_SCALE_INVARIANT)
    tests.append({"name":"A03_amount_isolation","pass":ok})

    # A04: forward-like input columns are rejected.
    bad=base.copy()
    bad["fwd10"]=0.1
    try:
        build_features(bad)
        ok=False
    except ValueError:
        ok=True
    tests.append({"name":"A04_forward_column_rejected","pass":ok})

    # A05: cross-sectional ranks are date-local.
    r0=add_cross_sectional_ranks(f0,["ret_20"])
    changed=f0.copy()
    last=max(changed["bar_date"])
    changed.loc[changed["bar_date"]==last,"ret_20"]*=1000
    r1=add_cross_sectional_ranks(changed,["ret_20"])
    earlier=sorted(set(f0["bar_date"]))[-2]
    x=r0[r0["bar_date"]==earlier].sort_values("canonical_security_id")["ret_20__pct_rank"]
    y=r1[r1["bar_date"]==earlier].sort_values("canonical_security_id")["ret_20__pct_rank"]
    tests.append({"name":"A05_cross_sectional_rank_date_local","pass":finite_close(x,y)})

    # A06: engine emits no future/outcome columns.
    leaked=[c for c in f0.columns if c.startswith(("fwd","future_","outcome_","target_"))]
    tests.append({"name":"A06_no_outcome_columns_emitted","pass":len(leaked)==0,"detail":leaked})

    receipt={
      "schema":"AI_CORE_EVID_V2_8_0_FEATURE_ENGINE_SELFTEST_V1",
      "tests":tests,
      "passed":sum(1 for t in tests if t["pass"]),
      "total":len(tests)
    }
    receipt["all_pass"]=receipt["passed"]==receipt["total"]
    Path("v280_feature_selftest.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps(receipt,indent=2))
    if not receipt["all_pass"]:
        raise SystemExit(1)

if __name__=="__main__":
    main()
