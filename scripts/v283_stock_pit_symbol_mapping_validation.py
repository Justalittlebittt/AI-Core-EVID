from __future__ import annotations
import json
from pathlib import Path
import duckdb
import pandas as pd

OUT=Path("evidence/V2.8.3_STOCK_PIT_SYMBOL_MAPPING_VALIDATION_1.json")
PIT=Path("evidence/v283_pit_authority/2026-10-09_PIT_UNIVERSE.csv")
URL="https://huggingface.co/datasets/AlphaDojo/dojo_stock_kline/resolve/ae09e2103d224050c90b6bdbf77f8fcf5805d6cf/data.parquet?download=true"

def main():
    pit=pd.read_csv(PIT,dtype=str).fillna("")
    pit["expected_symbol"]=pit.apply(
        lambda r: f"{r['security_code']}.SS" if r["exchange"]=="SSE"
        else (f"{r['security_code']}.SZ" if r["exchange"]=="SZSE" else ""),
        axis=1
    )
    if (pit["expected_symbol"]=="").any():
        raise RuntimeError("UNSUPPORTED_EXCHANGE_IN_PIT")
    con=duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.register("u",pit[["canonical_security_id","expected_symbol"]])
    q=f"""
      SELECT
        u.canonical_security_id,
        u.expected_symbol,
        count(*) row_count,
        count(DISTINCT cast(k.symbol as varchar)) distinct_symbol_count,
        min(cast(k.symbol as varchar)) min_symbol,
        max(cast(k.symbol as varchar)) max_symbol
      FROM u
      LEFT JOIN read_parquet('{URL}') k
        ON cast(k.symbol as varchar)=u.expected_symbol
       AND cast(k.kline_t as varchar)='1D'
      GROUP BY 1,2
      ORDER BY 1
    """
    x=con.execute(q).fetchdf()
    missing=x[x["row_count"]==0]
    ambiguous=x[x["distinct_symbol_count"]>1]
    matched=x[x["row_count"]>0]
    out={
      "schema":"AI_CORE_EVID_V2_8_3_STOCK_PIT_SYMBOL_MAPPING_VALIDATION_1",
      "status":"PASS" if len(missing)==0 and len(ambiguous)==0 and len(x)==len(pit) else "FAIL",
      "pit_security_count":int(len(pit)),
      "mapped_security_count":int(len(matched)),
      "missing_security_count":int(len(missing)),
      "ambiguous_security_count":int(len(ambiguous)),
      "missing_examples":missing[["canonical_security_id","expected_symbol"]].head(20).to_dict("records"),
      "ambiguous_examples":ambiguous[["canonical_security_id","expected_symbol"]].head(20).to_dict("records"),
      "mapping_rule":"SSE:<code> -> <code>.SS; SZSE:<code> -> <code>.SZ; kline_t=1D; membership authority is PIT universe",
      "scientific_output_generated":False,
      "price_or_return_statistics_computed":False,
      "fold3_accessed":False,
      "fold4_accessed":False
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out,ensure_ascii=False,indent=2))
    con.close()
    if out["status"]!="PASS":
        raise SystemExit(2)

if __name__=="__main__":
    main()
