from __future__ import annotations
import hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from playwright.sync_api import sync_playwright

PIT="2026-09-17"
OUT=Path("v2727_sample_artifacts")
RAW=OUT/"raw"; PDF=OUT/"pdf"
RAW.mkdir(parents=True,exist_ok=True); PDF.mkdir(parents=True,exist_ok=True)

def sha(b:bytes)->str: return hashlib.sha256(b).hexdigest()

def pit_ok(date_text:str)->bool:
    return str(date_text)[:10] < PIT

def primary_meta(title:str):
    # Full periodic report only. Summaries and separate financial/audit reports are not substitutes.
    t=re.sub(r"\s+","",title or "")
    if any(x in t for x in ("摘要","财务报告","审计报告","审阅报告")):
        return None
    m=re.search(r"(20\d{2})年(半年度|年度)报告(?P<suffix>.*)$",t)
    if not m: return None
    suffix=m.group("suffix")
    # Accept only empty suffix or explicit revision/correction markers.
    if suffix and not re.fullmatch(r"[（(]?(修订版|修订稿|更正版|更正稿)[）)]?",suffix):
        return None
    y=int(m.group(1)); kind=m.group(2)
    period_end=f"{y}-06-30" if kind=="半年度" else f"{y}-12-31"
    revision=bool(suffix)
    return {"year":y,"kind":"H1" if kind=="半年度" else "FY","period_end":period_end,"revision":revision}

def select_latest(rows, exchange):
    candidates=[]
    for r in rows:
        if exchange=="SSE":
            title=r.get("TITLE") or ""; d=r.get("SSEDATE") or ""
            url=r.get("URL") or ""
            code=r.get("SECURITY_CODE")
        else:
            title=r.get("title") or ""; d=r.get("publishTime") or ""
            url=r.get("attachPath") or ""
            codes=r.get("secCode") or []
            code=codes[0] if len(codes)==1 else None
        pm=primary_meta(title)
        if not pm or not pit_ok(d): continue
        candidates.append({"title":title,"disclosure_date":str(d)[:10],"path":url,"code":code,**pm})
    if not candidates:
        return None, candidates, "NO_PERIODIC_PRIMARY"
    max_period=max(c["period_end"] for c in candidates)
    same=[c for c in candidates if c["period_end"]==max_period]
    revisions=[c for c in same if c["revision"]]
    if len(revisions)==1:
        return revisions[0],candidates,None
    if len(revisions)>1:
        return None,candidates,"AMBIGUOUS_MULTIPLE_REVISIONS"
    if len(same)==1:
        return same[0],candidates,None
    # Multiple full reports same period without explicit revision marker are ambiguous.
    return None,candidates,"AMBIGUOUS_SAME_PERIOD_PRIMARY"

