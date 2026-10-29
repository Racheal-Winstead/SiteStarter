"""Live model call for the design agent, using the Anthropic Messages API.

    call = make_live_model("claude-haiku-5-5")
    result = plan_and_build(brief, call)

The API key is read from the ANTHROPIC_API_KEY environment variable when the
call is made. It is never taken as an argument, stored on the returned
function, written to a file, or put in an error message. Errors carry only the
HTTP status or the exception type, never the provider's response body.

Standard library only. Each call has a 45-second limit, the PRD's per-attempt
limit; the design agent already counts a failed call against its one retry.
"""

import json
import os
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
TIMEOUT_SECONDS = 45
MAX_TOKENS = 2000
MAX_REPLY_BYTES = 256 * 1024


class LiveModelError(RuntimeError):
    """A live call failed. The message never includes the key or the reply body."""


def to_api_request(messages, model):
    """Turn the agents' [{role, content}] list into a Messages API body.

    A "system" message becomes the top-level system field; the rest stay in order.
    """
    system = [m["content"] for m in messages if m["role"] == "system"]
    turns = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
    body = {"model": model, "max_tokens": MAX_TOKENS, "messages": turns}
    if system:
        body["system"] = "\n\n".join(system)
    return body


def reply_text(payload):
    """Join the text blocks of a Messages API reply."""
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
        raise LiveModelError("reply had no content list")
    return "".join(block.get("text", "") for block in payload["content"]
                   if isinstance(block, dict) and block.get("type") == "text")


def make_live_model(model, opener=urllib.request.urlopen):
    """Return call_model(messages) -> raw reply text for one model id.

    `opener` is replaceable so tests run without a network or a key.
    """
    if not isinstance(model, str) or not model.strip():
        raise ValueError("a model id is required")

    def call_model(messages):
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            raise LiveModelError("ANTHROPIC_API_KEY is not set")
        request = urllib.request.Request(
            API_URL,
            data=json.dumps(to_api_request(messages, model)).encode("utf-8"),
            headers={"x-api-key": key, "anthropic-version": API_VERSION,
                     "content-type": "application/json"},
            method="POST",
        )
        try:
            with opener(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read(MAX_REPLY_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise LiveModelError(f"provider returned HTTP {exc.code}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise LiveModelError(f"request failed: {type(exc).__name__}") from None
        if len(raw) > MAX_REPLY_BYTES:
            raise LiveModelError("reply was too large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise LiveModelError("reply was not JSON") from None
        return reply_text(payload)

    return call_model
