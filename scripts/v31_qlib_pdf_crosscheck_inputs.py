#!/usr/bin/env python3
"""Preselect original-report cross-check issuer periods without looking at future prices."""
import argparse
import hashlib
import json
import math
import struct
import zipfile
from pathlib import Path
from v31_qlib_pit_archive_probe import ARCHIVE_SHA256, HEADER, DATA, FIELDS, _find_member

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--archive",type=Path,required=True)
    p.add_argument("--listing",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    digest=hashlib.sha256(a.archive.read_bytes()).hexdigest()
    if digest!=ARCHIVE_SHA256: raise ValueError("ARCHIVE_IDENTITY_MISMATCH")
    rows=json.loads(a.listing.read_text())["rows"]
    # First two names per year from PREVIOUSLY pinned deterministic set.
    candidates=[]
    for year in (201803,202003,202203):
        eligible=sorted((r for r in rows if r["period"]==year and r["listing_status"]=="LISTED_AT_QUARTER_END" and r["fields_present"]==4),
                        key=lambda r: (hashlib.sha256(r["symbol"].encode()).hexdigest(),r["symbol"]))
        candidates.extend(eligible[:2])
    with zipfile.ZipFile(a.archive) as z:
        names=z.namelist()
        definitions=json.loads(z.read(_find_member(names,"/financial/fields.json")))["fields"]
        fmap={int(k):v["name"] for k,v in definitions.items() if v.get("name") in FIELDS}
        out=[]
        for r in candidates:
            raw=z.read(_find_member(names,"/financial/"+r["symbol"]+"/pit.data"))
            magic,version,size,_,count,checksum=HEADER.unpack_from(raw)
            if size!=DATA.size or len(raw)!=HEADER.size+count*size or hashlib.sha256(raw[HEADER.size:]).digest()!=checksum:
                raise ValueError("CORRUPT_PIT_FILE:"+r["symbol"])
            field_records={field:[] for field in FIELDS}
            for offset in range(HEADER.size,len(raw),size):
                fid,day,period,value,_=DATA.unpack_from(raw,offset)
                if period==r["period"] and fid in fmap and math.isfinite(value):
                    field_records[fmap[fid]].append({"vendor_notice_day":day,"value":value})
            first={f:sorted(values,key=lambda v:v["vendor_notice_day"])[0] if values else None for f,values in field_records.items()}
            out.append({"symbol":r["symbol"],"report_period":r["period"],"first_vendor_field_versions":first})
    result={"schema":"V31_PRESELECTED_ISSUER_PDF_CROSSCHECK_INPUTS_V1","rule":"two first SHA256-ranked complete previously sampled provider-listed issuers per period, fixed without future outcomes","issuer_periods":out,"source_only":True,"pdf_authenticated":False,"price_or_returns_read":False,"trade_authorized":False}
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print("PRESELECTED_PDF_VERIFICATION_INPUTS="+json.dumps(out,ensure_ascii=False))
if __name__=="__main__":
    main()
