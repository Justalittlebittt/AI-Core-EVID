from __future__ import annotations
import json
from pathlib import Path
import duckdb

OUT=Path("evidence/V2.8.3_STOCK_SCHEMA_DOMAIN_PROBE_1.json")
URL="https://huggingface.co/datasets/AlphaDojo/dojo_stock_kline/resolve/ae09e2103d224050c90b6bdbf77f8fcf5805d6cf/data.parquet?download=true"

def rows(con,q):
    return [list(r) for r in con.execute(q).fetchall()]

def main():
    con=duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    out={
      "schema":"AI_CORE_EVID_V2_8_3_STOCK_SCHEMA_DOMAIN_PROBE_1",
      "status":"PASS",
      "revision":"ae09e2103d224050c90b6bdbf77f8fcf5805d6cf",
      "exchange_counts":rows(con,f"SELECT exchange, count(*) c FROM read_parquet('{URL}') GROUP BY 1 ORDER BY 2 DESC"),
      "kline_t_counts":rows(con,f"SELECT kline_t, count(*) c FROM read_parquet('{URL}') GROUP BY 1 ORDER BY 2 DESC"),
      "symbol_suffix_counts":rows(con,f"""
        SELECT
          CASE
            WHEN symbol LIKE '%.SS' THEN '.SS'
            WHEN symbol LIKE '%.SZ' THEN '.SZ'
            ELSE 'OTHER'
          END suffix,
          count(*) c
        FROM read_parquet('{URL}')
        GROUP BY 1 ORDER BY 2 DESC
      """),
      "exchange_symbol_cross_counts":rows(con,f"""
        SELECT exchange,
          CASE
            WHEN symbol LIKE '%.SS' THEN '.SS'
            WHEN symbol LIKE '%.SZ' THEN '.SZ'
            ELSE 'OTHER'
          END suffix,
          count(*) c
        FROM read_parquet('{URL}')
        GROUP BY 1,2 ORDER BY 1,2
      """),
      "distinct_symbols":con.execute(f"SELECT count(DISTINCT symbol) FROM read_parquet('{URL}')").fetchone()[0],
      "other_symbol_examples":[r[0] for r in con.execute(f"SELECT DISTINCT symbol FROM read_parquet('{URL}') WHERE symbol NOT LIKE '%.SS' AND symbol NOT LIKE '%.SZ' LIMIT 20").fetchall()],
      "scientific_output_generated":False,
      "price_or_return_statistics_computed":False,
      "fold3_accessed":False,
      "fold4_accessed":False
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out,ensure_ascii=False,indent=2))
    con.close()

if __name__=="__main__":
    main()