def sse_fetch(page,code):
    all_rows=[]; queries=[]
    for report_type in ("QUATER2","YEARLY"):
        cb=f"jsonpCallbackV2727{report_type}"
        qs=(
          f"jsonCallBack={cb}&isPagination=true&productId={code}"
          "&securityType=0101%2C120100%2C020100%2C020200%2C120200"
          f"&reportType2=DQBG&reportType={report_type}"
          "&pageHelp.pageSize=100&pageHelp.pageCount=50&pageHelp.pageNo=1"
          "&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=5"
        )
        url="https://query.sse.com.cn/security/stock/queryCompanyBulletin.do?"+qs

        # Use the endpoint in its native JSONP/browser mode. Direct APIRequestContext
        # calls are intermittently rejected with 403 even with Referer headers.
        out=page.evaluate("""async ({url,cb}) => {
          return await new Promise((resolve,reject) => {
            let done=false;
            const timer=setTimeout(() => {
              if (!done) { done=true; try { delete window[cb]; } catch(e) {} reject(new Error('SSE JSONP timeout')); }
            }, 30000);
            window[cb]=(obj) => {
              if (done) return;
              done=true; clearTimeout(timer);
              try { delete window[cb]; } catch(e) {}
              resolve(obj);
            };
            const s=document.createElement('script');
            s.src=url;
            s.async=true;
            s.onerror=() => {
              if (done) return;
              done=true; clearTimeout(timer);
              try { delete window[cb]; } catch(e) {}
              reject(new Error('SSE JSONP script load failed'));
            };
            document.head.appendChild(s);
          });
        }""", {"url":url,"cb":cb})

        # Re-canonicalize exact bytes for audit because JSONP browser execution
        # exposes the parsed object rather than the original response bytes.
        canon=json.dumps(out,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
        (RAW/f"sse_{code}_{report_type}_page1.browser.json").write_bytes(canon)
        ph=out.get("pageHelp") or {}
        rows=ph.get("data") or []
        all_rows.extend(rows)
        queries.append({
          "reportType":report_type,"url":url,
          "capture_mode":"BROWSER_JSONP_NATIVE",
          "canonical_json_sha256":sha(canon),"canonical_json_bytes":len(canon),
          "pageNo":ph.get("pageNo"),"pageSize":ph.get("pageSize"),
          "pageCount":ph.get("pageCount"),"total":ph.get("total"),
          "rows_returned":len(rows)
        })
    return all_rows, {"queries":queries}


def szse_fetch(page,code):
    body={"pageSize":50,"pageNum":1,"stock":[code],"channelCode":["listedNotice_disc"]}
    out=page.evaluate("""async (body) => {
      const u='/api/disc/announcement/annList?random=0.2727';
      const r=await fetch(u,{
        method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(body)
      });
      return {status:r.status,text:await r.text(),url:r.url};
    }""",body)
    if out["status"]!=200: raise RuntimeError(f"SZSE query HTTP {out['status']}")
    b=out["text"].encode()
    (RAW/f"szse_{code}_query_page1.json").write_bytes(b)
    obj=json.loads(out["text"])
    return obj.get("data") or [], {
      "url":out["url"],"request_body":body,"raw_sha256":sha(b),"raw_bytes":len(b),
      "announceCount":obj.get("announceCount"),"pageSize":50,"pageNum":1
    }

def sse_download_pdf(ctx, chosen, cid):
    path=chosen["path"]
    referer=f"https://www.sse.com.cn/assortment/stock/list/info/announcement/index.shtml?productId={chosen['code']}"
    attempts=[]
    for host in ("https://static.sse.com.cn","https://www.sse.com.cn"):
        url=host+path
        try:
            resp=ctx.request.get(
              url,
              headers={
                "Referer":referer,
                "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
                "Accept":"application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
              },
              timeout=60000
            )
            b=resp.body()
            diag={
              "host":host,"url":url,"status":resp.status,
              "content_type":resp.headers.get("content-type"),
              "bytes":len(b),"sha256":sha(b),
              "first64_hex":b[:64].hex(),
              "pdf_header_offset":b[:1024].find(b"%PDF-")
            }
            attempts.append(diag)
            (RAW/(cid.replace(":","_")+f"_sse_pdf_attempt_{len(attempts)}.json")).write_text(
              json.dumps(diag,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
            )
            if resp.status==200 and diag["pdf_header_offset"]>=0:
                p=PDF/(cid.replace(":","_")+".pdf"); p.write_bytes(b)
                return {
                  "path":str(p),"bytes":len(b),"sha256":sha(b),
                  "content_type":resp.headers.get("content-type"),
                  "pdf_header_offset":diag["pdf_header_offset"],
                  "resolved_url":url,"attempts":attempts
                }
            (RAW/(cid.replace(":","_")+f"_sse_nonpdf_attempt_{len(attempts)}.bin")).write_bytes(b)
        except Exception as e:
            attempts.append({"host":host,"url":url,"error":repr(e)})
    raise RuntimeError(f"{cid} no official SSE PDF host returned valid PDF; attempts={attempts}")

def save_pdf(resp, cid):
    b=resp.body()
    diag={
      "status":resp.status,
      "url":resp.url,
      "content_type":resp.headers.get("content-type"),
      "bytes":len(b),
      "first64_hex":b[:64].hex(),
      "pdf_header_offset":b[:1024].find(b"%PDF-")
    }
    (RAW/(cid.replace(":","_")+"_pdf_response_diag.json")).write_text(
      json.dumps(diag,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    if resp.status!=200: raise RuntimeError(f"{cid} PDF HTTP {resp.status}; diag={diag}")
    off=diag["pdf_header_offset"]
    if off < 0: 
        (RAW/(cid.replace(":","_")+"_nonpdf_payload.bin")).write_bytes(b)
        raise RuntimeError(f"{cid} payload is not PDF; diag={diag}")
    p=PDF/(cid.replace(":","_")+".pdf"); p.write_bytes(b)
    return {"path":str(p),"bytes":len(b),"sha256":sha(b),"content_type":resp.headers.get("content-type"),"pdf_header_offset":off}

def main():
    receipt={
      "schema":"AI_CORE_EVID_V2_7_27_SAMPLE_E2E_V1",
      "pit_date":PIT,
      "samples":{},
      "status":"BLOCKED",
      "started_at_utc":datetime.now(timezone.utc).isoformat()
    }
    with sync_playwright() as pw:
      browser=pw.chromium.launch(headless=True)
      ctx=browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
        locale="zh-CN"
      )

      # SSE sample: lightweight official browser session + native JSONP query.
      # wait_until='commit' avoids waiting for the heavy SSE page DOM/resources.
      page=ctx.new_page()
      page.goto("https://www.sse.com.cn/",wait_until="commit",timeout=30000)
      page.wait_for_timeout(1200)
      rows,qmeta=sse_fetch(page,"600000")
      chosen,cands,err=select_latest(rows,"SSE")
      srec={"query":qmeta,"candidate_count":len(cands),"candidates":cands,"selector_error":err}
      if chosen:
        if chosen["code"]!="600000": raise RuntimeError("SSE issuer identity mismatch")
        srec["selected"]=chosen
        srec["pdf"]=sse_download_pdf(ctx,chosen,"SSE:600000")
      receipt["samples"]["SSE:600000"]=srec
      page.close()

      # SZSE sample
      page=ctx.new_page()
      page.goto("https://www.szse.cn/disclosure/listed/notice/index.html?stock=000001",
                wait_until="domcontentloaded",timeout=90000)
      page.wait_for_timeout(3000)
      rows,qmeta=szse_fetch(page,"000001")
      chosen,cands,err=select_latest(rows,"SZSE")
      zrec={"query":qmeta,"candidate_count":len(cands),"candidates":cands,"selector_error":err}
      if chosen:
        if chosen["code"]!="000001": raise RuntimeError("SZSE issuer identity mismatch")
        base=page.evaluate("() => window.pathObj && pathObj.disc_file_path")
        if not base: raise RuntimeError("SZSE disc_file_path unavailable")
        pdf_url=base+"/download"+chosen["path"]+"?n="+quote(chosen["title"]+".PDF")
        pr=ctx.request.get(pdf_url,headers={"Referer":page.url},timeout=90000)
        zrec["selected"]=chosen
        zrec["pdf_base"]=base
        zrec["pdf_url"]=pdf_url
        zrec["pdf"]=save_pdf(pr,"SZSE:000001")
      receipt["samples"]["SZSE:000001"]=zrec
      page.close(); browser.close()

    ok=True
    for cid,r in receipt["samples"].items():
        ok &= r.get("selector_error") is None
        ok &= bool(r.get("selected"))
        ok &= bool(r.get("pdf",{}).get("sha256"))
    receipt["status"]="SAMPLE_E2E_PASS" if ok else "SAMPLE_E2E_BLOCKED"
    receipt["finished_at_utc"]=datetime.now(timezone.utc).isoformat()
    canonical=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    receipt["receipt_sha256"]=sha(canonical)
    (OUT/"V2.7.27_SAMPLE_E2E_RECEIPT.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
    return 0 if ok else 2

if __name__=="__main__": raise SystemExit(main())
