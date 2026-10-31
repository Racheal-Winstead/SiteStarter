# Live-mode preparation

Institution-provided configuration: Anthropic, Claude Sonnet 5.5. The institution's
LiteLLM spelling is `anthropic/claude-sonnet-5-5`; our direct API adapter uses
`claude-sonnet-5-5`. Live requests use max_tokens=4096. Personal institutional
keys must not be shared; each developer configures their own Keychain item.

Recorded mode remains the default and needs no credentials:

```sh
python3 -m sitestarter.web
```

Explicit live mode (institutional credits are used when submitting a brief):

```sh
python3 -m sitestarter.web --live --model claude-sonnet-5-5 --port 4174
```

Open http://127.0.0.1:4174/. The page reports its server mode. A live submission
uses Content's plan/review/revise callback and a Design task callback based on
Sam's prompt. Both share the existing validation/review loop, then the deterministic
Builder and session-owned delivery gate. No nested agent retry loops are added.
The web preview loads credentials only on an actual live request; the recorded
server never reads Keychain. The credential is retrieved once per run and reused
in that run's memory, avoiding a prompt on every agent call or retry. Denied
retrieval ends the run without a credential retry. A new run may prompt again;
there is no need to choose Always Allow. Stop/restart the live server to end old
in-memory activity. macOS may require permission for retrieval.

Provider requests capture the key in memory via the Keychain loader; they do not
export it into the environment or send it to the browser. Explicit environment
configuration remains supported. The adapter sends requests only to the direct
Anthropic Messages endpoint. No tools, external browsing, or publishing are enabled.

The provider adapter has a 45-second network timeout and rejects truncated or
empty replies. The shared loop owns its existing single retry per step. Each
run permits at most 24 provider calls (12 task steps, each with up to 2 attempts),
and a four-minute result-acceptance deadline. These are caps, not estimates of
cost: each call has input and output costs. A network inactivity timeout is not
a hard wall-clock interruption; the store also refuses late results and reports
timeout while a callback finishes. Full process isolation and the original PRD's
task-level retry budget reconciliation remain future work.

For the first live check, use only fictional business data. Inspect generated
copy against the brief; schema checks do not prove factual correctness. Live
warnings still require explicit revision-bound review before output release.
Key validity, credits, and live model behavior are not established by mocked tests.

## Monday demonstration preparation (independent work)

1. Rehearse the recorded success case with the trace and actual HTML download.
2. Rehearse missing contact: no agents start; the interface preserves answers.
3. Rehearse instruction-like about text: review_required; output is withheld.
4. Explain one revision: who requested it, what changed, and which checks ran.
5. Contrast recorded evidence with a real live run; never present mocks as AI.
6. Keep screenshots/recorded-mode fallback ready in case network, credits, or
   Keychain access interrupts the presentation.
7. Present remaining limits honestly: sequential planners, incomplete semantic
   fact checking, two known warning-detector misses, and development-only hosting.

This branch builds on Content Agent PR #14. Sam should review shared Design and
provider changes before merging; it can be developed and mock-tested independently.
