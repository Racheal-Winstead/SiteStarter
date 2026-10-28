"""Scoring the review loop on recorded cases: end-to-end, per-agent, and handoff."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sitestarter.eval_loop import CaseError, load_cases, run_case, score

ROOT = Path(__file__).resolve().parents[1]
BRIEF = json.loads((ROOT / "examples/bakery-brief.json").read_text())
CASES = json.loads((ROOT / "examples/eval-cases.json").read_text())


def one_case(**case):
    data = copy.deepcopy(CASES)
    data["cases"] = [dict({"id": "c", "content_agent": [], "design_agent": []}, **case)]
    return data


def run_cli(cases, brief=None):
    with tempfile.TemporaryDirectory() as tmp:
        cases_file, brief_file = Path(tmp) / "cases.json", Path(tmp) / "brief.json"
        cases_file.write_text(cases if isinstance(cases, str) else json.dumps(cases))
        brief_file.write_text(json.dumps(BRIEF if brief is None else brief))
        return subprocess.run([sys.executable, "-m", "sitestarter.eval_loop", "--brief", str(brief_file),
                               "--cases", str(cases_file)],
                              cwd=ROOT, capture_output=True, text=True, timeout=60)


class ShippedCasesTests(unittest.TestCase):
    def test_every_shipped_case_ends_as_expected(self):
        runs = [run_case(case) for case in load_cases(CASES, BRIEF)]
        misses = [(r["id"], r["status"], r["stage"]) for r in runs if not r["matched"]]
        self.assertEqual(misses, [])
        self.assertGreaterEqual(len(runs), 10)

    def test_shipped_cases_cover_ready_and_each_kind_of_stop(self):
        stages = {case["expect"]["stage"] for case in CASES["cases"]}
        for stage in ("done", "brief", "review_loop", "content_agent:plan", "design_agent:plan",
                      "design_agent:review"):
            self.assertIn(stage, stages)

    def test_cli_reports_three_dimensions_and_the_recorded_caveat(self):
        run = subprocess.run([sys.executable, "-m", "sitestarter.eval_loop", "--brief", "examples/bakery-brief.json",
                              "--cases", "examples/eval-cases.json"],
                             cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        for text in ("End-to-end success:", "Per-agent contribution:", "Handoff success",
                     "final plan gate passed", "not live AI"):
            self.assertIn(text, run.stdout)


class ScoringTests(unittest.TestCase):
    def fake_run(self, matched=True, stage="done", status="ready", calls=()):
        return {"id": "x", "expect": {"status": status, "stage": stage}, "status": status, "stage": stage,
                "has_page": status == "ready", "matched": matched, "errors": [], "calls": list(calls)}

    def call(self, agent, kind, attempt, accepted):
        return {"agent": agent, "kind": kind, "round": 0, "attempt": attempt, "accepted": accepted}

    def test_counts_first_replies_retries_and_handoffs_separately(self):
        calls = [self.call("content_agent", "plan", 1, False), self.call("content_agent", "plan", 2, True),
                 self.call("design_agent", "plan", 1, True), self.call("design_agent", "review", 1, True)]
        s = score([self.fake_run(calls=calls)])
        self.assertEqual(s["per_agent"]["content_agent"],
                         {"first_replies": 1, "first_accepted": 0, "retries": 1, "retries_accepted": 1,
                          "stopped_runs": 0, "unexpected_stops": 0})
        self.assertEqual(s["handoffs"]["content_agent:plan"], {"accepted": 1, "replies": 2})
        self.assertEqual(s["handoffs"]["design_agent:review"], {"accepted": 1, "replies": 1})

    def test_unexpected_stop_is_charged_to_the_agent_that_stopped(self):
        expected = self.fake_run(status="failed", stage="design_agent:review")
        surprise = dict(self.fake_run(status="ready", stage="done"), status="failed",
                        stage="content_agent:revise", matched=False)
        s = score([expected, surprise])
        self.assertEqual((s["per_agent"]["design_agent"]["stopped_runs"],
                          s["per_agent"]["design_agent"]["unexpected_stops"]), (1, 0))
        self.assertEqual((s["per_agent"]["content_agent"]["stopped_runs"],
                          s["per_agent"]["content_agent"]["unexpected_stops"]), (1, 1))
        self.assertEqual(s["end_to_end"]["matched"], 1)
        self.assertEqual(s["end_to_end"]["ready_built"], 0)

    def test_gate_and_final_checks_only_count_runs_that_reached_them(self):
        runs = [self.fake_run(), self.fake_run(status="failed", stage="plan_gate"),
                self.fake_run(status="failed", stage="final_checks"),
                self.fake_run(status="failed", stage="review_loop")]
        s = score(runs)
        self.assertEqual(s["plan_gate"], {"reached": 3, "passed": 2})
        self.assertEqual(s["final_checks"], {"reached": 2, "passed": 1})

    def test_a_ready_page_where_failure_was_expected_is_a_miss(self):
        data = one_case(content_agent=[{"plan": {}}, {"review": "agree", "round": 1}],
                        design_agent=[{"plan": {}}, {"review": "agree", "round": 1}],
                        expect={"status": "failed", "stage": "review_loop"})
        run = run_case(load_cases(data, BRIEF)[0])
        self.assertFalse(run["matched"])
        self.assertTrue(run["has_page"])

    def test_a_failed_run_that_still_returns_a_page_is_a_miss(self):
        import sitestarter.eval_loop as eval_loop
        original = eval_loop.run_planning_loop
        eval_loop.run_planning_loop = lambda brief, content, design: {
            "status": "failed", "stage": "review_loop", "errors": [], "calls": [], "html": "<p>leaked</p>"}
        try:
            data = one_case(expect={"status": "failed", "stage": "review_loop"})
            run = run_case(load_cases(data, BRIEF)[0])
        finally:
            eval_loop.run_planning_loop = original
        self.assertFalse(run["matched"])


class CaseFileTests(unittest.TestCase):
    def test_bad_case_files_are_rejected_with_a_reason(self):
        bad = [
            ({}, "non-empty cases list"),
            (dict(CASES, base={}), "base.content_plan"),
            (one_case(id=""), "needs a text id"),
            (one_case(expect={"status": "ready"}), "expect needs status and stage"),
            (one_case(expect={"status": "ready", "stage": "done"}, content_agent=[{}]), "exactly one of"),
            (one_case(expect={"status": "ready", "stage": "done"},
                      content_agent=[{"plan": {}, "raw": "x"}]), "exactly one of"),
            (one_case(expect={"status": "ready", "stage": "done"}, design_agent=[{"error": "OSError"}]),
             "error must be one of"),
            (one_case(expect={"status": "ready", "stage": "done"}, content_agent="plan"), "must be a list"),
            (one_case(expect={"status": "ready", "stage": "done"}, brief_changes=[]), "brief_changes"),
        ]
        for data, message in bad:
            with self.subTest(message=message):
                with self.assertRaises(CaseError) as caught:
                    load_cases(data, BRIEF)
                self.assertIn(message, str(caught.exception))

    def test_duplicate_ids_are_rejected(self):
        data = copy.deepcopy(CASES)
        data["cases"].append(copy.deepcopy(data["cases"][0]))
        with self.assertRaises(CaseError):
            load_cases(data, BRIEF)

    def test_cli_exits_1_on_a_miss_and_names_it(self):
        data = one_case(content_agent=[{"plan": {}}, {"review": "agree", "round": 1}],
                        design_agent=[{"plan": {}}, {"review": "agree", "round": 1}],
                        expect={"status": "failed", "stage": "review_loop"})
        run = run_cli(data)
        self.assertEqual(run.returncode, 1)
        self.assertIn("MISS c: ready/done (expected failed/review_loop)", run.stdout)

    def test_cli_fails_cleanly_on_bad_input(self):
        for cases, brief in (("not json", None), ("[" * 5000 + "]" * 5000, None), (CASES, ["not", "a", "brief"])):
            with self.subTest(cases=str(cases)[:20], brief=brief):
                run = run_cli(cases, brief)
                self.assertEqual(run.returncode, 1)
                self.assertIn("Eval failed:", run.stderr)
                self.assertNotIn("Traceback", run.stderr)


if __name__ == "__main__":
    unittest.main()
