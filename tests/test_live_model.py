import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error

from sitestarter.handoff import plan_and_build
from sitestarter.live_model import (API_URL, LiveModelError, MAX_REPLY_BYTES, TIMEOUT_SECONDS,
                                    make_live_model, to_api_request)

ROOT = Path(__file__).resolve().parents[1]
BRIEF = json.loads((ROOT / "examples/bakery-brief.json").read_text())
PLAN = json.loads((ROOT / "examples/bakery-design.json").read_text())
FAKE_KEY = "test-key-not-real-0123456789"
MESSAGES = [{"role": "system", "content": "SYSTEM"}, {"role": "user", "content": "USER"}]


def api_reply(text):
    return json.dumps({"content": [{"type": "text", "text": text}]}).encode()


class FakeOpener:
    """Stands in for urlopen: records each request and returns or raises in turn."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return io.BytesIO(outcome)


@patch.dict(os.environ, {"ANTHROPIC_API_KEY": FAKE_KEY})
class LiveModelTests(unittest.TestCase):
    def test_system_message_moves_to_the_system_field(self):
        body = to_api_request(MESSAGES, "some-model")
        self.assertEqual(body["system"], "SYSTEM")
        self.assertEqual(body["messages"], [{"role": "user", "content": "USER"}])
        self.assertEqual(body["model"], "some-model")

    def test_request_goes_to_the_messages_api_with_a_time_limit(self):
        opener = FakeOpener(api_reply("hello"))
        self.assertEqual(make_live_model("m", opener)(MESSAGES), "hello")
        request, timeout = opener.requests[0]
        self.assertEqual(request.full_url, API_URL)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("X-api-key"), FAKE_KEY)
        self.assertEqual(timeout, TIMEOUT_SECONDS)
        self.assertNotIn(FAKE_KEY, request.data.decode())

    def test_key_is_read_at_call_time_not_kept(self):
        call = make_live_model("m", FakeOpener(api_reply("x")))
        self.assertNotIn(FAKE_KEY, repr(call.__closure__))
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            with self.assertRaisesRegex(LiveModelError, "not set"):
                call(MESSAGES)

    def test_errors_never_carry_the_key_or_the_reply_body(self):
        body = io.BytesIO(b'{"error": "SECRET_BODY_TEXT"}')
        outcomes = [urllib.error.HTTPError(API_URL, 401, "Unauthorized", {}, body),
                    urllib.error.URLError("SECRET_REASON"), TimeoutError("SECRET_TIMEOUT"),
                    b"not json SECRET_BODY_TEXT", b"x" * (MAX_REPLY_BYTES + 1)]
        call = make_live_model("m", FakeOpener(*outcomes))
        messages = []
        for _ in outcomes:
            with self.assertRaises(LiveModelError) as caught:
                call(MESSAGES)
            messages.append(str(caught.exception))
        self.assertEqual(messages[0], "provider returned HTTP 401")
        for message in messages:
            self.assertNotIn(FAKE_KEY, message)
            self.assertNotIn("SECRET", message)

    def test_only_text_blocks_are_returned(self):
        reply = json.dumps({"content": [{"type": "text", "text": "a"}, {"type": "tool_use", "id": "t"},
                                        {"type": "text", "text": "b"}]}).encode()
        self.assertEqual(make_live_model("m", FakeOpener(reply))(MESSAGES), "ab")

    def test_a_model_id_is_required(self):
        for model in (None, "", "  "):
            with self.assertRaises(ValueError):
                make_live_model(model)

    def test_live_call_feeds_the_design_agent_and_builder(self):
        plan = dict(PLAN, request_id=BRIEF["request_id"])
        opener = FakeOpener(b"not json", api_reply(json.dumps(plan)))
        result = plan_and_build(BRIEF, make_live_model("m", opener))
        self.assertEqual(result["status"], "ready", result["errors"])
        self.assertEqual(result["design_attempts"], 2)

    def test_provider_failures_use_the_design_agents_single_retry(self):
        error = urllib.error.HTTPError(API_URL, 529, "Overloaded", {}, io.BytesIO(b""))
        opener = FakeOpener(error, error)
        result = plan_and_build(BRIEF, make_live_model("m", opener))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(opener.requests), 2)
        self.assertEqual(result["errors"], ["model call failed: LiveModelError"])


if __name__ == "__main__":
    unittest.main()
