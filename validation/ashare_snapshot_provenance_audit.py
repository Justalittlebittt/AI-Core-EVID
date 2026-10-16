"""Independent fail-closed provenance audit; does not alter frozen market admission criteria."""
import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

REQUIRED = {'index_id','date','close','source_id','retrieved_at_utc'}
PROVIDER = 'AKSHARE_INDEX_ZH_A_HIST_EASTMONEY'
INDEXES = {'000300.SH','000688.SH'}


def audit(snapshot: Path, manifest: Path) -> dict:
    data = snapshot.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    m = json.loads(manifest.read_text(encoding='utf-8'))
    if m.get('schema') != 'AI_CORE_EVID_ASHARE_INDEX_SOURCE_SNAPSHOT_V1':
        raise ValueError('MANIFEST_SCHEMA_BLOCK')
    if m.get('snapshot_sha256') != sha:
        raise ValueError('MANIFEST_SNAPSHOT_HASH_MISMATCH')
    if m.get('source') != 'AKShare.index_zh_a_hist/Eastmoney':
        raise ValueError('MANIFEST_SOURCE_BLOCK')
    if m.get('historical_PIT_verified') is not False:
        raise ValueError('MANIFEST_PIT_CLAIM_BLOCK')
    ts = datetime.fromisoformat(str(m['captured_at_utc']).replace('Z','+00:00'))
    if ts.utcoffset() != timezone.utc.utcoffset(ts):
        raise ValueError('MANIFEST_CAPTURE_NOT_UTC')
    start = date.fromisoformat(m['query_start_date'])
    end = date.fromisoformat(m['query_end_date'])
    if start > end:
        raise ValueError('MANIFEST_INVALID_QUERY_RANGE')
    counts = Counter()
    seen = set()
    with snapshot.open(encoding='utf-8-sig',newline='') as f:
        reader = csv.DictReader(f)
        if set(reader.fieldnames or []) != REQUIRED:
            raise ValueError('SNAPSHOT_COLUMNS_BLOCK')
        for r in reader:
            if r['index_id'] not in INDEXES:
                raise ValueError('SNAPSHOT_INDEX_BLOCK')
            if r['source_id'] != PROVIDER:
                raise ValueError('SNAPSHOT_SOURCE_BLOCK')
            row_timestamp = datetime.fromisoformat(r['retrieved_at_utc'].replace('Z', '+00:00'))
            if row_timestamp.utcoffset() != timezone.utc.utcoffset(row_timestamp):
                raise ValueError('ROW_CAPTURE_NOT_UTC')
            if row_timestamp != ts:
                raise ValueError('CAPTURE_TIMESTAMP_MISMATCH')
            trading_day = date.fromisoformat(r['date'])
            if not (start <= trading_day <= end):
                raise ValueError('SNAPSHOT_DATE_OUT_OF_QUERY')
            close = float(r['close'])
            if not math.isfinite(close) or close <= 0:
                raise ValueError('SNAPSHOT_CLOSE_INVALID')
            key = (r['index_id'], trading_day)
            if key in seen:
                raise ValueError('SNAPSHOT_DUPLICATE_INDEX_DATE')
            seen.add(key)
            counts[r['index_id']] += 1
    if set(counts) != INDEXES or dict(counts) != m.get('rows_per_index'):
        raise ValueError('MANIFEST_ROW_COUNTS_MISMATCH')
    return {'status':'PASS_PROVENANCE_BINDING_ONLY','snapshot_sha256':sha,
            'rows_per_index':dict(counts),'historical_PIT_verified':False,
            'market_close_verified':False,'trading_authorized':False}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input-csv',type=Path,required=True)
    p.add_argument('--manifest-json',type=Path,required=True)
    x=p.parse_args()
    print(json.dumps(audit(x.input_csv,x.manifest_json),sort_keys=True))


if __name__ == '__main__':
    main()
