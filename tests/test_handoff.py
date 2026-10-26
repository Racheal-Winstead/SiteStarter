"""Design agent -> builder handoff and the final page checks.

The model is a scripted fake, so these run without an API key. The brief and
plan come from the checked-in fictional bakery example.
"""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sitestarter.builder import build_site
from sitestarter.design_agent import validate_design_plan
from sitestarter.final_checks import check_final_html
from sitestarter.handoff import plan_and_build

ROOT = Path(__file__).resolve().parents[1]
BRIEF = json.loads((ROOT / "examples/bakery-brief.json").read_text())
PLAN = json.loads((ROOT / "examples/bakery-design.json").read_text())


def scripted_model(*responses):
    calls = []

    def call_model(messages):
        calls.append(messages)
        item = responses[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, str) else json.dumps(item)

    call_model.calls = calls
    return call_model


def plan_with(**changes):
    plan = copy.deepcopy(PLAN)
    plan.update(changes)
    return plan


class HandoffTests(unittest.TestCase):
    def test_accepted_plan_flows_into_a_checked_page(self):
        model = scripted_model(PLAN)
        result = plan_and_build(BRIEF, model)
        self.assertEqual(result["status"], "ready", result["errors"])
        self.assertEqual(result["stage"], "done")
        self.assertEqual(result["request_id"], BRIEF["request_id"])
        self.assertEqual(result["plan"], PLAN)
        # The colors the design agent chose are what the builder used.
        self.assertIn(PLAN["colors"]["background"], result["html"])
        self.assertIn(BRIEF["name"], result["html"])
        self.assertEqual(len(model.calls), 1)

    def test_brief_reaches_the_design_agent_as_data(self):
        model = scripted_model(PLAN)
        plan_and_build(BRIEF, model)
        user_message = model.calls[0][1]["content"]
        self.assertIn("<brief>", user_message)
        self.assertIn(BRIEF["request_id"], user_message)

    def test_bad_first_plan_is_retried_then_built(self):
        model = scripted_model(plan_with(section_order=["about", "heading", "contact"]), PLAN)
        result = plan_and_build(BRIEF, model)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["design_attempts"], 2)

    def test_rejected_plan_never_reaches_the_builder(self):
        bad = plan_with(colors={"background": "#FFFFFF", "text": "#EEEEEE", "accent": "#DDDDDD"})
        result = plan_and_build(BRIEF, scripted_model(bad, bad))
        self.assertEqual((result["status"], result["stage"]), ("failed", "design"))
        self.assertIsNone(result["html"])
        self.assertTrue(any("contrast" in e for e in result["errors"]))

    def test_plan_for_another_request_is_rejected(self):
        other = plan_with(request_id="someone-else-002")
        result = plan_and_build(BRIEF, scripted_model(other, other))
        self.assertEqual((result["status"], result["stage"]), ("failed", "design"))
        self.assertIn("request_id does not match the brief", result["errors"])
        self.assertIsNone(result["html"])

    def test_model_errors_fail_closed(self):
        result = plan_and_build(BRIEF, scripted_model(TimeoutError(), TimeoutError()))
        self.assertEqual((result["status"], result["stage"]), ("failed", "design"))
        self.assertIsNone(result["html"])

    def test_needs_input_stops_before_building(self):
        ask = {"request_id": BRIEF["request_id"], "agent_name": "design_agent",
               "status": "needs_input", "warnings": ["style preferences conflict"]}
        result = plan_and_build(BRIEF, scripted_model(ask))
        self.assertEqual((result["status"], result["stage"]), ("needs_input", "design"))
        self.assertEqual(result["errors"], ["style preferences conflict"])
        self.assertIsNone(result["html"])

    def test_missing_facts_stop_before_any_model_call(self):
        model = scripted_model(PLAN)
        brief = dict(BRIEF)
        del brief["contact"]
        result = plan_and_build(brief, model)
        self.assertEqual((result["status"], result["stage"]), ("failed", "brief"))
        self.assertEqual(model.calls, [])

    def test_non_object_brief_fails_cleanly(self):
        for brief in (None, [], "brief"):
            with self.subTest(brief=brief):
                result = plan_and_build(brief, scripted_model(PLAN))
                self.assertEqual((result["status"], result["stage"]), ("failed", "brief"))

    def test_final_check_failure_withholds_html(self):
        import sitestarter.handoff as handoff
        original = handoff.build_site
        handoff.build_site = lambda brief, plan: original(brief, plan).replace(
            "</body>", '<img src="https://tracker.example/x.gif"></body>')
        try:
            result = plan_and_build(BRIEF, scripted_model(PLAN))
        finally:
            handoff.build_site = original
        self.assertEqual((result["status"], result["stage"]), ("failed", "final_checks"))
        self.assertIsNone(result["html"])


