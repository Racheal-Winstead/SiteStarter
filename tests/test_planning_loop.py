"""Content agent <-> design agent review loop, final plan gate, and the loop demo.

Agents are scripted fakes that play back replies in order, so no API key or
live model is involved.
"""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sitestarter.planning_loop import (MAX_REVIEW_ROUNDS, final_plan_gate, run_planning_loop,
                                       validate_content_plan, validate_review)

ROOT = Path(__file__).resolve().parents[1]
BRIEF = json.loads((ROOT / "examples/bakery-brief.json").read_text())
DESIGN = json.loads((ROOT / "examples/bakery-design.json").read_text())
RID = BRIEF["request_id"]
CONTENT = {"request_id": RID, "agent_name": "content_agent", "status": "complete",
           "heading": "Fresh bread for local families", "about_text": BRIEF["about"],
           "contact": BRIEF["contact"], "missing_information": [], "warnings": []}


def review(agent, round_number, verdict="agree", requests=()):
    return {"request_id": RID, "agent_name": agent, "round": round_number,
            "verdict": verdict, "requests": list(requests)}


def ask(field, reason="please change this"):
    return {"target_field": field, "reason": reason}


def scripted(*replies):
    queue, tasks = list(replies), []

    def agent(task):
        tasks.append(task)
        if not queue:
            raise TimeoutError("no reply left")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, str) else json.dumps(item)
    agent.tasks = tasks
    return agent


def with_(base, **changes):
    plan = copy.deepcopy(base)
    plan.update(changes)
    return plan


class LoopFlowTests(unittest.TestCase):
    def test_agree_in_first_round_builds_without_revisions(self):
        content = scripted(CONTENT, review("content_agent", 1))
        design = scripted(DESIGN, review("design_agent", 1))
        result = run_planning_loop(BRIEF, content, design)
        self.assertEqual(result["status"], "ready", result["errors"])
        self.assertEqual(result["rounds"], 1)
        self.assertEqual([t["kind"] for t in content.tasks], ["plan", "review"])
        self.assertIn(CONTENT["heading"], result["html"])

    def test_design_asks_for_shorter_heading_and_revised_plan_is_built(self):
        short = with_(CONTENT, heading="Fresh bread")
        content = scripted(CONTENT, review("content_agent", 1), short, review("content_agent", 2))
        design = scripted(DESIGN, review("design_agent", 1, "revise", [ask("heading")]),
                          review("design_agent", 2))
        result = run_planning_loop(BRIEF, content, design)
        self.assertEqual(result["status"], "ready", result["errors"])
        self.assertEqual(result["rounds"], 2)
        self.assertEqual(result["content_plan"]["heading"], "Fresh bread")
        self.assertIn(">Fresh bread<", result["html"])
        revise_task = content.tasks[2]
        self.assertEqual(revise_task["kind"], "revise")
        self.assertEqual(revise_task["requests"], [ask("heading")])
        # The design agent reviews the content plan, and only the content plan.
        self.assertEqual(design.tasks[1]["content_plan"], CONTENT)
        self.assertNotIn("design_plan", design.tasks[1])

    def test_content_asks_design_to_change_typography(self):
        georgia = with_(DESIGN, typography=dict(DESIGN["typography"], body_font="Georgia"))
        content = scripted(CONTENT, review("content_agent", 1, "revise", [ask("typography")]),
                           review("content_agent", 2))
        design = scripted(DESIGN, review("design_agent", 1), georgia, review("design_agent", 2))
        result = run_planning_loop(BRIEF, content, design)
        self.assertEqual(result["status"], "ready", result["errors"])
        self.assertEqual(result["design_plan"]["typography"]["body_font"], "Georgia")

    def test_loop_stops_after_max_rounds_without_building(self):
        n = MAX_REVIEW_ROUNDS
        content = scripted(CONTENT, *[x for r in range(1, n + 1) for x in (
            review("content_agent", r), CONTENT)])
        design = scripted(DESIGN, *[review("design_agent", r, "revise", [ask("heading")])
                                    for r in range(1, n + 1)])
        result = run_planning_loop(BRIEF, content, design)
        self.assertEqual((result["status"], result["stage"]), ("failed", "review_loop"))
        self.assertEqual(result["rounds"], n)
        self.assertIsNone(result["html"])
        self.assertIn(f"did not agree after {n} rounds", result["errors"][0])
        # 2 first plans + 2 reviews per round + 1 revision for each round except the last.
        self.assertEqual(len(result["calls"]), 2 + 2 * n + (n - 1))


