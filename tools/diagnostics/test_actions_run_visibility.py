"""Offline tests for the read-only Actions diagnostic; no GitHub calls."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).with_name("actions_run_visibility.py")
spec = importlib.util.spec_from_file_location("actions_run_visibility", MODULE_PATH)
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)

class RunVisibilityTests(unittest.TestCase):
    def invoke(self, responses, pages=3):
        def fake_get(path, token):
            if "/actions/runs?" in path:
                page = int(path.rsplit("page=", 1)[1])
                return {"workflow_runs": responses["pages"].get(page, [])}
            parts = path.split("/actions/runs/")[1].split("/")
            run_id = parts[0]
            attempt = parts[2]
            if path.endswith("/jobs?per_page=1"):
                return {"total_count": responses["jobs"].get(run_id + ":" + attempt, responses["jobs"].get(run_id))}
            return {"conclusion": responses.get("conclusions", {}).get(run_id + ":" + attempt, responses["pages"][1][0].get("conclusion"))}
        out, err = io.StringIO(), io.StringIO()
        args = ["diagnostic", "--since", "2026-10-21", "--pages", str(pages)]
        with patch.object(sys, "argv", args), patch.dict(os.environ, {"GH_TOKEN": "test-token"}), patch.object(diagnostic, "get", fake_get), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = diagnostic.main()
        return code, out.getvalue(), err.getvalue()

    def run_data(self, run_id, conclusion, name="V2.8.4 Controlled Prospective E-Layer Observation"):
        return {"id": run_id, "name": name, "created_at": "2026-10-22T06:00:00Z", "status": "completed", "conclusion": conclusion, "run_attempt": 1, "html_url": f"https://github.com/example/actions/runs/{run_id}"}

    def test_zero_job_failure_flagged(self):
        responses = {"pages": {1: [self.run_data(11, "failure")]}, "jobs": {"11": 0}}
        code, out, _ = self.invoke(responses)
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["runs"][0]["pre_job_failure_candidate"])

    def test_successful_run_not_flagged(self):
        responses = {"pages": {1: [self.run_data(12, "success")]}, "jobs": {"12": 1}}
        code, out, _ = self.invoke(responses)
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["runs"][0]["pre_job_failure_candidate"])

    def test_old_attempt_checked_after_successful_rerun(self):
        run = self.run_data(14, "success")
        run["run_attempt"] = 2
        responses = {"pages": {1: [run]}, "jobs": {"14:1": 0, "14:2": 1}, "conclusions": {"14:1": "failure", "14:2": "success"}}
        code, out, _ = self.invoke(responses)
        self.assertEqual(code, 0)
        item = json.loads(out)["runs"][0]
        self.assertEqual(item["jobs_per_attempt"], [0, 1])
        self.assertEqual(item["zero_job_failed_attempts"], [1])

    def test_cancelled_zero_job_attempt_not_failure(self):
        run = self.run_data(15, "cancelled")
        responses = {"pages": {1: [run]}, "jobs": {"15": 0}}
        code, out, _ = self.invoke(responses)
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["runs"][0]["pre_job_failure_candidate"])

    def test_unknown_workflow_not_reported(self):
        responses = {"pages": {1: [self.run_data(13, "failure", "Other workflow")]}, "jobs": {}}
        code, out, _ = self.invoke(responses)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["runs"], [])

    def test_page_cap_fails_closed(self):
        responses = {"pages": {1: [self.run_data(n, "success", "Other workflow") for n in range(100)]}, "jobs": {}}
        code, out, err = self.invoke(responses, pages=1)
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out)["coverage_complete"])
        self.assertIn("incomplete", err)

    def test_api_failure_fails_closed(self):
        with patch.object(sys, "argv", ["diagnostic"]), patch.dict(os.environ, {"GH_TOKEN": "test-token"}), patch.object(diagnostic, "get", side_effect=KeyError("workflow_runs")), contextlib.redirect_stderr(io.StringIO()) as err:
            code = diagnostic.main()
        self.assertEqual(code, 2)
        self.assertIn("incomplete", err.getvalue())

if __name__ == "__main__":
    unittest.main()
