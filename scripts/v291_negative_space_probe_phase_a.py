from __future__ import annotations

import csv, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

CONTRACT=Path('evidence/V2.9.1_NEGATIVE_SPACE_PROBE_CONTRACT_1.json')
MAP=Path('evidence/V2.7.27_SECURITY_ISSUER_PIT_MAP.csv')
MANIFESTS=[
 Path('evidence/V2.8.5_BACKWARD_HOLDOUT_SAMPLE_MANIFEST.csv'),
 Path('evidence/V2.8.6_FOLD1_MECHANISM_REPLICATION_MANIFEST.csv'),
 Path('evidence/V2.8.7_FOLD2_SETUP_SHAPE_MANIFEST.csv')]
OUT=Path('evidence/V2.9.1_NEGATIVE_SPACE_PROBE_PHASE_A_VALIDATION_1.json')
BEIJING=ZoneInfo('Asia/Shanghai')
START='2023-01-01'; END='2024-12-30'
EXPECTED_MANIFEST_SHA=[
 '199864ece6c02f3257647d59ba63fe261a7b478a2525b7ed8042bbf475a9fe48',
 'fe15777a0a3a131b58288454a0e3023503bd80ac6a22f20a2e50c45a4deed38a',
 '79b6a4c752a22a16f6ec7167dfb1e6b007473229d7ec6729fb03a15b3ba0fa9a']
EXPECTED_COUNTS=[1031,1058,1048]

