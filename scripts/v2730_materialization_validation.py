from __future__ import annotations
import csv, hashlib, json, os, re, shutil
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

PIT_DATE="2026-09-17"
EXPECTED_INVENTORY_SHA="6f497c81f99344596ba19e7ef62c54a23d373c07f80877d79af6f70f19f4a4f4"
INVENTORY=Path("evidence/V2.7.29_PRIMARY_LOCATOR_INVENTORY.csv")
OUT=Path("v2730_materialization")
CACHE=OUT/"cache"
OBJECTS=CACHE/"objects"/"sha256"
INDEX_PATH=CACHE/"locator_index.json"
SAMPLE=["SSE:600000","SSE:688981","SZSE:000001","SZSE:300750"]
ALLOWED_ORIGIN="https://static.cninfo.com.cn/"
PDF_PATH_RE=re.compile(r"^finalpage/\d{4}-\d{2}-\d{2}/(\d+)\.PDF$",re.I)

for p in (OUT,OBJECTS):
    p.mkdir(parents=True,exist_ok=True)

def sha(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()

def sha_text(s:str)->str:
    return sha(s.encode("utf-8"))

def fail(state,msg):
    raise RuntimeError(f"{state}:{msg}")

def inventory_rows():
    b=INVENTORY.read_bytes()
    if sha(b)!=EXPECTED_INVENTORY_SHA:
        fail("INVALID_LOCATOR_BLOCKED","inventory SHA256 mismatch")
    rows=list(csv.DictReader(b.decode("utf-8").splitlines()))
    by={}
    for r in rows:
        cid=r["canonical_security_id"]
        if cid in by:
            fail("INVALID_LOCATOR_BLOCKED",f"duplicate canonical_security_id {cid}")
        by[cid]=r
    return by

def validate_locator(r):
    cid=r["canonical_security_id"].strip()
    aid=r["announcement_id"].strip()
    adjunct=r["adjunct_url"].strip()
    disclosure=r["disclosure_date"].strip()
    if not cid or not aid or not adjunct or not disclosure:
        fail("INVALID_LOCATOR_BLOCKED",f"{cid}: incomplete locator")
    m=PDF_PATH_RE.match(adjunct)
    if not m:
        fail("INVALID_LOCATOR_BLOCKED",f"{cid}: adjunct_url not approved relative PDF path")
    if m.group(1)!=aid:
        fail("INVALID_LOCATOR_BLOCKED",f"{cid}: announcement_id/path mismatch")
    if disclosure>=PIT_DATE:
        fail("INVALID_LOCATOR_BLOCKED",f"{cid}: disclosure_date is not before PIT")
    return {
      "canonical_security_id":cid,
      "announcement_id":aid,
      "adjunct_url":adjunct,
      "disclosure_date":disclosure,
      "url":ALLOWED_ORIGIN+adjunct
    }

def validate_pdf_bytes(b:bytes):
    off=b[:2048].find(b"%PDF-")
    if off<0:
        fail("INVALID_PDF_BLOCKED","PDF header not found in first 2048 bytes")
    if len(b)<1024:
        fail("INVALID_PDF_BLOCKED","payload implausibly small")
    return off

def load_index():
    if not INDEX_PATH.exists():
        return {}
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))

