from __future__ import annotations

import argparse, csv, hashlib, json, re, tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

import v29_historical_e_dev_source_runner as old
import v284_candidate_triage as ct
import v284_pdf_text_extractor as te
import v284_page_scoped_classifier as pc

CONTRACT=Path('evidence/V2.9.1_NEGATIVE_SPACE_PROBE_CONTRACT_1.json')
MAP=Path('evidence/V2.7.27_SECURITY_ISSUER_PIT_MAP.csv')
START='2023-01-01'; END='2024-12-30'; BATCH_SIZE=64
POSITIVE='ELIGIBLE_AI_CORE'; SH=ZoneInfo('Asia/Shanghai')
OUT_RESULTS=Path('evidence/V2.9.1_NEGATIVE_SPACE_BATCH1_RESULTS_1.csv')
OUT_POS=Path('evidence/V2.9.1_NEGATIVE_SPACE_BATCH1_POSITIVE_EVENTS_1.csv')
OUT_RECEIPT=Path('evidence/V2.9.1_NEGATIVE_SPACE_BATCH1_RECEIPT_1.json')
FALLBACK_RECEIPT=Path('evidence/V2.9.1_IDENTITY_AUTHORITY_FALLBACK_VALIDATION_1.json')

FIELDS=['canonical_security_id','development_fold','security_code','security_name','org_id','announcement_id','announcement_title','announcement_time','adjunct_url','path_disclosure_date','parent_candidate_absent','triage_state','announcement_local_date_asia_shanghai','temporal_provenance_status','retrospective_causal_effective_date','pipeline_status','blocker','object_sha256','bytes','pdf_page_count','pages_with_text','total_nonwhitespace_characters','page_text_sha256','classification_state','evidence_page_number','evidence_sentence_sha256','matched_ai_role','matched_commerciality','classification_reason','decision_sha256']

