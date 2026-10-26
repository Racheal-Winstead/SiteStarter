"""Exercise actual generated HTML, adversarial inputs, and the CLI boundary."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from sitestarter.builder import BuildError, build_site
from sitestarter.design_agent import contrast_ratio

ROOT = Path(__file__).resolve().parents[1]
BRIEF = json.loads((ROOT / "examples/bakery-brief.json").read_text())
PLAN = json.loads((ROOT / "examples/bakery-design.json").read_text())


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


class BuilderTests(unittest.TestCase):
    def test_sample_has_required_sections_in_order_and_exact_facts(self):
        page = Page(build_site(BRIEF, PLAN))
        self.assertEqual([attrs["id"] for tag, attrs in page.tags if tag == "section"],
                         ["heading", "about", "contact"])
        for field in ("name", "purpose", "about", "contact"):
            self.assertIn(BRIEF[field], page.text)
        self.assertEqual(sum(tag == "h1" for tag, _ in page.tags), 1)
        self.assertIn(("html", {"lang": "en"}), page.tags)

    def test_injection_in_all_business_text_is_rendered_only_as_text(self):
        payload = '\"><script>alert(1)</script><img src=x onerror=alert(2)>& ☕'
        brief = dict(BRIEF, **{key: payload for key in ("name", "purpose", "about", "contact")})
        page = Page(build_site(brief, PLAN))
        self.assertIn(payload, page.text)
        self.assertFalse(any(tag in ("script", "img", "iframe", "object", "form") for tag, _ in page.tags))
        self.assertFalse(any(key.startswith("on") for _, attrs in page.tags for key in attrs))
        self.assertIn(("meta", {"name": "description", "content": payload}), page.tags)

    def test_no_external_requests_and_navigation_targets_exist(self):
        brief = dict(BRIEF, contact="javascript:alert(1) https://example.com")
        page = Page(build_site(brief, PLAN))
        ids = {attrs["id"] for _, attrs in page.tags if "id" in attrs}
        for _, attrs in page.tags:
            self.assertNotIn("src", attrs)
            if "href" in attrs:
                self.assertTrue(attrs["href"].startswith("#"))
                self.assertIn(attrs["href"][1:], ids)
        policies = [attrs["content"] for tag, attrs in page.tags
                    if tag == "meta" and attrs.get("http-equiv") == "Content-Security-Policy"]
        self.assertEqual(len(policies), 1)
        self.assertIn("default-src 'none'", policies[0])
        self.assertIn("form-action 'none'", policies[0])

    def test_readable_button_on_light_and_dark_accents(self):
        for accent, foreground in (("#FFFFFF", "#000000"), ("#000000", "#FFFFFF")):
            with self.subTest(accent=accent):
                plan = copy.deepcopy(PLAN)
                plan["colors"]["accent"] = accent
                html = build_site(BRIEF, plan)
                self.assertIn(f"color: {foreground}", html)
                self.assertGreaterEqual(contrast_ratio(accent, foreground), 4.5)

    def test_mobile_and_keyboard_access_are_present(self):
        html = build_site(BRIEF, PLAN)
        self.assertIn('@media (max-width: 600px)', html)
        self.assertIn('grid-template-columns: 1fr;', html)
        self.assertIn('name="viewport"', html)
        self.assertIn('Skip to content', html)
        self.assertIn(':focus-visible', html)

    def test_rejects_missing_wrong_type_blank_and_overlong_facts(self):
        for key in ("request_id", "name", "purpose", "about", "contact"):
            for value in (None, [], {}, 42, True, "", " \n", "x" * 5000, "bad\x00", "bad\ud800"):
                with self.subTest(key=key, value=repr(value)):
                    with self.assertRaises(BuildError):
                        build_site(dict(BRIEF, **{key: value}), PLAN)
            brief = dict(BRIEF)
            del brief[key]
            with self.assertRaises(BuildError):
                build_site(brief, PLAN)
        for brief in (None, [], "text"):
            with self.assertRaises(BuildError):
                build_site(brief, PLAN)

    def test_rejects_non_complete_mismatched_and_unsafe_plans(self):
        for plan in (None, [], dict(PLAN, request_id="other"), dict(PLAN, status="failed"),
                     dict(PLAN, status="needs_input"), dict(PLAN, colors=["bad"]),
                     dict(PLAN, warnings=["https://external.example"]),
                     dict(PLAN, typography={"heading_font": "Arial; color:red", "body_font": "Arial", "base_size_px": 18})):
            with self.subTest(plan=plan):
                with self.assertRaises(BuildError):
                    build_site(BRIEF, plan)

    def test_rejects_trailing_newline_in_css_color(self):
        plan = copy.deepcopy(PLAN)
        plan["colors"]["background"] += "\n"
        with self.assertRaises(BuildError):
            build_site(BRIEF, plan)

    def test_multiline_and_unicode_facts_are_preserved(self):
        brief = dict(BRIEF, about="Café & tea\nFresh bread 🍞")
        self.assertIn(brief["about"], Page(build_site(brief, PLAN)).text)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.brief = self.directory / "brief.json"
        self.plan = self.directory / "plan.json"
        self.output = self.directory / "result/index.html"
        self.brief.write_text(json.dumps(BRIEF), encoding="utf-8")
        self.plan.write_text(json.dumps(PLAN), encoding="utf-8")

    def run_build(self):
        return subprocess.run([sys.executable, "-m", "sitestarter", "--brief", str(self.brief),
                               "--plan", str(self.plan), "--output", str(self.output)],
                              cwd=ROOT, capture_output=True, text=True)

    def assert_failed_without_output(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Build failed:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(self.output.exists())

    def test_build_command_produces_utf8_page_and_reports_path(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.output), result.stdout)
        self.assertEqual(self.output.read_text(encoding="utf-8"), build_site(BRIEF, PLAN))

    def test_refuses_existing_output_without_changing_it(self):
        self.output.parent.mkdir()
        self.output.write_text("keep this", encoding="utf-8")
        result = self.run_build()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.output.read_text(), "keep this")

    def test_refuses_symlink_without_changing_target(self):
        self.output.parent.mkdir()
        self.output.symlink_to(self.brief)
        before = self.brief.read_bytes()
        result = self.run_build()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.brief.read_bytes(), before)

    def test_malformed_json_does_not_create_output(self):
        self.plan.write_text('{"oops":', encoding="utf-8")
        self.assert_failed_without_output()

    def test_invalid_utf8_does_not_create_output(self):
        self.brief.write_bytes(b'\xff')
        self.assert_failed_without_output()

    def test_invalid_brief_and_plan_do_not_create_output(self):
        self.brief.write_text('{}', encoding="utf-8")
        self.assert_failed_without_output()
        self.brief.write_text(json.dumps(BRIEF), encoding="utf-8")
        self.plan.write_text(json.dumps(dict(PLAN, request_id="other")), encoding="utf-8")
        self.assert_failed_without_output()

    def test_oversized_and_deeply_nested_input_fail_cleanly(self):
        for data in (b' ' * (64 * 1024 + 1), b'[' * 1500 + b']' * 1500):
            self.plan.write_bytes(data)
            self.assert_failed_without_output()

    def test_missing_file_fails_cleanly(self):
        self.brief.unlink()
        self.assert_failed_without_output()


if __name__ == "__main__":
    unittest.main()