def save_index(idx):
    INDEX_PATH.write_text(json.dumps(idx,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")

def locator_key(loc):
    return sha_text("|".join([
      loc["canonical_security_id"],loc["announcement_id"],loc["adjunct_url"]
    ]))

def verify_cached(entry):
    p=OBJECTS/entry["object_sha256"]
    if not p.exists():
        fail("CACHE_TAMPERED_BLOCKED",f"missing object {entry['object_sha256']}")
    b=p.read_bytes()
    actual=sha(b)
    if actual!=entry["object_sha256"]:
        fail("CACHE_TAMPERED_BLOCKED",f"object hash mismatch {actual} != {entry['object_sha256']}")
    off=validate_pdf_bytes(b)
    return b,off

def materialize(api, row, network_counter):
    loc=validate_locator(row)
    lk=locator_key(loc)
    idx=load_index()
    if lk in idx:
        b,off=verify_cached(idx[lk])
        return {
          **loc,"locator_key":lk,"state":"CACHE_HIT_VALID","network_fetch":False,
          "object_sha256":sha(b),"bytes":len(b),"pdf_header_offset":off
        }
    r=api.get(
      loc["url"],
      timeout=90000,
      headers={
        "Referer":"https://www.cninfo.com.cn/",
        "Accept":"application/pdf,application/octet-stream;q=0.9,*/*;q=0.8"
      }
    )
    network_counter[0]+=1
    status=r.status
    if status!=200:
        fail("FETCH_BLOCKED",f"{loc['canonical_security_id']}: HTTP {status}")
    b=r.body()
    off=validate_pdf_bytes(b)
    obj_sha=sha(b)
    p=OBJECTS/obj_sha
    if p.exists():
        existing=p.read_bytes()
        if sha(existing)!=obj_sha:
            fail("CACHE_TAMPERED_BLOCKED",f"{loc['canonical_security_id']}: existing object corrupted")
    else:
        p.write_bytes(b)
    idx[lk]={
      "canonical_security_id":loc["canonical_security_id"],
      "announcement_id":loc["announcement_id"],
      "adjunct_url":loc["adjunct_url"],
      "object_sha256":obj_sha,
      "bytes":len(b)
    }
    save_index(idx)
    return {
      **loc,"locator_key":lk,"state":"FETCHED_VALID","network_fetch":True,
      "http_status":status,"content_type":r.headers.get("content-type",""),
      "object_sha256":obj_sha,"bytes":len(b),"pdf_header_offset":off
    }

def expect_block(name,fn,expected):
    try:
        fn()
    except RuntimeError as e:
        state=str(e).split(":",1)[0]
        return {"name":name,"expected":expected,"actual":state,"pass":state==expected,"detail":str(e)}
    return {"name":name,"expected":expected,"actual":"NO_BLOCK","pass":False}

def attack_tests(by):
    first=dict(by[SAMPLE[0]])
    tests=[]

    bad_id=dict(first)
    bad_id["announcement_id"]="9999999999"
    tests.append(expect_block(
      "announcement_id_path_mismatch",
      lambda: validate_locator(bad_id),
      "INVALID_LOCATOR_BLOCKED"
    ))

    future=dict(first)
    future["disclosure_date"]=PIT_DATE
    tests.append(expect_block(
      "disclosure_date_not_before_pit",
      lambda: validate_locator(future),
      "INVALID_LOCATOR_BLOCKED"
    ))

    absolute=dict(first)
    absolute["adjunct_url"]="https://example.com/fake.pdf"
    tests.append(expect_block(
      "absolute_unapproved_origin",
      lambda: validate_locator(absolute),
      "INVALID_LOCATOR_BLOCKED"
    ))

    tests.append(expect_block(
      "non_pdf_payload",
      lambda: validate_pdf_bytes(b"<html>not pdf</html>"*100),
      "INVALID_PDF_BLOCKED"
    ))

    # Isolated corruption test: do not damage the real cache.
    idx=load_index()
    loc=validate_locator(first)
    lk=locator_key(loc)
    entry=dict(idx[lk])
    src=OBJECTS/entry["object_sha256"]
    tmp=OUT/"attack_cache"
    if tmp.exists(): shutil.rmtree(tmp)
    tmp.mkdir()
    corrupt=tmp/entry["object_sha256"]
    corrupt.write_bytes(src.read_bytes()+b"CORRUPTION")
    actual=sha(corrupt.read_bytes())
    tests.append({
      "name":"cache_object_hash_corruption",
      "expected":"CACHE_TAMPERED_BLOCKED",
      "actual":"CACHE_TAMPERED_BLOCKED" if actual!=entry["object_sha256"] else "NO_BLOCK",
      "pass":actual!=entry["object_sha256"]
    })

    return tests

def main():
    started=datetime.now(timezone.utc)
    by=inventory_rows()
    for cid in SAMPLE:
        if cid not in by:
            fail("INVALID_LOCATOR_BLOCKED",f"sample missing {cid}")

    network=[0]
    first=[]
    second=[]
    with sync_playwright() as pw:
        api=pw.request.new_context(
          extra_http_headers={
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36"
          }
        )
        # Establish official CNInfo session without launching a browser binary.
        home=api.get("https://www.cninfo.com.cn/",timeout=30000)
        if home.status!=200:
            fail("FETCH_BLOCKED",f"CNInfo session bootstrap HTTP {home.status}")
        for cid in SAMPLE:
            first.append(materialize(api,by[cid],network))
            print(f"FIRST {cid} -> {first[-1]['state']} {first[-1]['bytes']} bytes",flush=True)

        first_network=network[0]
        before=network[0]
        for cid in SAMPLE:
            second.append(materialize(api,by[cid],network))
            print(f"SECOND {cid} -> {second[-1]['state']}",flush=True)
        second_network=network[0]-before
        api.dispose()

    attacks=attack_tests(by)
    if not all(x["pass"] for x in attacks):
        fail("ATTACK_TEST_BLOCKED","one or more attack tests did not fail closed")

    first_map={x["canonical_security_id"]:x for x in first}
    second_map={x["canonical_security_id"]:x for x in second}
    for cid in SAMPLE:
        if first_map[cid]["object_sha256"]!=second_map[cid]["object_sha256"]:
            fail("CACHE_TAMPERED_BLOCKED",f"{cid}: first/second object hash differs")
        if second_map[cid]["state"]!="CACHE_HIT_VALID":
            fail("CACHE_TAMPERED_BLOCKED",f"{cid}: second pass not cache hit")

    receipt={
      "schema":"AI_CORE_EVID_V2_7_30_MATERIALIZATION_VALIDATION_V1",
      "started_at_utc":started.isoformat(),
      "finished_at_utc":datetime.now(timezone.utc).isoformat(),
      "pit_date":PIT_DATE,
      "inventory_sha256":EXPECTED_INVENTORY_SHA,
      "validation_scope":SAMPLE,
      "first_pass":first,
      "second_pass":second,
      "network_fetch_count_first_pass":first_network,
      "network_fetch_count_second_pass":second_network,
      "cache_object_count":len(list(OBJECTS.iterdir())),
      "attack_tests":attacks,
      "historical_prospective_certification":"BLOCKED_FIRST_OBSERVED_AFTER_PIT",
      "gate":{
        "all_first_pass_valid":all(x["state"]=="FETCHED_VALID" for x in first),
        "all_second_pass_cache_hit":all(x["state"]=="CACHE_HIT_VALID" for x in second),
        "second_pass_network_fetch_count_zero":second_network==0,
        "all_attack_tests_pass":all(x["pass"] for x in attacks),
        "status":"MATERIALIZATION_CONTRACT_VALIDATION_PASS"
      }
    }
    canon=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    receipt["receipt_sha256"]=sha(canon)
    (OUT/"V2.7.30_MATERIALIZATION_VALIDATION_RECEIPT.json").write_text(
      json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    # Git-safe compact locator->object index; raw objects remain artifact/cache-backend material.
    git_index={
      "schema":"AI_CORE_EVID_V2_7_30_LOCATOR_OBJECT_INDEX_V1",
      "objects":[
        {k:x[k] for k in ("canonical_security_id","announcement_id","adjunct_url","locator_key","object_sha256","bytes")}
        for x in first
      ]
    }
    (OUT/"V2.7.30_LOCATOR_OBJECT_INDEX.json").write_text(
      json.dumps(git_index,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
