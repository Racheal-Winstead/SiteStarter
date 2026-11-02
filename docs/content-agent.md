# Content Agent: model-ready callback

`sitestarter/content_agent.py` defines the Content Agent's system instructions
and `make_content_agent(call_model)`. It supports the existing planning loop's
three task kinds: `plan`, `review`, and `revise`.

```python
from sitestarter.content_agent import make_content_agent
from sitestarter.planning_loop import run_planning_loop

content_agent = make_content_agent(call_model)
result = run_planning_loop(approved_brief, content_agent, design_agent)
```

`call_model(messages)` is an injected provider adapter that must return raw text.
The callback makes one call per task, does not modify the response, and lets
provider failures propagate. The planning loop owns validation and retries;
do not wrap this callback in `run_design_agent` or another retry loop.

The prompt requires brief-grounded copy and exact preservation of contact.
Missing essential facts should produce `needs_input` and questions rather than
invented details. Reviews may request only colors, typography, and spacing.
Revisions return the full content plan and receive the existing plan, partner's
requests, and validation errors when retrying. Shared plan/review contracts and
Sam's Design Agent are unchanged.

## What is tested

`python3 -m unittest discover -s tests -v` checks task packaging, separation of
untrusted payload from system instructions, accepted plans reaching the real
Builder, contact/ID rejection, clarification, provider errors, invalid-review
rejection, single-owner retries, and a full two-round revision run.

These tests use scripted model replies. They prove integration and checks, not
that a real model follows the prompt or never invents facts. The current shared
schema validator does not semantically verify every business claim. Live factual
grounding and prompt-injection evaluation remain required before trusting output.

Sam's existing `make_live_model` adapter in `live_model.py` accepts this message
format; a mocked HTTP integration test verifies the complete Content → provider
adapter → planning loop path, including the adapter's 45-second timeout argument.
It does not establish a hard overall execution deadline or real model quality.

No real credentials are loaded, no network requests are made by these tests, and
the web preview remains in its explicitly labeled recorded mode. Selecting an
institution-approved model, connecting Keychain retrieval to the adapter (which
currently reads an environment variable), reviewing cost/timeout behavior, and
enabling live-mode integration remain next work. No shared contract was changed.
