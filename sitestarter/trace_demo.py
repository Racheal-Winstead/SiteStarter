"""Print the trace of one recorded case, step by step.

    python3 -m sitestarter.trace_demo --brief examples/bakery-brief.json \
        --cases examples/eval-cases.json --case instruction-text-in-brief

Each line is one event from run_planning_loop's trace: what was sent, what
came back (field fingerprints and lengths, never the user's or agent's text), the check
errors, and whether it was accepted. It then lists what the trace shows:
- brief fields that reached a plan unchanged (same fingerprint)
- replies a retry hid (rejected first, accepted second)
- revisions that left a requested field unchanged
- warnings from final validation

The replies come from the recorded cases file, not a live model.
"""

import argparse
import json
import sys
from pathlib import Path

from .__main__ import read_json
from .builder import BuildError
from .eval_loop import CaseError, load_cases, run_case

# Brief field -> content plan field written from it. Contact is left out on
# purpose: the contract requires it to be copied exactly.
CARRIED = {"about": "about_text", "purpose": "heading"}


def _line(event):
    seq = f"#{event['seq']:>2}"
    kind = event["event"]
    if kind == "agent_call":
        got = event["received"]
        if got is None:
            received = "no reply"
        elif not got["json"]:
            received = f"{got['chars']} chars, not JSON"
        else:
            fields = got.get("fields") or {}
            received = f"{got['chars']} chars, fields {sorted(fields)}"
        mark = "accepted" if event["accepted"] else "REJECTED"
        line = (f"{seq} {event['agent']} {event['kind']} round {event['round']} attempt {event['attempt']}: "
                f"{mark} | sent {event['sent']['fields']} | got {received}")
        if event.get("late"):
            line += " | LATE"
        if event["errors"]:
            line += " | errors: " + "; ".join(event["errors"])
        if "requested_fields" in event:
            line += (f" | asked to change {event['requested_fields']}, changed {event['changed_fields']}")
        return line
    if kind == "result":
        return f"{seq} result: {event['status']}/{event['stage']}"
    status = "passed" if event.get("passed") else "FAILED"
    line = f"{seq} {kind}: {status}"
    if event.get("errors"):
        line += " | " + "; ".join(event["errors"])
    if event.get("warnings"):
        line += " | warnings: " + "; ".join(f"{w['field']}: {w['code']} ({w['pattern']})"
                                           for w in event["warnings"])
    return line


def findings(trace):
    """What the trace shows that the final status alone does not."""
    notes = []
    brief = next((e for e in trace if e["event"] == "brief_check"), None)
    brief_fields = (brief or {}).get("fields") or {}
    for event in trace:
        if event["event"] != "agent_call" or not event["accepted"]:
            continue
        got = (event["received"] or {}).get("fields") or {}
        if event["agent"] == "content_agent" and event["kind"] in ("plan", "revise"):
            for source, target in CARRIED.items():
                if source in brief_fields and got.get(target) == brief_fields[source]:
                    notes.append(f"#{event['seq']}: content plan {target} is brief.{source} copied unchanged")
        if event["attempt"] > 1:
            notes.append(f"#{event['seq']}: {event['agent']} {event['kind']} passed only on retry; "
                         f"end-to-end success would not show the first rejection")
        if event.get("ignored_requests"):
            notes.append(f"#{event['seq']}: {event['agent']} revision left {event['ignored_requests']} unchanged "
                         f"even though the reviewer asked for it")
    for event in trace:
        for warning in event.get("warnings", []) if event["event"] == "final_checks" else []:
            notes.append(f"#{event['seq']}: final validation warning on {warning['field']}: "
                         f"{warning['code']} ({warning['pattern']})")
    return notes


def main(argv=None):
    parser = argparse.ArgumentParser(description="Print the trace of one recorded case.")
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--case", required=True, help="case id from the cases file")
    parser.add_argument("--json", action="store_true", help="print the raw trace as JSON")
    args = parser.parse_args(argv)
    try:
        cases = load_cases(read_json(args.cases), read_json(args.brief))
    except (CaseError, BuildError, OSError, RecursionError) as exc:
        print(f"Trace failed: {exc}", file=sys.stderr)
        return 1
    case = next((c for c in cases if c["id"] == args.case), None)
    if case is None:
        print(f"Trace failed: no case with id {args.case!r}", file=sys.stderr)
        return 1
    run = run_case(case)
    if args.json:
        print(json.dumps(run["trace"], indent=2))
        return 0
    print(f"case {case['id']} (recorded replies, not live AI)")
    for event in run["trace"]:
        print("  " + _line(event))
    notes = findings(run["trace"])
    print("What the trace shows:" if notes else "What the trace shows: nothing beyond the result line.")
    for note in notes:
        print("  - " + note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