def stable_sha(o): return hashlib.sha256(json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def sha_file(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read_json(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def read_rows(p): return list(csv.DictReader(Path(p).open(encoding='utf-8')))
def write_csv(p, rr):
    with Path(p).open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,extrasaction='ignore',lineterminator='\n'); w.writeheader(); w.writerows(rr)

def post(page,payload):
    q=page.evaluate("""async (payload)=>{const body=new URLSearchParams(payload).toString();const r=await fetch('/new/hisAnnouncement/query',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'},body});return {status:r.status,text:await r.text()};}""",payload)
    if q['status']!=200: raise RuntimeError(f'CNINFO_HTTP_{q["status"]}')
    return q['text']

def resolve_org(page,code):
    matches=[]
    def on_req(req):
        if '/new/hisAnnouncement/query' not in req.url or req.method!='POST': return
        q=parse_qs(req.post_data or ''); stock=(q.get('stock') or [''])[0]
        if stock.startswith(code+','):
            org=stock.split(',',1)[1].strip()
            if org: matches.append(org)
    page.on('request',on_req)
    try:
        page.goto(f'https://www.cninfo.com.cn/new/fulltextSearch?keyWord={code}',wait_until='domcontentloaded',timeout=60000)
        page.wait_for_timeout(1000)
        ins=page.locator('input')
        for i in range(min(ins.count(),12)):
            try:
                el=ins.nth(i)
                if not el.is_visible(): continue
                ph=el.get_attribute('placeholder') or ''
                if any(x in ph for x in ('代码','简称','关键')):
                    el.fill(code); el.press('Enter'); page.wait_for_timeout(1500); break
            except Exception: pass
    finally: page.remove_listener('request',on_req)
    u=sorted(set(matches))
    if len(u)!=1: raise RuntimeError(f'ORG_ID_UNRESOLVED:{code}:{u}')
    return u[0]

def locator(raw, aid):
    x=str(raw or '').strip(); p=urlparse(x)
    if not x or any(ch in x for ch in ('\r','\n','\x00')): raise RuntimeError('OFFICIAL_LOCATOR_BLOCK')
    if p.scheme or p.netloc:
        if p.scheme!='https' or (p.hostname or '').lower() not in {'www.cninfo.com.cn','static.cninfo.com.cn'}: raise RuntimeError('OFFICIAL_LOCATOR_ORIGIN_BLOCK')
    path=p.path.lstrip('/')
    m=re.fullmatch(r'finalpage/(\d{4}-\d{2}-\d{2})/(\d+)\.pdf',path,re.I)
    if not m or m.group(2)!=aid: raise RuntimeError(f'OFFICIAL_LOCATOR_SHAPE_BLOCK:{x[:120]}')
    return path,m.group(1)

def query_rows(page, cid, code, org, exchange):
    base={'column':'sse' if exchange=='SSE' else 'szse','tabName':'fulltext','plate':'sh' if exchange=='SSE' else 'sz','stock':f'{code},{org}','searchkey':'','secid':'','category':'','trade':'','seDate':f'{START}~{END}','sortName':'','sortType':'','isHLtitle':'true','pageNum':'1','pageSize':'30'}
    first=json.loads(post(page,base)); total=int(first.get('totalRecordNum') or first.get('totalAnnouncement') or 0)
    raw=[]; page_no=1
    while len(raw)<total:
        obj=first if page_no==1 else json.loads(post(page,{**base,'pageNum':str(page_no)}))
        anns=obj.get('announcements') or []
        if not anns and len(raw)<total: raise RuntimeError(f'PAGINATION_EARLY:{cid}:{len(raw)}/{total}')
        raw.extend(anns); page_no+=1
        if page_no>1000: raise RuntimeError('PAGINATION_RUNAWAY')
    ded={}
    for a in raw:
        aid=str(a.get('announcementId') or '').strip()
        if not aid: continue
        path,pdate=locator(a.get('adjunctUrl'),aid)
        ms=str(a.get('announcementTime') or '').strip()
        if not re.fullmatch(r'\d{13}|\d{10}',ms): raise RuntimeError(f'ANNOUNCEMENT_TIME_BLOCK:{aid}')
        d=datetime.fromtimestamp(int(ms)/(1000 if len(ms)==13 else 1),tz=timezone.utc).astimezone(SH).date().isoformat()
        if not START<=d<=END: raise RuntimeError(f'DATE_BOUND_ESCAPE:{aid}:{d}')
        row={'canonical_security_id':cid,'security_code':code,'security_name':str(a.get('secName') or '').strip(),'org_id':org,'announcement_id':aid,'announcement_title':re.sub(r'</?em>','',str(a.get('announcementTitle') or ''),flags=re.I),'announcement_time':ms,'adjunct_url':path,'path_disclosure_date':pdate}
        if aid in ded and any(str(ded[aid].get(k))!=str(row.get(k)) for k in ('canonical_security_id','adjunct_url','announcement_time')): raise RuntimeError(f'ANNOUNCEMENT_CONFLICT:{aid}')
        ded[aid]=row
    if len(ded)!=total: raise RuntimeError(f'PAGINATION_DEDUPE_MISMATCH:{cid}:{len(ded)}/{total}')
    rr=sorted(ded.values(),key=lambda r:(r['path_disclosure_date'],r['announcement_id']))
    return rr,{'official_total':total,'deduped_count':len(rr),'pages_fetched':page_no-1}

def load_authority(path):
    rr=read_rows(path); ids=[str(r.get('announcement_id') or '').strip() for r in rr]
    if len(ids)!=583 or len(set(ids))!=583 or not all(ids): raise RuntimeError(f'RECOVERY_AUTHORITY_COUNT_BLOCK:{len(ids)}')
    if hashlib.sha256(('\n'.join(sorted(ids))+'\n').encode()).hexdigest()!='dad6e67763cc92c1c7c1b3f2527dc241499c6cb9ef59ce4175892209fe397e72': raise RuntimeError('RECOVERY_AUTHORITY_ID_HASH_BLOCK')
    return set(ids)

def validate_inputs(authority, recovery_receipt, phase_a_receipt):
    c=read_json(CONTRACT)
    if c.get('schema')!='AI_CORE_EVID_V2_9_1_NEGATIVE_SPACE_PROBE_CONTRACT_1' or c.get('status')!='FROZEN_BEFORE_IMPLEMENTATION': raise RuntimeError('CONTRACT_BLOCK')
    r=read_json(recovery_receipt)
    if r.get('status')!='V2_9_1_COMPARISON_AUTHORITY_RECOVERED_CONSERVATIVE' or r.get('all_pass') is not True or r.get('authorization',{}).get('negative_space_batch1_allowed') is not True: raise RuntimeError('RECOVERY_RECEIPT_BLOCK')
    a=read_json(phase_a_receipt)
    if a.get('schema')!='AI_CORE_EVID_V2_9_1_NEGATIVE_SPACE_PROBE_PHASE_A_VALIDATION_1' or a.get('status')!='PASS' or a.get('all_pass') is not True or a.get('authorization',{}).get('execute_scientific_probe') is not True: raise RuntimeError('PHASE_A_RECEIPT_BLOCK')
    ids=load_authority(authority)
    return c,ids

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--authority',required=True); ap.add_argument('--recovery-receipt',required=True); ap.add_argument('--phase-a-receipt',required=True); a=ap.parse_args()
    c,parent_ids=validate_inputs(a.authority,a.recovery_receipt,a.phase_a_receipt)
    owner,by_fold=old.load_development_universe(); order=sorted(owner,key=lambda x:(hashlib.sha256(x.encode()).hexdigest(),x)); batch=order[:BATCH_SIZE]
    if len(batch)!=64 or any(owner[x] not in (0,1,2) for x in batch): raise RuntimeError('BATCH_MEMBERSHIP_BLOCK')
    m={r['canonical_security_id']:r for r in read_rows(MAP)}
    fb=read_json(FALLBACK_RECEIPT)
    if fb.get('status')!='V2_9_1_IDENTITY_AUTHORITY_FALLBACK_VALIDATED' or fb.get('all_pass') is not True or fb.get('authorization',{}).get('batch1_identity_fallback_allowed') is not True:
        raise RuntimeError('IDENTITY_FALLBACK_RECEIPT_BLOCK')
    fallback={}
    for x in fb.get('identity_evidence') or []:
        cid=str(x.get('canonical_security_id') or '').strip()
        if cid in {'SZSE:300344','SSE:600599'} and x.get('status')=='PASS' and str(x.get('resolved_org_id') or '').strip():
            fallback[cid]={
                'canonical_security_id':cid,
                'security_code':str(x.get('security_code') or cid.split(':')[1]).strip(),
                'exchange':str(x.get('exchange') or cid.split(':')[0]).strip(),
                'validated_org_id':str(x.get('resolved_org_id')).strip(),
                'identity_source':'V2.9.1_IDENTITY_AUTHORITY_FALLBACK_VALIDATION_1'
            }
    if set(fallback)!={'SZSE:300344','SSE:600599'}:
        raise RuntimeError('IDENTITY_FALLBACK_SET_BLOCK:'+','.join(sorted(fallback)))
    missing_identity=[x for x in batch if x not in m and x not in fallback]
    if missing_identity: raise RuntimeError('IDENTITY_MAP_COVERAGE_BLOCK:'+','.join(missing_identity))
    days=old.trading_dates(); results=[]; transport=[]
    with tempfile.TemporaryDirectory() as td, sync_playwright() as pw:
        root=Path(td); browser=pw.chromium.launch(headless=True); page=browser.new_page(locale='zh-CN'); page.goto('https://www.cninfo.com.cn/',wait_until='domcontentloaded',timeout=90000); page.wait_for_timeout(1000)
        api=pw.request.new_context(extra_http_headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36'})
        for rank,cid in enumerate(batch,1):
            ir=m.get(cid) or fallback[cid]; code=str(ir.get('security_code') or cid.split(':')[1]); exchange=cid.split(':')[0]
            try:
                org=ir.get('validated_org_id') or resolve_org(page,code)
                rr,ev=query_rows(page,cid,code,org,exchange)
                transport.append({'batch_rank':rank,'canonical_security_id':cid,'org_id':org,'identity_source':ir.get('identity_source','FROZEN_PIT_MAP_PLUS_CNINFO_PHASE_A_TRANSPORT'),**ev,'status':'PASS'})
            except Exception as exc:
                transport.append({'batch_rank':rank,'canonical_security_id':cid,'status':'BLOCKED','blocker':f'{type(exc).__name__}:{exc}'}); continue
            for row in rr:
                aid=row['announcement_id']
                if aid in parent_ids: continue
                q=ct.triage_title(row['announcement_title'],row.get('security_name',''))
                if q['triage_state']!='MATERIALIZE_CANDIDATE': continue
                base={**row,'development_fold':owner[cid],'parent_candidate_absent':True,'triage_state':q['triage_state']}
                try:
                    temporal=old.resolve_temporal(row,days); pdf=root/f'{rank:03d}_{aid}.pdf'; obj_sha,nbytes=old.fetch_pdf(api,row,pdf); pages,ex=te.extract_pdf(pdf,obj_sha); dec=pc.classify_pages(pages); e=dec['evidence']
                    results.append({**base,**temporal,'pipeline_status':'SUCCESS','blocker':'','object_sha256':obj_sha,'bytes':nbytes,'pdf_page_count':ex['pdf_page_count'],'pages_with_text':ex['pages_with_text'],'total_nonwhitespace_characters':ex['total_nonwhitespace_characters'],'page_text_sha256':ex['page_text_sha256'],'classification_state':dec['classification_state'],'evidence_page_number':e['page_number'],'evidence_sentence_sha256':hashlib.sha256(str(e.get('evidence_sentence') or '').encode()).hexdigest(),'matched_ai_role':'|'.join(e.get('matched_ai_role') or []),'matched_commerciality':'|'.join(e.get('matched_commerciality') or []),'classification_reason':e.get('reason',''),'decision_sha256':dec['decision_sha256']})
                except Exception as exc:
                    results.append({**base,'pipeline_status':'BLOCKED','blocker':f'{type(exc).__name__}:{exc}'})
        api.dispose(); browser.close()
    write_csv(OUT_RESULTS,results); positives=[r for r in results if r.get('pipeline_status')=='SUCCESS' and r.get('classification_state')==POSITIVE]; write_csv(OUT_POS,positives)
    queried=sum(x.get('status')=='PASS' for x in transport); ready=sum(r.get('pipeline_status')=='SUCCESS' for r in results); mat_rate=ready/len(results) if results else 1.0
    technical={'batch_membership_exact_64':len(batch)==64,'all_64_issuers_transport_complete':queried==64,'pagination_closed':all(x.get('official_total')==x.get('deduped_count') for x in transport if x.get('status')=='PASS'),'all_negative_space_claims_parent_absent':all(r['announcement_id'] not in parent_ids for r in results),'classifier_ready_materialization_rate_ge_0_90':mat_rate>=0.90,'all_positive_temporal_provenance_pass':all(r.get('temporal_provenance_status')=='PASS' for r in positives)}
    if not all(technical.values()): status='V2_9_1_NEGATIVE_SPACE_PROBE_TECHNICALLY_BLOCKED'
    elif positives: status='V2_9_1_DISCOVERY_SELECTION_BIAS_CONFIRMED'
    else: status='V2_9_1_BATCH1_COMPLETE_NO_NEGATIVE_SPACE_POSITIVE'
    out={'schema':'AI_CORE_EVID_V2_9_1_NEGATIVE_SPACE_BATCH1_RECEIPT_1','version':'V2.9.1','status':status,'batch_index':1,'batch_size':64,'batch_security_ids':batch,'summary':{'issuers_transport_complete':queried,'negative_space_triage_admitted':len(results),'classifier_ready':ready,'materialization_rate':mat_rate,'negative_space_positive_count':len(positives)},'technical_checks':technical,'transport_evidence':transport,'results_sha256':sha_file(OUT_RESULTS),'positive_events_sha256':sha_file(OUT_POS),'price_or_return_data_consumed':False,'candidate_outcome_research_executed':False,'fold3_accessed':False,'fold4_accessed':False,'next_batch_authorized':status=='V2_9_1_BATCH1_COMPLETE_NO_NEGATIVE_SPACE_POSITIVE'}
    out['receipt_sha256']=stable_sha(out); OUT_RECEIPT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(out,ensure_ascii=False,indent=2))
    if status=='V2_9_1_NEGATIVE_SPACE_PROBE_TECHNICALLY_BLOCKED': raise SystemExit(2)

if __name__=='__main__': main()
