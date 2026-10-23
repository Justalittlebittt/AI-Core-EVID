#!/usr/bin/env python3
"""Classify recent read-only Actions visibility results; no GitHub writes."""
import argparse
import datetime as dt
import json
import sys

def assess(data, now, hours=24):
    if not data.get("coverage_complete"):
        raise ValueError("Actions run enumeration incomplete")
    cutoff = now - dt.timedelta(hours=hours)
    incidents = []
    for run in data["runs"]:
        created = dt.datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        if created > now or created < cutoff:
            continue
        if run.get("pre_job_failure_candidate"):
            incidents.append({"id": run["id"], "url": run["url"], "reason": "zero_job_failed_attempt", "attempts": run.get("zero_job_failed_attempts", [])})
    return incidents

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--strict", action="store_true", help="Exit 1 only for confirmed recent zero-job failures")
    args = parser.parse_args()
    if args.hours <= 0 or args.hours > 168:
        parser.error("--hours must be 1..168")
    try:
        with open(args.input_json, encoding="utf-8") as stream:
            data = json.load(stream)
        incidents = assess(data, dt.datetime.now(dt.timezone.utc), args.hours)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("MONITOR_ERROR: " + str(exc), file=sys.stderr)
        return 2
    if incidents:
        print("NEW_ZERO_JOB_FAILURE_CANDIDATES " + json.dumps(incidents))
        return 1 if args.strict else 0
    print("HEALTHY: no recent zero-job failure candidates; no action required")
    return 0

if __name__ == "__main__":
    sys.exit(main())
