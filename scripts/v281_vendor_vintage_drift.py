from __future__ import annotations
import hashlib,json
from pathlib import Path
import duckdb
import pandas as pd
from huggingface_hub import HfApi,hf_hub_download

OLD_REV="cc79371024009e10d55ee9196f443d4528411cd4"
NEW_REV="c009ad58278161e7b6eb347b68f34f51166114f3"
INFO_REV="6654503cdfcfa87e3524145f6922c87d30b22ab0"
NEW_SHA="acb8ae5e31f58fe3972455b86614d668837f18afd59126c505faaae06920954b"
INFO_SHA="c548dfb42763e548fb33e275e6c1148294d52376b205fb31ce53a714cfcaf49f"
OUT=Path("v281_vintage_audit"); OUT.mkdir(exist_ok=True)

def sha_file(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def sql_lit(v):
    return "'" + str(v).replace("'", "''") + "'"

def lfs_meta(api,repo,rev):
    info=api.dataset_info(repo_id=repo,revision=rev,files_metadata=True)
    target=next((s for s in info.siblings or [] if s.rfilename=="data.parquet"),None)
    if target is None: raise RuntimeError(f"{repo}@{rev}: data.parquet missing")
    lfs=getattr(target,"lfs",None)
    if isinstance(lfs,dict): l=lfs
    else: l={k:getattr(lfs,k) for k in ("sha256","size") if lfs and getattr(lfs,k,None) is not None}
    return {"revision":info.sha,"last_modified":str(info.last_modified),"size":getattr(target,"size",None),"lfs":l}

def main():
    api=HfApi()
    old_meta=lfs_meta(api,"AlphaDojo/dojo_stock_kline",OLD_REV)
    new_meta=lfs_meta(api,"AlphaDojo/dojo_stock_kline",NEW_REV)
    info_meta=lfs_meta(api,"AlphaDojo/dojo_stock_info",INFO_REV)
    if new_meta["lfs"].get("sha256")!=NEW_SHA: raise RuntimeError("current kline LFS hash mismatch")
    if info_meta["lfs"].get("sha256")!=INFO_SHA: raise RuntimeError("stock_info LFS hash mismatch")

    old=Path(hf_hub_download("AlphaDojo/dojo_stock_kline","data.parquet",repo_type="dataset",revision=OLD_REV))
    new=Path(hf_hub_download("AlphaDojo/dojo_stock_kline","data.parquet",repo_type="dataset",revision=NEW_REV))
    info=Path(hf_hub_download("AlphaDojo/dojo_stock_info","data.parquet",repo_type="dataset",revision=INFO_REV))
    if sha_file(new)!=NEW_SHA: raise RuntimeError("downloaded current kline SHA mismatch")
    if sha_file(info)!=INFO_SHA: raise RuntimeError("downloaded stock_info SHA mismatch")
    old_sha=sha_file(old)
    if old_meta["lfs"].get("sha256") and old_sha!=old_meta["lfs"]["sha256"]:
        raise RuntimeError("downloaded old kline SHA mismatch")

    con=duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='5GB'")
    con.execute(f"""
      CREATE TEMP TABLE cn_symbols AS
      SELECT DISTINCT symbol
      FROM read_parquet({sql_lit(info)})
      WHERE lower(cast(market as varchar))='cn'
        AND upper(cast(quote_type as varchar))='EQUITY'
        AND symbol IS NOT NULL
    """)
    con.execute(f"""
      CREATE TEMP VIEW o AS
      SELECT k.symbol, cast(k.bar_time as timestamp) bar_time,
             cast(k.open as double) open_px, cast(k.high as double) high_px,
             cast(k.low as double) low_px, cast(k.close as double) close_px,
             cast(k.amount as double) amount
      FROM read_parquet({sql_lit(old)}) k
      INNER JOIN cn_symbols s USING(symbol)
      WHERE cast(k.kline_t as varchar)='1D'
    """)
    con.execute(f"""
      CREATE TEMP VIEW n_all AS
      SELECT k.symbol, cast(k.bar_time as timestamp) bar_time,
             cast(k.open as double) open_px, cast(k.high as double) high_px,
             cast(k.low as double) low_px, cast(k.close as double) close_px,
             cast(k.amount as double) amount
      FROM read_parquet({sql_lit(new)}) k
      INNER JOIN cn_symbols s USING(symbol)
      WHERE cast(k.kline_t as varchar)='1D'
    """)
    old_min,old_max,old_rows,old_symbols=con.execute(
      "SELECT min(bar_time),max(bar_time),count(*),count(distinct symbol) FROM o"
    ).fetchone()
    con.execute(f"CREATE TEMP VIEW n AS SELECT * FROM n_all WHERE bar_time <= {sql_lit(old_max)}")

    dup_o=con.execute("SELECT count(*)-count(distinct symbol||'|'||cast(bar_time as varchar)) FROM o").fetchone()[0]
    dup_n=con.execute("SELECT count(*)-count(distinct symbol||'|'||cast(bar_time as varchar)) FROM n").fetchone()[0]
    if dup_o or dup_n: raise RuntimeError(f"duplicate keys old={dup_o} new={dup_n}")

    con.execute("""
      CREATE TEMP TABLE joined AS
      SELECT coalesce(o.symbol,n.symbol) symbol,
             coalesce(o.bar_time,n.bar_time) bar_time,
             o.open_px old_open,o.high_px old_high,o.low_px old_low,o.close_px old_close,o.amount old_amount,
             n.open_px new_open,n.high_px new_high,n.low_px new_low,n.close_px new_close,n.amount new_amount,
             o.bar_time IS NOT NULL old_present,
             n.bar_time IS NOT NULL new_present
      FROM o FULL OUTER JOIN n USING(symbol,bar_time)
    """)
    con.execute("""
      CREATE TEMP TABLE scales AS
      SELECT symbol,
             median(new_close/old_close) FILTER (WHERE old_present AND new_present AND old_close>0 AND new_close>0) scale
      FROM joined GROUP BY symbol
    """)
    con.execute("""
      CREATE TEMP TABLE row_audit AS
      SELECT j.*,s.scale,
        CASE WHEN old_present AND new_present
                  AND old_open>0 AND old_high>0 AND old_low>0 AND old_close>0
                  AND new_open>0 AND new_high>0 AND new_low>0 AND new_close>0
                  AND s.scale>0
             THEN greatest(
               abs(new_open/(old_open*s.scale)-1),
               abs(new_high/(old_high*s.scale)-1),
               abs(new_low/(old_low*s.scale)-1),
               abs(new_close/(old_close*s.scale)-1)
             )
             ELSE NULL END price_resid,
        CASE WHEN old_present AND new_present AND old_amount IS NOT NULL AND new_amount IS NOT NULL
             THEN abs(new_amount-old_amount)/greatest(abs(old_amount),1.0)
             ELSE NULL END amount_rel_diff
      FROM joined j LEFT JOIN scales s USING(symbol)
    """)
    sym=con.execute("""
      SELECT symbol,
        sum(old_present::int) old_rows,
        sum(new_present::int) new_rows,
        sum((old_present AND new_present)::int) matched_rows,
        sum((old_present AND NOT new_present)::int) old_only_rows,
        sum((new_present AND NOT old_present)::int) new_only_rows,
        max(scale) scale,
        count(price_resid) valid_price_rows,
        max(price_resid) max_price_resid,
        quantile_cont(price_resid,0.9999) p9999_price_resid,
        max(amount_rel_diff) max_amount_rel_diff
      FROM row_audit
      GROUP BY symbol
      ORDER BY symbol
    """).fetchdf()
    sym["comparable"]=sym["old_rows"]>=60
    sym["price_stable"]=(
      sym["comparable"]
      & (sym["old_only_rows"]==0)
      & (sym["new_only_rows"]==0)
      & (sym["valid_price_rows"]==sym["matched_rows"])
      & (sym["max_price_resid"].fillna(float("inf"))<=0.001)
      & (sym["p9999_price_resid"].fillna(float("inf"))<=0.0001)
    )
    comparable=sym[sym["comparable"]]
    if len(comparable)==0: raise RuntimeError("no comparable symbols")
    stable=comparable[comparable["price_stable"]]
    stable_symbol_share=len(stable)/len(comparable)
    total_rows=int(comparable["matched_rows"].sum())
    stable_rows=int(stable["matched_rows"].sum())
    stable_row_share=stable_rows/total_rows if total_rows else 0.0
    current_only=int(((sym["old_rows"]==0)&(sym["new_rows"]>0)).sum())

    sym.to_csv(OUT/"V2.8.1_VENDOR_VINTAGE_SYMBOL_AUDIT.csv",index=False)
    unstable=sym[(sym["comparable"])&(~sym["price_stable"])].copy()
    unstable.to_csv(OUT/"V2.8.1_VENDOR_VINTAGE_UNSTABLE_SYMBOLS.csv",index=False)

    tests=[
      {"name":"V01_no_duplicate_old_keys","pass":dup_o==0,"actual":int(dup_o)},
      {"name":"V02_no_duplicate_new_overlap_keys","pass":dup_n==0,"actual":int(dup_n)},
      {"name":"V03_stable_symbol_share_ge_98pct","pass":stable_symbol_share>=0.98,"actual":stable_symbol_share},
      {"name":"V04_stable_row_share_ge_99_5pct","pass":stable_row_share>=0.995,"actual":stable_row_share},
    ]
    receipt={
      "schema":"AI_CORE_EVID_V2_8_1_VENDOR_VINTAGE_DRIFT_AUDIT_V1",
      "old_source":{**old_meta,"download_sha256":old_sha},
      "current_source":{**new_meta,"download_sha256":sha_file(new)},
      "stock_info":{**info_meta,"download_sha256":sha_file(info)},
      "overlap":{
        "old_min_bar_time":str(old_min),"old_max_bar_time":str(old_max),
        "old_cn_1d_rows":int(old_rows),"old_cn_symbols":int(old_symbols),
        "comparable_symbols":int(len(comparable)),
        "price_stable_symbols":int(len(stable)),
        "price_unstable_symbols":int(len(unstable)),
        "current_only_symbols_in_overlap_table":current_only,
        "stable_symbol_share":stable_symbol_share,
        "comparable_matched_rows":total_rows,
        "stable_matched_rows":stable_rows,
        "stable_row_share":stable_row_share
      },
      "tolerances":{"max_price_resid":0.001,"p9999_price_resid":0.0001,"min_old_rows":60},
      "tests":tests,
      "gate":{
        "status":"VINTAGE_SCALE_INVARIANCE_PASS" if all(t["pass"] for t in tests) else "VINTAGE_DRIFT_BLOCKED",
        "stage1_max_signal_date":str(old_max.date()) if hasattr(old_max,"date") else str(old_max)[:10],
        "unstable_symbols_must_be_excluded":True,
        "current_only_symbols_must_be_excluded":True
      }
    }
    canonical=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    receipt["receipt_sha256"]=hashlib.sha256(canonical).hexdigest()
    (OUT/"V2.8.1_VENDOR_VINTAGE_DRIFT_RECEIPT.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
    if receipt["gate"]["status"]!="VINTAGE_SCALE_INVARIANCE_PASS": raise SystemExit(2)

if __name__=="__main__": main()
