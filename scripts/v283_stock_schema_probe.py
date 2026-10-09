from __future__ import annotations
import json
from pathlib import Path
import duckdb

OUT=Path("evidence/V2.8.3_STOCK_SCHEMA_PROBE_1.json")
URL="https://huggingface.co/datasets/AlphaDojo/dojo_stock_kline/resolve/ae09e2103d224050c90b6bdbf77f8fcf5805d6cf/data.parquet?download=true"

def main():
    con=duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    rows=con.execute(f"DESCRIBE SELECT * FROM read_parquet('{URL}')").fetchall()
    cols=[{"name":r[0],"type":r[1]} for r in rows]
    out={
      "schema":"AI_CORE_EVID_V2_8_3_STOCK_SCHEMA_PROBE_1",
      "status":"PASS",
      "revision":"ae09e2103d224050c90b6bdbf77f8fcf5805d6cf",
      "target_file":"data.parquet",
      "columns":cols,
      "column_names":[x["name"] for x in cols],
      "has_bar_time":any(x["name"]=="bar_time" for x in cols),
      "has_kline_t":any(x["name"]=="kline_t" for x in cols),
      "has_market":any(x["name"]=="market" for x in cols),
      "has_quote_type":any(x["name"]=="quote_type" for x in cols),
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
