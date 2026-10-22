from __future__ import annotations

import argparse, csv, hashlib, json, tempfile, time
from pathlib import Path

import v291_negative_space_batch1 as base

CHUNK_SIZE=8
CHUNK_COUNT=8
POSITIVE=base.POSITIVE

def out_paths(chunk_index:int):
    p=f'{chunk_index:02d}'
    return (
        Path(f'evidence/V2.9.3_BATCH3_RECONSTRUCTION_CHUNK_{p}_RESULTS_1.csv'),
        Path(f'evidence/V2.9.3_BATCH3_RECONSTRUCTION_CHUNK_{p}_RECEIPT_1.json'),
        Path(f'evidence/V2.9.3_BATCH3_RECONSTRUCTION_CHUNK_{p}_PROGRESS_1.json'),
    )

def heartbeat(progress:Path, chunk:int, rank:int, cid:str, stage:str, **extra):
    rec={
        'schema':'AI_CORE_EVID_V2_9_3_BATCH3_RECONSTRUCTION_CHUNK_PROGRESS_1',
        'chunk_index':chunk,'rank':rank,'canonical_security_id':cid,
        'stage':stage,'unix_time':time.time(),**extra
    }
    progress.write_text(json.dumps(rec,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"[V293-BATCH3-RECON-CHUNK{chunk:02d}] rank={rank}/192 security={cid} stage={stage} "+
          ' '.join(f"{k}={v}" for k,v in extra.items()), flush=True)

def write_results(path:Path, rows:list[dict]):
    base.write_csv(path, rows)

def load_batch_and_identity(authority, recovery_receipt, phase_a_receipt):
    _,parent_ids=base.validate_inputs(authority,recovery_receipt,phase_a_receipt)
    c=base.read_json(Path('evidence/V2.9.3_BATCH3_MINIMAL_RECONSTRUCTION_CONTRACT_1.json'))
    if c.get('schema')!='AI_CORE_EVID_V2_9_3_BATCH3_MINIMAL_RECONSTRUCTION_CONTRACT_1' or c.get('status')!='FROZEN_BEFORE_IMPLEMENTATION':
        raise RuntimeError('V293_CONTRACT_BLOCK')
    b2=base.read_json(Path('evidence/V2.9.2_HYBRID_DISCOVERY_BATCH2_RECEIPT_1.json'))
    if b2.get('status')!='V2_9_2_HYBRID_DISCOVERY_BATCH2_COMPLETE_TOO_SPARSE' or b2.get('next_batch_authorized') is not True:
        raise RuntimeError('BATCH3_NOT_AUTHORIZED_BY_BATCH2_RECEIPT')
    pre=base.read_json(Path('evidence/V2.9.2_BATCH3_IDENTITY_PREFLIGHT_1.json'))
    if pre.get('schema')!='AI_CORE_EVID_V2_9_2_BATCH3_IDENTITY_PREFLIGHT_1' or pre.get('status')!='PASS':
        raise RuntimeError('BATCH3_IDENTITY_PREFLIGHT_BLOCK')
    owner,_=base.old.load_development_universe()
    order=sorted(owner,key=lambda x:(hashlib.sha256(x.encode()).hexdigest(),x))
    batch=order[128:192]
    if len(batch)!=64 or any(owner[x] not in (0,1,2) for x in batch):
        raise RuntimeError('BATCH3_MEMBERSHIP_BLOCK')
    if pre.get('security_ids')!=batch or pre.get('batch_ranks')!=[129,192]:
        raise RuntimeError('BATCH3_PREFLIGHT_MEMBERSHIP_MISMATCH')
    m={r['canonical_security_id']:r for r in base.read_rows(base.MAP)}
    missing=[x for x in batch if x not in m]
    if missing:
        raise RuntimeError('BATCH3_IDENTITY_MAP_COVERAGE_BLOCK:'+','.join(missing))
    return c,parent_ids,owner,batch,m

def query_rows_stable(page, cid, code, org, exchange):
    try:
        return base.query_rows(page,cid,code,org,exchange)
    except RuntimeError as exc:
        msg=str(exc)
        # Each call restarts the *whole* fixed-range official query at page 1.
        # A short/empty last page is not accepted as a complete record set.
        if not msg.startswith(('PAGINATION_DEDUPE_MISMATCH:', 'PAGINATION_EARLY:')):
            raise
        time.sleep(3)
        return base.query_rows(page,cid,code,org,exchange)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--authority',required=True)
    ap.add_argument('--recovery-receipt',required=True)
    ap.add_argument('--phase-a-receipt',required=True)
    a=ap.parse_args()
    chunk_index=3
    results_path,receipt_path,progress_path=out_paths(chunk_index)
    contract,parent_ids,owner,batch,m=load_batch_and_identity(a.authority,a.recovery_receipt,a.phase_a_receipt)
    local_start=(chunk_index-1)*CHUNK_SIZE
    chunk=batch[local_start:local_start+CHUNK_SIZE]
    rank_start=129+local_start
    ranks=list(range(rank_start,rank_start+CHUNK_SIZE))
    if len(chunk)!=CHUNK_SIZE:
        raise RuntimeError('CHUNK_MEMBERSHIP_BLOCK')

    if receipt_path.exists():
        prior=base.read_json(receipt_path)
        if (prior.get('status')=='V2_9_3_BATCH3_RECONSTRUCTION_CHUNK_COMPLETE'
            and prior.get('chunk_index')==chunk_index
            and prior.get('batch_ranks')==ranks
            and prior.get('security_ids')==chunk
            and prior.get('execution_integrity_pass') is True):
            print(json.dumps({'status':'CHUNK_ALREADY_COMPLETE_REUSED','chunk_index':chunk_index,'receipt_sha256':prior.get('receipt_sha256')},ensure_ascii=False))
            return

    days=base.old.trading_dates()
    results=[]
    transport=[]
    with tempfile.TemporaryDirectory() as td, base.sync_playwright() as pw:
        root=Path(td)
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(locale='zh-CN')
        page.goto('https://www.cninfo.com.cn/',wait_until='domcontentloaded',timeout=90000)
        page.wait_for_timeout(1000)
        api=pw.request.new_context(extra_http_headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36'})
        for local_i,cid in enumerate(chunk):
            rank=ranks[local_i]
            sec_t0=time.monotonic()
            ir=m[cid]
            code=str(ir.get('security_code') or cid.split(':')[1])
            exchange=cid.split(':')[0]
            heartbeat(progress_path,chunk_index,rank,cid,'SECURITY_START',exchange=exchange,code=code)
            try:
                heartbeat(progress_path,chunk_index,rank,cid,'ORG_RESOLVE_START')
                org=ir.get('validated_org_id') or base.resolve_org(page,code)
                heartbeat(progress_path,chunk_index,rank,cid,'ORG_RESOLVE_DONE',org_id=org)
                heartbeat(progress_path,chunk_index,rank,cid,'PAGINATION_START')
                rr,ev=query_rows_stable(page,cid,code,org,exchange)
                heartbeat(progress_path,chunk_index,rank,cid,'PAGINATION_DONE',official_total=ev.get('official_total'),pages_fetched=ev.get('pages_fetched'))
                transport.append({'batch_rank':rank,'canonical_security_id':cid,'org_id':org,
                    'identity_source':'FROZEN_PIT_MAP_PLUS_CNINFO_PHASE_A_TRANSPORT',
                    **ev,'status':'PASS'})
            except Exception as exc:
                blocker=f'{type(exc).__name__}:{exc}'
                transport.append({'batch_rank':rank,'canonical_security_id':cid,'status':'BLOCKED','blocker':blocker})
                heartbeat(progress_path,chunk_index,rank,cid,'TRANSPORT_BLOCKED',blocker=blocker,elapsed_seconds=round(time.monotonic()-sec_t0,3))
                continue

            admitted=0
            for row in rr:
                aid=row['announcement_id']
                if aid in parent_ids:
                    continue
                q=base.ct.triage_title(row['announcement_title'],row.get('security_name',''))
                if q['triage_state']!='MATERIALIZE_CANDIDATE':
                    continue
                admitted+=1
                base_row={**row,'development_fold':owner[cid],'parent_candidate_absent':True,'triage_state':q['triage_state']}
                try:
                    heartbeat(progress_path,chunk_index,rank,cid,'CANDIDATE_START',announcement_id=aid,candidate_index=admitted)
                    temporal=base.old.resolve_temporal(row,days)
                    heartbeat(progress_path,chunk_index,rank,cid,'PDF_FETCH_START',announcement_id=aid,candidate_index=admitted)
                    pdf=root/f'{rank:03d}_{aid}.pdf'
                    obj_sha,nbytes=base.old.fetch_pdf(api,row,pdf)
                    heartbeat(progress_path,chunk_index,rank,cid,'PDF_FETCH_DONE',announcement_id=aid,bytes=nbytes)
                    pages,ex=base.run_with_timeout(120,'PDF_EXTRACT',base.te.extract_pdf,pdf,obj_sha)
                    heartbeat(progress_path,chunk_index,rank,cid,'CLASSIFIER_START',announcement_id=aid,pdf_pages=ex.get('pdf_page_count'))
                    dec=base.run_with_timeout(120,'CLASSIFIER',base.pc.classify_pages,pages)
                    e=dec['evidence']
                    heartbeat(progress_path,chunk_index,rank,cid,'CLASSIFIER_DONE',announcement_id=aid,classification_state=dec.get('classification_state'))
                    results.append({**base_row,**temporal,'pipeline_status':'SUCCESS','blocker':'',
                        'object_sha256':obj_sha,'bytes':nbytes,'pdf_page_count':ex['pdf_page_count'],
                        'pages_with_text':ex['pages_with_text'],'total_nonwhitespace_characters':ex['total_nonwhitespace_characters'],
                        'page_text_sha256':ex['page_text_sha256'],'classification_state':dec['classification_state'],
                        'evidence_page_number':e['page_number'],
                        'evidence_sentence_sha256':hashlib.sha256(str(e.get('evidence_sentence') or '').encode()).hexdigest(),
                        'matched_ai_role':'|'.join(e.get('matched_ai_role') or []),
                        'matched_commerciality':'|'.join(e.get('matched_commerciality') or []),
                        'classification_reason':e.get('reason',''),'decision_sha256':dec['decision_sha256']})
                except Exception as exc:
                    blocker=f'{type(exc).__name__}:{exc}'
                    heartbeat(progress_path,chunk_index,rank,cid,'CANDIDATE_BLOCKED',announcement_id=aid,blocker=blocker)
                    results.append({**base_row,'pipeline_status':'BLOCKED','blocker':blocker})
                write_results(results_path,results)
            heartbeat(progress_path,chunk_index,rank,cid,'SECURITY_DONE',triage_admitted=admitted,elapsed_seconds=round(time.monotonic()-sec_t0,3))
            write_results(results_path,results)
        api.dispose()
        browser.close()

    write_results(results_path,results)
    queried=sum(x.get('status')=='PASS' for x in transport)
    positives=[r for r in results if r.get('pipeline_status')=='SUCCESS' and r.get('classification_state')==POSITIVE]
    execution_checks={
        'chunk_membership_exact_8':len(chunk)==8,
        'all_8_issuers_transport_complete':queried==8,
        'pagination_closed':all(x.get('official_total')==x.get('deduped_count') for x in transport if x.get('status')=='PASS'),
        'all_negative_space_claims_parent_absent':all(r['announcement_id'] not in parent_ids for r in results),
        'all_positive_temporal_provenance_pass':all(r.get('temporal_provenance_status')=='PASS' for r in positives)
    }
    execution_pass=all(execution_checks.values())
    receipt={
        'schema':'AI_CORE_EVID_V2_9_3_BATCH3_RECONSTRUCTION_CHUNK_RECEIPT_1',
        'version':'V2.9.3','status':'V2_9_3_BATCH3_RECONSTRUCTION_CHUNK_COMPLETE' if execution_pass else 'V2_9_3_BATCH3_RECONSTRUCTION_CHUNK_BLOCKED',
        'chunk_index':chunk_index,'batch_ranks':ranks,'security_ids':chunk,
        'execution_integrity_pass':execution_pass,'execution_checks':execution_checks,
        'summary':{
            'issuers_transport_complete':queried,
            'negative_space_triage_admitted':len(results),
            'classifier_ready':sum(r.get('pipeline_status')=='SUCCESS' for r in results),
            'supplement_positive_count_diagnostic_only':len(positives)
        },
        'transport_evidence':transport,
        'results_sha256':base.sha_file(results_path),
        'scientific_terminal_status_emitted':False,'scientific_batch_index':3,
        'next_scientific_batch_authorized':False,
        'price_or_return_data_consumed':False,'candidate_outcome_research_executed':False,
        'fold3_accessed':False,'fold4_accessed':False
    }
    receipt['receipt_sha256']=base.stable_sha(receipt)
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    heartbeat(progress_path,chunk_index,ranks[-1],chunk[-1],'CHUNK_DONE',execution_integrity_pass=execution_pass,result_count=len(results))
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
    if not execution_pass:
        raise SystemExit(2)

if __name__=='__main__':
    main()