def sha_file(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def stable_sha(o): return hashlib.sha256(json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def rows(p): return list(csv.DictReader(p.open(encoding='utf-8')))
def cid_of(r):
    for k in ('canonical_security_id','security_id','canonical_id'):
        if str(r.get(k) or '').strip(): return str(r[k]).strip()
    raise RuntimeError(f'NO_CANONICAL_ID_COLUMN:{p}')

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
        page.wait_for_timeout(1200)
        ins=page.locator('input')
        for i in range(min(ins.count(),12)):
            try:
                el=ins.nth(i)
                if not el.is_visible(): continue
                ph=el.get_attribute('placeholder') or ''
                if any(x in ph for x in ('代码','简称','关键')):
                    el.fill(code); el.press('Enter'); page.wait_for_timeout(1800); break
            except Exception: pass
    finally: page.remove_listener('request',on_req)
    u=sorted(set(matches))
    if len(u)!=1: raise RuntimeError(f'ORG_ID_UNRESOLVED:{code}:{u}')
    return u[0]

def query_blank(page,code,org,exchange):
    base={'column':'sse' if exchange=='SSE' else 'szse','tabName':'fulltext','plate':'sh' if exchange=='SSE' else 'sz',
          'stock':f'{code},{org}','searchkey':'','secid':'','category':'','trade':'','seDate':f'{START}~{END}',
          'sortName':'','sortType':'','isHLtitle':'true','pageNum':'1','pageSize':'30'}
    first=json.loads(post(page,base)); total=int(first.get('totalRecordNum') or first.get('totalAnnouncement') or 0)
    got=[]; ids=set(); page_no=1
    while len(got)<total:
        o=first if page_no==1 else json.loads(post(page,{**base,'pageNum':str(page_no)}))
        anns=o.get('announcements') or []
        if not anns and len(got)<total: raise RuntimeError(f'PAGINATION_EARLY:{len(got)}/{total}')
        for a in anns:
            aid=str(a.get('announcementId') or '').strip()
            if aid and aid not in ids: ids.add(aid); got.append(a)
        page_no+=1
        if page_no>1000: raise RuntimeError('PAGINATION_RUNAWAY')
    if len(got)!=total: raise RuntimeError(f'PAGINATION_MISMATCH:{len(got)}/{total}')
    for a in got:
        ms=a.get('announcementTime')
        if ms is not None:
            d=datetime.fromtimestamp(int(ms)/1000,tz=timezone.utc).astimezone(BEIJING).date().isoformat()
            if not (START<=d<=END): raise RuntimeError(f'DATE_BOUND_ESCAPE:{d}')
        url=str(a.get('adjunctUrl') or '')
        if url and not re.search(r'/finalpage/\d{4}-\d{2}-\d{2}/',url): raise RuntimeError('OFFICIAL_LOCATOR_SHAPE_BLOCK')
    return {'official_total':total,'deduped_count':len(got),'pages_fetched':page_no-1,'sample_ids':[str(x.get('announcementId') or '') for x in got[:5]]}

def main():
    c=json.loads(CONTRACT.read_text(encoding='utf-8'))
    tests=[]
    def ck(n,v): tests.append({'name':n,'pass':bool(v)})
    ck('A01_contract_frozen',c.get('schema')=='AI_CORE_EVID_V2_9_1_NEGATIVE_SPACE_PROBE_CONTRACT_1' and c.get('status')=='FROZEN_BEFORE_IMPLEMENTATION')
    ck('A02_no_scientific_classification_phase_a',c['probe_design']['phase_a_transport_validation']['real_ai_classification_allowed'] is False)
    ck('A03_manifest_hashes_exact',[sha_file(x) for x in MANIFESTS]==EXPECTED_MANIFEST_SHA)
    sets=[]
    for p,n in zip(MANIFESTS,EXPECTED_COUNTS):
        rr=rows(p); ck(f'A_manifest_count_{p.name}',len(rr)==n); sets.append({cid_of(x) for x in rr})
    ck('A04_manifests_pairwise_disjoint',not (sets[0]&sets[1] or sets[0]&sets[2] or sets[1]&sets[2]))
    ck('A05_identity_map_exact',sha_file(MAP)==c['invariants']['issuer_identity_map']['sha256'])
    order=sorted(set().union(*sets),key=lambda x:(hashlib.sha256(x.encode()).hexdigest(),x))
    fixtures=order[:3]
    m={r['canonical_security_id']:r for r in rows(MAP)}
    ck('A06_fixture_membership_exact',len(fixtures)==3 and all(x in m for x in fixtures))
    transport=[]
    try:
        with sync_playwright() as pw:
            b=pw.chromium.launch(headless=True); page=b.new_page(locale='zh-CN')
            page.goto('https://www.cninfo.com.cn/',wait_until='domcontentloaded',timeout=90000); page.wait_for_timeout(1000)
            for cid in fixtures:
                r=m[cid]; org=resolve_org(page,r['security_code']); q=query_blank(page,r['security_code'],org,r['exchange'])
                transport.append({'canonical_security_id':cid,'exchange':r['exchange'],'security_code':r['security_code'],'org_id':org,**q})
            b.close()
        ck('A07_blank_searchkey_transport_real',True)
        ck('A08_pagination_closed',all(x['official_total']==x['deduped_count'] for x in transport))
    except Exception as e:
        transport.append({'blocker':f'{type(e).__name__}:{e}'}); ck('A07_blank_searchkey_transport_real',False); ck('A08_pagination_closed',False)
    auth=c['authorization']
    ck('A09_no_price_outcome_fold34',auth['price_or_return_access'] is False and auth['candidate_outcome_research'] is False and auth['fold3_access'] is False and auth['fold4_access'] is False)
    ok=all(x['pass'] for x in tests)
    out={'schema':'AI_CORE_EVID_V2_9_1_NEGATIVE_SPACE_PROBE_PHASE_A_VALIDATION_1','version':'V2.9.1','status':'PASS' if ok else 'V2_9_1_NEGATIVE_SPACE_PROBE_TECHNICALLY_BLOCKED','tests':tests,'passed':sum(x['pass'] for x in tests),'total':len(tests),'all_pass':ok,'fixture_security_ids':fixtures,'transport_evidence':transport,'real_ai_classification_executed':False,'price_or_return_data_consumed':False,'candidate_outcome_research_executed':False,'fold3_accessed':False,'fold4_accessed':False,'authorization':{'execute_scientific_probe':ok,'price_or_return_access':False,'candidate_outcome_research':False,'fold3_access':False,'fold4_access':False}}
    out['receipt_sha256']=stable_sha(out); OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if not ok: raise SystemExit(2)

if __name__=='__main__': main()
