#!/usr/bin/env python3
"""Read-only GitHub Actions run visibility check. No workflow dispatch or writes."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"

def get(path, token):
    request = urllib.request.Request(
        API + path,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ai-core-evid-readonly-diagnostic",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", default="Justalittlebittt/AI-Core-EVID")
    p.add_argument("--since", help="UTC inclusive date, e.g. 2026-10-21")
    p.add_argument("--pages", type=int, default=3)
    args = p.parse_args()
    if args.since:
        try:
            import datetime as datetime_module
            datetime_module.date.fromisoformat(args.since)
        except ValueError:
            p.error("--since must be YYYY-MM-DD")
    if args.pages < 1 or args.pages > 20:
        p.error("--pages must be 1..20")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GH_TOKEN or GITHUB_TOKEN with Actions:read is required", file=sys.stderr)
        return 2
    if "/" not in args.repo or args.repo.count("/") != 1:
        p.error("--repo must be owner/name")
    base = "/repos/" + "/".join(urllib.parse.quote(s, safe="") for s in args.repo.split("/"))
    results = []
    complete = False
    try:
        for page in range(1, args.pages + 1):
            data = get(base + "/actions/runs?per_page=100&page=" + str(page), token)
            runs = data["workflow_runs"]
            for run in runs:
                created = run["created_at"][:10]
                if args.since and created < args.since:
                    complete = True
                    break
                name = run.get("name") or ""
                if "V2.8.4 Controlled Prospective E-Layer Observation" not in name and "Infrastructure Smoke Diagnostic" not in name:
                    continue
                run_id = run["id"]
                attempts = run.get("run_attempt") or 1
                counts = []
                attempt_conclusions = []
                for attempt in range(1, attempts + 1):
                    # Per-attempt endpoint preserves failures hidden by a successful rerun.
                    jobs = get(base + "/actions/runs/" + str(run_id) + "/attempts/" + str(attempt) + "/jobs?per_page=1", token)
                    counts.append(jobs["total_count"])
                    details = get(base + "/actions/runs/" + str(run_id) + "/attempts/" + str(attempt), token)
                    attempt_conclusions.append(details.get("conclusion"))
                count = counts[-1]
                zero_job_failed_attempts = [i + 1 for i, value in enumerate(counts) if value == 0 and attempt_conclusions[i] == "failure"]
                results.append({
                    "id": run_id,
                    "name": name,
                    "created_at": run["created_at"],
                    "status": run["status"],
                    "conclusion": run.get("conclusion"),
                    "run_attempt": run.get("run_attempt"),
                    "jobs_total": count,
                    "jobs_per_attempt": counts,
                    "attempt_conclusions": attempt_conclusions,
                    "zero_job_failed_attempts": zero_job_failed_attempts,
                    "pre_job_failure_candidate": bool(zero_job_failed_attempts),
                    "url": run["html_url"],
                })
            if complete or len(runs) < 100:
                complete = True
                break
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError, ValueError) as error:
        print("ERROR: incomplete Actions API inspection: " + str(error), file=sys.stderr)
        return 2
    output = {"repo": args.repo, "since": args.since, "coverage_complete": complete, "runs": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if not complete:
        print("ERROR: pagination cap reached; results are incomplete", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
