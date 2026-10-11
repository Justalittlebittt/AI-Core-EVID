# V2.9.3 Batch-3 portable execution (non-GitHub Runner)

Status: IMPLEMENTED / RUNTIME NOT VALIDATED. This does not claim Batch-3 completed.

## Contract
- Existing seven chunk receipts 1,2,4,5,6,7,8 are immutable.
- Only chunk 3 (ranks 145-152) may be reconstructed.
- Frozen source runner and aggregator Git blobs are verified before starting.
- Frozen prerequisite artifacts are sha256-verified before starting.
- No fold3/fold4, prices, returns, threshold/classifier/triage changes.
- Batch-4 is never automatically authorized.
- Terminal receipt `evidence/V2.9.3_PORTABLE_EXECUTION_TERMINAL_1.json` is operational, not a scientific conclusion.
- If the process/machine is killed, a terminal receipt may not be written; do not interpret absence as PASS.
- No automatic git push. Evidence must be reviewed and explicitly persisted.

## Setup on a free existing Python 3.12 workstation, VM, or other authorized executor
From the repository root:

```bash
python -m pip install "playwright>=1.55" "PyMuPDF>=1.24,<2" "pandas>=2.2"
python -m playwright install chromium
python scripts/v293_batch3_portable_launch.py --preflight-only
python scripts/v293_batch3_portable_launch.py
```

A container or Linux runner additionally needs Chromium system libraries; a compatible machine is required. The network must reach CNINFO and dependencies must be installed before running. Running the script from arbitrary working directories is supported.

## Inspect result
- `V2.9.3_PORTABLE_EXECUTION_TERMINAL_1.json`: execution completed or blocked
- `V2.9.3_BATCH3_RECONSTRUCTION_CHUNK_03_RECEIPT_1.json`: chunk completeness
- `V2.9.3_RECONSTRUCTED_BATCH3_RECEIPT_1.json`: authoritative aggregate scientific status
- Re-run uses the chunk's existing complete receipt when legitimate. On an incomplete chunk, it restarts chunk-3 scope only.
- No aggregate PASS until hash/membership checks run and the aggregate receipt is produced.

## Known unclosed risks
- The underlying frozen chunk-3 runner only emits a full chunk receipt after its loop finishes; abrupt machine failure may leave a partial progress/results file. This launcher marks controlled subprocess failures as BLOCKED but cannot guarantee durable evidence after power loss.
- The frozen aggregator may leave intermediate CSV output on failure; terminal receipt must not be treated as scientific PASS.
- Hosted Runner provisioning failure cannot be fixed by Python code. This is a different execution path, not proof GitHub service recovered.