DEEP_LIST = "[" * 1500 + "]" * 1500


def deep_object(levels=1500):
    plan = copy.deepcopy(PLAN)
    node = plan["warnings"] = [{}]
    node = node[0]
    for _ in range(levels):
        node["a"] = {}
        node = node["a"]
    return plan


def deep_object_text(levels=1500):
    # Built by hand: json.dumps itself overflows on deep input in older Pythons.
    head = json.dumps(PLAN)[:-1].replace('"warnings": []', '"warnings": [' + '{"a": ' * levels + "{}" + "}" * levels + "]")
    return head + "}"


class DeepNestingTests(unittest.TestCase):
    """Regression: deeply nested model output must be rejected, never raise RecursionError."""

    def test_deep_list_then_good_reply_is_built(self):
        model = scripted_model(DEEP_LIST, PLAN)
        result = plan_and_build(BRIEF, model)
        self.assertEqual(result["status"], "ready", result["errors"])
        self.assertEqual(result["design_attempts"], 2)

    def test_deep_list_twice_fails_cleanly_without_html(self):
        result = plan_and_build(BRIEF, scripted_model(DEEP_LIST, DEEP_LIST))
        self.assertEqual((result["status"], result["stage"]), ("failed", "design"))
        self.assertEqual(result["design_attempts"], 2)
        self.assertIsNone(result["html"])
        self.assertEqual(len(result["errors"]), 1)

    def test_validator_rejects_deep_object_without_recursing(self):
        # Parsed objects can be deep on newer Pythons, so the validator must check depth itself.
        self.assertEqual(validate_design_plan(deep_object(), BRIEF), ["plan nests deeper than 8 levels"])
        # plan -> warnings -> object is 3 levels, so 5 more is exactly the limit and 6 is one past it.
        self.assertEqual(validate_design_plan(deep_object(levels=5), BRIEF), [])
        self.assertEqual(validate_design_plan(deep_object(levels=6), BRIEF), ["plan nests deeper than 8 levels"])
        self.assertEqual(validate_design_plan(PLAN, BRIEF), [])

    def test_deep_object_reply_twice_fails_cleanly(self):
        deep = deep_object_text()
        result = plan_and_build(BRIEF, scripted_model(deep, deep))
        self.assertEqual((result["status"], result["stage"]), ("failed", "design"))
        self.assertIn("plan nests deeper than 8 levels", result["errors"])
        self.assertIsNone(result["html"])

    def test_deep_object_then_good_reply_is_built(self):
        model = scripted_model(deep_object_text(), PLAN)
        result = plan_and_build(BRIEF, model)
        self.assertEqual(result["status"], "ready", result["errors"])
        self.assertIn("plan nests deeper than 8 levels", model.calls[1][1]["content"])

    def test_cli_reports_deep_reply_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            deep_file = Path(tmp) / "deep.json"
            deep_file.write_text(DEEP_LIST)
            output = Path(tmp) / "out.html"
            run = subprocess.run(
                [sys.executable, "-m", "sitestarter.handoff_demo", "--brief", str(ROOT / "examples/bakery-brief.json"),
                 "--model-response", str(deep_file), "--model-response", str(deep_file), "--output", str(output)],
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 1)
            self.assertNotIn("Traceback", run.stderr)
            self.assertIn("status=failed stage=design design_attempts=2", run.stdout)
            self.assertFalse(output.exists())

    def test_cli_recovers_after_deep_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            deep_file = Path(tmp) / "deep.json"
            deep_file.write_text(DEEP_LIST)
            output = Path(tmp) / "out.html"
            run = subprocess.run(
                [sys.executable, "-m", "sitestarter.handoff_demo", "--brief", str(ROOT / "examples/bakery-brief.json"),
                 "--model-response", str(deep_file), "--model-response", str(ROOT / "examples/bakery-design.json"),
                 "--output", str(output)],
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertNotIn("Traceback", run.stderr)
            self.assertTrue(output.exists())

    def test_builder_rejects_deep_plan_instead_of_crashing(self):
        from sitestarter.builder import BuildError
        with self.assertRaises(BuildError):
            build_site(BRIEF, deep_object())


class FinalCheckTests(unittest.TestCase):
    def setUp(self):
        self.html = build_site(BRIEF, PLAN)

    def test_built_sample_passes(self):
        self.assertEqual(check_final_html(self.html, BRIEF), [])

    def test_injected_brief_text_still_passes_as_text(self):
        payload = '"><script>alert(1)</script><img src=x onerror=alert(2)>'
        brief = dict(BRIEF, name=payload, contact=payload)
        self.assertEqual(check_final_html(build_site(brief, PLAN), brief), [])

    def test_each_unsafe_change_is_caught(self):
        cases = {
            "script": ("</body>", "<script>alert(1)</script></body>"),
            "external image": ("</body>", '<img src="https://example.com/a.png"></body>'),
            "event handler": ('<main id="main"', '<main onclick="x()" id="main"'),
            "outside link": ('href="#contact">Get', 'href="https://example.com">Get'),
            "css url": ("* {", "body { background: url(https://example.com/a.png); } * {"),
            "css import": ("<style>", "<style>@import 'https://example.com/a.css';"),
            "inline style url": ('<footer>', '<footer style="background:url(x)">'),
            "meta refresh": ("<title>", '<meta http-equiv="refresh" content="0;url=https://example.com"><title>'),
            "iframe": ("</body>", '<iframe srcdoc="hi"></iframe></body>'),
            "form": ("</body>", "<form><input name=q></form></body>"),
        }
        for label, (old, new) in cases.items():
            with self.subTest(label=label):
                self.assertIn(old, self.html)
                self.assertTrue(check_final_html(self.html.replace(old, new, 1), BRIEF))

    def test_missing_csp_is_caught(self):
        html = self.html.replace("Content-Security-Policy", "X-Removed")
        self.assertIn("page is missing the default-src 'none' content security policy",
                      check_final_html(html, BRIEF))

    def test_missing_or_reordered_sections_are_caught(self):
        html = self.html.replace('id="about"', 'id="story"')
        self.assertTrue(any(e.startswith("sections must be") for e in check_final_html(html, BRIEF)))

    def test_changed_contact_is_caught(self):
        html = self.html.replace(BRIEF["contact"], "sales@example.com")
        self.assertIn("page does not show the approved contact exactly as supplied",
                      check_final_html(html, BRIEF))

    def test_bad_inputs_never_raise(self):
        for html in (None, "", "   ", 42, "<", "<<<>>>", "<html><body>" * 2000):
            with self.subTest(html=str(html)[:20]):
                self.assertIsInstance(check_final_html(html, BRIEF), list)
                self.assertTrue(check_final_html(html, BRIEF))

    def test_oversized_page_is_rejected(self):
        self.assertEqual(check_final_html("a" * (256 * 1024 + 1), BRIEF), ["page is larger than 256 KiB"])


if __name__ == "__main__":
    unittest.main()