class HandoffCheckTests(unittest.TestCase):
    def test_changed_contact_is_rejected_then_retry_accepted(self):
        bad = with_(CONTENT, contact="sales@example.com")
        content = scripted(bad, CONTENT, review("content_agent", 1))
        design = scripted(DESIGN, review("design_agent", 1))
        result = run_planning_loop(BRIEF, content, design)
        self.assertEqual(result["status"], "ready", result["errors"])
        self.assertIn("contact must match the brief exactly", content.tasks[1]["errors"])
        self.assertEqual([c["accepted"] for c in result["calls"][:2]], [False, True])

    def test_two_bad_content_plans_stop_before_design_runs(self):
        bad = with_(CONTENT, contact="sales@example.com")
        design = scripted(DESIGN)
        result = run_planning_loop(BRIEF, scripted(bad, bad), design)
        self.assertEqual((result["status"], result["stage"]), ("failed", "content_agent:plan"))
        self.assertEqual(design.tasks, [])
        self.assertIsNone(result["html"])

    def test_bad_revision_is_caught_at_its_handoff(self):
        too_long = with_(CONTENT, heading="x" * 81)
        content = scripted(CONTENT, review("content_agent", 1), too_long, too_long)
        design = scripted(DESIGN, review("design_agent", 1, "revise", [ask("heading")]))
        result = run_planning_loop(BRIEF, content, design)
        self.assertEqual((result["status"], result["stage"]), ("failed", "content_agent:revise"))
        self.assertIsNone(result["html"])

    def test_revision_for_another_request_is_rejected(self):
        other = with_(CONTENT, request_id="someone-else")
        content = scripted(CONTENT, review("content_agent", 1), other, other)
        design = scripted(DESIGN, review("design_agent", 1, "revise", [ask("heading")]))
        result = run_planning_loop(BRIEF, content, design)
        self.assertEqual(result["stage"], "content_agent:revise")
        self.assertIn("request_id does not match the brief", result["errors"])

    def test_unexpected_fields_are_rejected(self):
        sneaky = with_(CONTENT, publish_now=True)
        self.assertIn("content plan has unexpected fields: publish_now",
                      validate_content_plan(sneaky, BRIEF))
        extra = dict(review("design_agent", 1), approve_build=True)
        self.assertTrue(validate_review(extra, BRIEF, "design_agent", 1))

    def test_reviewer_cannot_ask_for_fields_outside_its_role(self):
        # The design agent may not ask the content agent to change contact details.
        self.assertTrue(validate_review(review("design_agent", 1, "revise", [ask("contact")]),
                                        BRIEF, "design_agent", 1))
        # The content agent may not ask the design agent to reorder sections.
        self.assertTrue(validate_review(review("content_agent", 1, "revise", [ask("section_order")]),
                                        BRIEF, "content_agent", 1))

    def test_review_shape_rules(self):
        cases = [
            review("design_agent", 2),                                  # wrong round
            review("content_agent", 1),                                 # wrong agent
            review("design_agent", 1, "agree", [ask("heading")]),       # agree with requests
            review("design_agent", 1, "revise", []),                    # revise without requests
            review("design_agent", 1, "revise", [ask("heading")] * 6),  # too many requests
            review("design_agent", 1, "maybe"),                         # unknown verdict
            dict(review("design_agent", 1), round=True),                # bool is not a round
            review("design_agent", 1, "revise", [{"target_field": "heading"}]),
            review("design_agent", 1, "revise", [ask("heading", " ")]),
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertTrue(validate_review(case, BRIEF, "design_agent", 1))

    def test_invalid_review_gets_one_retry(self):
        content = scripted(CONTENT, review("content_agent", 1))
        design = scripted(DESIGN, review("design_agent", 9), review("design_agent", 1))
        result = run_planning_loop(BRIEF, content, design)
        self.assertEqual(result["status"], "ready", result["errors"])
        self.assertIn("round must be 1", design.tasks[2]["errors"])

    def test_invalid_review_twice_stops(self):
        content = scripted(CONTENT)
        design = scripted(DESIGN, "not json", "[" * 1500 + "]" * 1500)
        result = run_planning_loop(BRIEF, content, design)
        self.assertEqual((result["status"], result["stage"]), ("failed", "design_agent:review"))
        self.assertIsNone(result["html"])


class StopConditionTests(unittest.TestCase):
    def test_needs_input_stops_the_run_with_the_question(self):
        ask_user = with_(CONTENT, status="needs_input", heading=None,
                         missing_information=["What hours is the bakery open?"])
        design = scripted(DESIGN)
        result = run_planning_loop(BRIEF, scripted(ask_user), design)
        self.assertEqual((result["status"], result["stage"]), ("needs_input", "content_agent:plan"))
        self.assertEqual(result["errors"], ["What hours is the bakery open?"])
        self.assertEqual(design.tasks, [])

    def test_model_errors_use_the_attempts(self):
        result = run_planning_loop(BRIEF, scripted(TimeoutError(), ConnectionError()), scripted())
        self.assertEqual((result["status"], result["stage"]), ("failed", "content_agent:plan"))
        self.assertEqual(result["errors"], ["model call failed: ConnectionError"])

    def test_deadline_stops_the_run(self):
        ticks = iter([0, 0, 1, 300, 300, 300])
        content = scripted(CONTENT, review("content_agent", 1))
        design = scripted(DESIGN, review("design_agent", 1))
        result = run_planning_loop(BRIEF, content, design, clock=lambda: next(ticks))
        self.assertEqual((result["status"], result["stage"]), ("failed", "timed_out"))
        self.assertIsNone(result["html"])

    def test_bad_brief_stops_before_any_agent_runs(self):
        content, design = scripted(), scripted()
        result = run_planning_loop(dict(BRIEF, contact=""), content, design)
        self.assertEqual((result["status"], result["stage"]), ("failed", "brief"))
        self.assertEqual((content.tasks, design.tasks), ([], []))


class FinalPlanGateTests(unittest.TestCase):
    def test_gate_passes_matching_plans(self):
        self.assertEqual(final_plan_gate(BRIEF, CONTENT, DESIGN), [])

    def agreeing_agents(self):
        return (scripted(CONTENT, review("content_agent", 1)),
                scripted(DESIGN, review("design_agent", 1)))

    def test_run_stops_when_gate_fails(self):
        import sitestarter.planning_loop as loop
        original = loop.final_plan_gate
        loop.final_plan_gate = lambda brief, content, design: ["forced gate failure"]
        try:
            result = run_planning_loop(BRIEF, *self.agreeing_agents())
        finally:
            loop.final_plan_gate = original
        self.assertEqual((result["status"], result["stage"]), ("failed", "plan_gate"))
        self.assertIsNone(result["html"])

    def test_run_withholds_page_that_fails_final_checks(self):
        import sitestarter.planning_loop as loop
        original = loop.build_site
        loop.build_site = lambda facts, plan: original(facts, plan).replace(
            "</body>", "<script>alert(1)</script></body>")
        try:
            result = run_planning_loop(BRIEF, *self.agreeing_agents())
        finally:
            loop.build_site = original
        self.assertEqual((result["status"], result["stage"]), ("failed", "final_checks"))
        self.assertIsNone(result["html"])

    def test_gate_rechecks_even_after_agents_agreed(self):
        self.assertTrue(final_plan_gate(BRIEF, with_(CONTENT, contact="x@example.com"), DESIGN))
        self.assertTrue(final_plan_gate(BRIEF, CONTENT, with_(DESIGN, request_id="other")))
        self.assertTrue(final_plan_gate(BRIEF, CONTENT, with_(DESIGN, status="needs_input")))


class LoopDemoTests(unittest.TestCase):
    def run_demo(self, replies, output):
        with tempfile.TemporaryDirectory() as tmp:
            replies_file = Path(tmp) / "replies.json"
            replies_file.write_text(json.dumps(replies))
            out = Path(tmp) / output
            run = subprocess.run(
                [sys.executable, "-m", "sitestarter.loop_demo", "--brief", str(ROOT / "examples/bakery-brief.json"),
                 "--replies", str(replies_file), "--output", str(out)],
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            return run, out.exists()

    def test_recorded_example_builds(self):
        replies = json.loads((ROOT / "examples/bakery-loop-replies.json").read_text())
        run, built = self.run_demo(replies, "loop.html")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("status=ready stage=done rounds=2", run.stdout)
        self.assertTrue(built)

    def test_non_converging_replies_fail_cleanly(self):
        replies = {"content_agent": [CONTENT] + [review("content_agent", 1), CONTENT,
                                                 review("content_agent", 2), CONTENT,
                                                 review("content_agent", 3)],
                   "design_agent": [DESIGN] + [review("design_agent", r, "revise", [ask("heading")])
                                               for r in (1, 2, 3)]}
        run, built = self.run_demo(replies, "loop.html")
        self.assertEqual(run.returncode, 1)
        self.assertIn("status=failed stage=review_loop", run.stdout)
        self.assertNotIn("Traceback", run.stderr)
        self.assertFalse(built)

    def test_running_out_of_recorded_replies_fails_cleanly(self):
        run, built = self.run_demo({"content_agent": [CONTENT], "design_agent": []}, "loop.html")
        self.assertEqual(run.returncode, 1)
        self.assertNotIn("Traceback", run.stderr)
        self.assertFalse(built)


if __name__ == "__main__":
    unittest.main()
