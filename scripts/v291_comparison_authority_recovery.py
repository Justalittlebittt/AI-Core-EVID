from __future__ import annotations

import argparse, csv, hashlib, json, subprocess, sys
from pathlib import Path

CONTRACT=Path('evidence/V2.9.1_COMPARISON_AUTHORITY_RECOVERY_CONTRACT_1.json')
OUT_DIR=Path('evidence/v291_recovery')
OUT_IDS=OUT_DIR/'V2.9.1_RECOVERED_PARENT_CANDIDATE_IDS_1.csv'
OUT_RECEIPT=OUT_DIR/'V2.9.1_COMPARISON_AUTHORITY_RECOVERY_RECEIPT_1.json'
PARENT='c9bcda18ad9f39a79d20322183143e751121ae74'
COLLECTOR_PATH='scripts/v284_candidate_collector.py'
START='2023-01-01'; END='2024-12-30'


def stable_sha(o):
    return hashlib.sha256(json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def sha_file(p:Path):
    h=hashlib.sha256();
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

def read_csv(p:Path): return list(csv.DictReader(p.open(encoding='utf-8')))
def find_one(root:Path,name:str)->Path:
    xs=list(root.rglob(name))
    if len(xs)!=1: raise RuntimeError(f'ARTIFACT_MEMBER_COUNT:{name}:{len(xs)}')
    return xs[0]

def load_contract():
    c=json.loads(CONTRACT.read_text(encoding='utf-8'))
    if c.get('schema')!='AI_CORE_EVID_V2_9_1_COMPARISON_AUTHORITY_RECOVERY_CONTRACT_1' or c.get('status')!='FROZEN_BEFORE_RECOVERY_REPLAY':
        raise RuntimeError('RECOVERY_CONTRACT_BLOCK')
    if c['parent']['head_sha']!=PARENT or c['parent']['collector_path']!=COLLECTOR_PATH or c['parent']['range']!=[START,END]:
        raise RuntimeError('RECOVERY_PARENT_BINDING_BLOCK')
    if c['recovery_method']['classification_forbidden'] is not True or c['recovery_method']['price_or_return_forbidden'] is not True:
        raise RuntimeError('RECOVERY_SCOPE_BLOCK')
    return c

def ids_from_replay(obj):
    if obj.get('exact_88_selected_ids') is not True or obj.get('expected_selected_count')!=88 or obj.get('replay_selected_count')!=88:
        raise RuntimeError('PARENT_EXACT88_ARTIFACT_BLOCK')
    replay=[]
    for w in obj.get('per_window',[]): replay.extend(str(x) for x in w.get('selected_ids',[]))
    if len(replay)!=88 or len(set(replay))!=88: raise RuntimeError('PARENT_EXACT88_ID_BINDING_BLOCK')
    return set(replay)

def main(parent_artifact:Path):
    c=load_contract(); OUT_DIR.mkdir(parents=True,exist_ok=True)
    results_path=find_one(parent_artifact,'V2.9_HISTORICAL_E_SOURCE_EXPANSION_RESULTS_1.csv')
    replay_path=find_one(parent_artifact,'V2.9_HISTORICAL_E_SOURCE_EXPANSION_OLD_DESIGN_REPLAY_1.json')
    final_path=find_one(parent_artifact,'V2.9_HISTORICAL_E_SOURCE_EXPANSION_FINAL_RECEIPT_1.json')
    parent_rows=read_csv(results_path)
    parent_ids={str(r.get('announcement_id') or '').strip() for r in parent_rows}
    if len(parent_rows)!=277 or len(parent_ids)!=277 or '' in parent_ids: raise RuntimeError(f'PARENT_RESULTS_BINDING_BLOCK:{len(parent_rows)}:{len(parent_ids)}')
    replay=json.loads(replay_path.read_text(encoding='utf-8')); exact88=ids_from_replay(replay)
    final=json.loads(final_path.read_text(encoding='utf-8'))
    if final.get('status')!='V2_9_HISTORICAL_E_SOURCE_EXPANSION_TOO_SPARSE': raise RuntimeError('PARENT_TERMINAL_STATUS_BLOCK')

    work=OUT_DIR/'runtime'; work.mkdir(exist_ok=True)
    collector=work/'v284_candidate_collector_parent.py'
    src=subprocess.check_output(['git','show',f'{PARENT}:{COLLECTOR_PATH}'])
    collector.write_bytes(src)
    parent_blob=subprocess.check_output(['git','rev-parse',f'{PARENT}:{COLLECTOR_PATH}'],text=True).strip()
    if subprocess.check_output(['git','hash-object',str(collector)],text=True).strip()!=parent_blob: raise RuntimeError('PARENT_COLLECTOR_BLOB_BLOCK')
    census=work/'census'
    subprocess.run([sys.executable,str(collector),'collect','--start',START,'--end',END,'--out',str(census)],check=True)
    recovered_path=census/'V2.8.4_CNINFO_CANDIDATE_DEDUPED.csv'
    collector_receipt_path=census/'V2.8.4_CNINFO_CANDIDATE_COLLECTION_RECEIPT.json'
    recovered=read_csv(recovered_path)
    recovered_ids=[str(r.get('announcement_id') or '').strip() for r in recovered]
    recset=set(recovered_ids)
    collector_receipt=json.loads(collector_receipt_path.read_text(encoding='utf-8'))

    tests=[]
    def ck(name,v,detail=None): tests.append({'name':name,'pass':bool(v),**({'detail':detail} if detail is not None else {})})
    ck('R01_parent_results_277_exact',len(parent_rows)==277 and len(parent_ids)==277)
    ck('R02_parent_exact88_artifact_pass',len(exact88)==88)
    ck('R03_recovered_ids_nonempty_unique',bool(recovered_ids) and len(recovered_ids)==len(recset) and '' not in recset,{'rows':len(recovered_ids)})
    missing_parent=sorted(parent_ids-recset); missing88=sorted(exact88-recset)
    ck('R04_all_parent_277_ids_recovered',not missing_parent,{'missing_count':len(missing_parent),'sample':missing_parent[:10]})
    ck('R05_all_parent_exact88_ids_recovered',not missing88,{'missing_count':len(missing88),'sample':missing88[:10]})
    ck('R06_collector_no_classification',collector_receipt.get('real_security_classification_computed') is False)
    ck('R07_collector_no_price_return',collector_receipt.get('price_or_return_data_consumed') is False)
    ck('R08_candidate_hint_only',collector_receipt.get('eligibility_effect')=='NONE_CANDIDATE_HINT_ONLY')
    ck('R09_range_exact',collector_receipt.get('window_start')==START and collector_receipt.get('window_end')==END)
    ck('R10_terms_exact_18',len(collector_receipt.get('terms') or [])==18 and len(set(collector_receipt.get('terms') or []))==18)
    ok=all(x['pass'] for x in tests)

    with OUT_IDS.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f,lineterminator='\n'); w.writerow(['announcement_id'])
        for aid in sorted(recset): w.writerow([aid])
    out={
      'schema':'AI_CORE_EVID_V2_9_1_COMPARISON_AUTHORITY_RECOVERY_RECEIPT_1','version':'V2.9.1',
      'status':'V2_9_1_COMPARISON_AUTHORITY_RECOVERED_CONSERVATIVE' if ok else 'V2_9_1_COMPARISON_AUTHORITY_RECOVERY_TECHNICALLY_BLOCKED',
      'parent_run_id':c['parent']['run_id'],'parent_head_sha':PARENT,'parent_collector_blob_sha':parent_blob,
      'parent_results_sha256':sha_file(results_path),'parent_replay_sha256':sha_file(replay_path),'parent_final_sha256':sha_file(final_path),
      'recovered_candidate_count':len(recset),'recovered_candidate_ids_sha256':sha_file(OUT_IDS),
      'recovered_candidate_csv_sha256':sha_file(recovered_path),'collector_receipt_sha256':sha_file(collector_receipt_path),
      'tests':tests,'passed':sum(x['pass'] for x in tests),'total':len(tests),'all_pass':ok,
      'scientific_classification_executed':False,'triage_executed':False,'pdf_materialization_executed':False,
      'price_or_return_data_consumed':False,'candidate_outcome_research_executed':False,'fold3_accessed':False,'fold4_accessed':False,
      'authorization':{'negative_space_batch1_allowed':ok}
    }
    out['receipt_sha256']=stable_sha(out)
    OUT_RECEIPT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if not ok: raise SystemExit(2)

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--parent-artifact',required=True); a=ap.parse_args(); main(Path(a.parent_artifact))
