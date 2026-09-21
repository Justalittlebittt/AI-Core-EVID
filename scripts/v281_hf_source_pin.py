from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import HfApi

REPOS = [
    ("AlphaDojo/dojo_stock_kline", "data.parquet"),
    ("AlphaDojo/dojo_benchmark_kline", "data.parquet"),
    ("AlphaDojo/dojo_stock_info", "data.parquet"),
]

def stable_sha256(obj) -> str:
    b=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()

def main():
    api=HfApi()
    out={
      "schema":"AI_CORE_EVID_V2_8_1_HF_SOURCE_PIN_V1",
      "captured_at_utc":datetime.now(timezone.utc).isoformat(),
      "repos":[]
    }
    for repo_id,target_file in REPOS:
        info=api.dataset_info(repo_id=repo_id, files_metadata=True)
        siblings=[]
        target=None
        for s in info.siblings or []:
            rec={"rfilename":s.rfilename}
            size=getattr(s,"size",None)
            if size is not None: rec["size"]=size
            lfs=getattr(s,"lfs",None)
            if lfs:
                if isinstance(lfs,dict):
                    rec["lfs"]=lfs
                else:
                    rec["lfs"]={
                      k:getattr(lfs,k) for k in ("sha256","size","pointer_size")
                      if getattr(lfs,k,None) is not None
                    }
            siblings.append(rec)
            if s.rfilename==target_file:
                target=rec
        if target is None:
            raise RuntimeError(f"{repo_id}: target file {target_file} absent")
        out["repos"].append({
          "repo_id":repo_id,
          "repo_type":"dataset",
          "revision_sha":info.sha,
          "last_modified":str(info.last_modified),
          "target_file":target_file,
          "target_metadata":target,
          "siblings":siblings
        })
    out["source_pin_sha256"]=stable_sha256(out)
    Path("v281_hf_source_pin.json").write_text(
      json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
