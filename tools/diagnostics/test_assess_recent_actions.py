"""Offline regression tests of recent-incident selection."""
import datetime as dt
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("assess", Path(__file__).with_name("assess_recent_actions.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
NOW = dt.datetime(2026, 10, 23, 12, tzinfo=dt.timezone.utc)

def run(at, failure):
    return {"id": 123, "url": "https://github.com/test/actions/runs/123", "created_at": at, "pre_job_failure_candidate": failure, "zero_job_failed_attempts": [1] if failure else []}

class AssessmentTests(unittest.TestCase):
    def test_recent_failure(self):
        self.assertEqual(len(mod.assess({"coverage_complete": True, "runs": [run("2026-10-23T11:00:00Z", True)]}, NOW)), 1)
    def test_old_failure_is_silent(self):
        self.assertEqual(mod.assess({"coverage_complete": True, "runs": [run("2026-10-21T11:00:00Z", True)]}, NOW), [])
    def test_recent_success_is_silent(self):
        self.assertEqual(mod.assess({"coverage_complete": True, "runs": [run("2026-10-23T11:00:00Z", False)]}, NOW), [])
    def test_recent_job_failure_detected(self):
        item = run("2026-10-23T11:00:00Z", False)
        item.update(attempt_conclusions=["failure"], jobs_per_attempt=[1])
        incidents = mod.assess({"coverage_complete": True, "runs": [item]}, NOW)
        self.assertEqual(incidents[0]["reason"], "job_failed_attempt")

    def test_previous_failed_attempt_survives_successful_rerun(self):
        item = run("2026-10-23T11:00:00Z", False)
        item.update(attempt_conclusions=["failure", "success"], jobs_per_attempt=[1, 1])
        incidents = mod.assess({"coverage_complete": True, "runs": [item]}, NOW)
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["attempts"], [1])

    def test_cancelled_attempt_ignored(self):
        item = run("2026-10-23T11:00:00Z", False)
        item.update(attempt_conclusions=["cancelled"], jobs_per_attempt=[0])
        self.assertEqual(mod.assess({"coverage_complete": True, "runs": [item]}, NOW), [])

    def test_mismatched_attempt_metadata_fails_closed(self):
        item = run("2026-10-23T11:00:00Z", False)
        item.update(attempt_conclusions=["failure"], jobs_per_attempt=[])
        with self.assertRaises(ValueError):
            mod.assess({"coverage_complete": True, "runs": [item]}, NOW)

    def test_incomplete_scan_fails(self):
        with self.assertRaises(ValueError):
            mod.assess({"coverage_complete": False, "runs": []}, NOW)

if __name__ == "__main__":
    unittest.main()
