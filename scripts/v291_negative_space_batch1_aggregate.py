from __future__ import annotations

import csv, hashlib, json
from pathlib import Path

import v291_negative_space_batch1 as base

CHUNK_COUNT=8
CHUNK_SIZE=8
POSITIVE=base.POSITIVE
OUT_RESULTS=Path('evidence/V2.9.1_NEGATIVE_SPACE_BATCH1_RESULTS_1.csv')
OUT_POS=Path('evidence/V2.9.1_NEGATIVE_SPACE_BATCH1_POSITIVE_EVENTS_1.csv')
OUT_RECEIPT=Path('evidence/V2.9.1_NEGATIVE_SPACE_BATCH1_RECEIPT_1.json')

def chunk_paths(i:int):
    p=f'{i:02d}'
    return (
        Path(f'evidence/V2.9.1_NEGATIVE_SPACE_BATCH1_CHUNK_{p}_RESULTS_1.csv'),
        Path(f'evidence/V2.9.1_NEGATIVE_SPACE_BATCH1_CHUNK_{p}_RECEIPT_1.json'),
    )

def main():
    owner,_=base.old.load_development_universe()
    order=sorted(owner,key=lambda x:(hashlib.sha256(x.encode()).hexdigest(),x))
    batch=order[:64]
    if len(batch)!=64:
        raise RuntimeError('BATCH_MEMBERSHIP_BLOCK')

    all_results=[]
    all_transport=[]
    chunk_provenance=[]
    seen_ranks=[]
    seen_ids=[]
    for i in range(1,CHUNK_COUNT+1):
        rp,cp=chunk_paths(i)
        if not rp.exists() or not cp.exists():
            raise RuntimeError(f'CHUNK_EVIDENCE_MISSING:{i}')
        rec=base.read_json(cp)
        expected_ranks=list(range((i-1)*CHUNK_SIZE+1,i*CHUNK_SIZE+1))
        expected_ids=batch[(i-1)*CHUNK_SIZE:i*CHUNK_SIZE]
        if rec.get('schema')!='AI_CORE_EVID_V2_9_1_NEGATIVE_SPACE_BATCH1_EXECUTION_CHUNK_RECEIPT_1':
            raise RuntimeError(f'CHUNK_SCHEMA_BLOCK:{i}')
        if rec.get('status')!='V2_9_1_BATCH1_EXECUTION_CHUNK_COMPLETE' or rec.get('execution_integrity_pass') is not True:
            raise RuntimeError(f'CHUNK_NOT_COMPLETE:{i}')
        if rec.get('chunk_index')!=i or rec.get('batch_ranks')!=expected_ranks or rec.get('security_ids')!=expected_ids:
            raise RuntimeError(f'CHUNK_MEMBERSHIP_BLOCK:{i}')
        if base.sha_file(rp)!=rec.get('results_sha256'):
            raise RuntimeError(f'CHUNK_RESULTS_HASH_BLOCK:{i}')
        if rec.get('scientific_terminal_status_emitted') is not False or rec.get('next_scientific_batch_authorized') is not False:
            raise RuntimeError(f'CHUNK_SCIENTIFIC_AUTHORITY_BLOCK:{i}')
        if any(rec.get(k) is not False for k in ('price_or_return_data_consumed','candidate_outcome_research_executed','fold3_accessed','fold4_accessed')):
            raise RuntimeError(f'CHUNK_PROHIBITED_DATA_BLOCK:{i}')
        rr=base.read_rows(rp)
        all_results.extend(rr)
        all_transport.extend(rec.get('transport_evidence') or [])
        seen_ranks.extend(expected_ranks)
        seen_ids.extend(expected_ids)
        chunk_provenance.append({
            'chunk_index':i,
            'receipt_sha256':rec.get('receipt_sha256'),
            'results_sha256':rec.get('results_sha256'),
            'result_count':len(rr)
        })

    if seen_ranks!=list(range(1,65)) or seen_ids!=batch:
        raise RuntimeError('AGGREGATED_BATCH_MEMBERSHIP_BLOCK')

    base.write_csv(OUT_RESULTS,all_results)
    positives=[r for r in all_results if r.get('pipeline_status')=='SUCCESS' and r.get('classification_state')==POSITIVE]
    base.write_csv(OUT_POS,positives)

    queried=sum(x.get('status')=='PASS' for x in all_transport)
    ready=sum(r.get('pipeline_status')=='SUCCESS' for r in all_results)
    mat_rate=ready/len(all_results) if all_results else 1.0
    technical={
        'batch_membership_exact_64':len(batch)==64 and seen_ranks==list(range(1,65)) and seen_ids==batch,
        'all_64_issuers_transport_complete':queried==64 and len(all_transport)==64,
        'pagination_closed':all(x.get('status')=='PASS' and x.get('official_total')==x.get('deduped_count') for x in all_transport),
        'all_negative_space_claims_parent_absent':all(str(r.get('parent_candidate_absent')).lower() in {'true','1'} for r in all_results),
        'classifier_ready_materialization_rate_ge_0_90':mat_rate>=0.90,
        'all_positive_temporal_provenance_pass':all(r.get('temporal_provenance_status')=='PASS' for r in positives),
        'all_8_execution_chunks_complete':len(chunk_provenance)==8
    }
    if not all(technical.values()):
        status='V2_9_1_NEGATIVE_SPACE_PROBE_TECHNICALLY_BLOCKED'
    elif positives:
        status='V2_9_1_DISCOVERY_SELECTION_BIAS_CONFIRMED'
    else:
        status='V2_9_1_BATCH1_COMPLETE_NO_NEGATIVE_SPACE_POSITIVE'

    out={
        'schema':'AI_CORE_EVID_V2_9_1_NEGATIVE_SPACE_BATCH1_RECEIPT_1',
        'version':'V2.9.1','status':status,
        'batch_index':1,'batch_size':64,'batch_security_ids':batch,
        'execution_mode':'8x8_DETERMINISTIC_RESUMABLE_CHUNKS',
        'execution_chunks':chunk_provenance,
        'summary':{
            'issuers_transport_complete':queried,
            'negative_space_triage_admitted':len(all_results),
            'classifier_ready':ready,
            'materialization_rate':mat_rate,
            'negative_space_positive_count':len(positives)
        },
        'technical_checks':technical,
        'transport_evidence':all_transport,
        'results_sha256':base.sha_file(OUT_RESULTS),
        'positive_events_sha256':base.sha_file(OUT_POS),
        'price_or_return_data_consumed':False,
        'candidate_outcome_research_executed':False,
        'fold3_accessed':False,
        'fold4_accessed':False,
        'next_batch_authorized':status=='V2_9_1_BATCH1_COMPLETE_NO_NEGATIVE_SPACE_POSITIVE'
    }
    out['receipt_sha256']=base.stable_sha(out)
    OUT_RECEIPT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if status=='V2_9_1_NEGATIVE_SPACE_PROBE_TECHNICALLY_BLOCKED':
        raise SystemExit(2)

if __name__=='__main__':
    main()
