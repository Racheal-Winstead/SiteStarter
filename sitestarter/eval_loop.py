"""Score the content <-> design review loop on a set of recorded cases.

    python3 -m sitestarter.eval_loop --brief examples/bakery-brief.json \
        --cases examples/eval-cases.json

It reports three numbers, one for each multi-agent eval dimension:

- End-to-end success: did each case end the way it should? A case expected to
  be ready must return a page. A case expected to fail must stop at the
  expected stage and return no page.
- Per-agent contribution: for each agent, how often its first reply passed
  its handoff check, how often a retry recovered, and how many runs stopped at
  one of its steps when they should not have.
- Handoff success: the share of replies accepted at each handoff (agent and
  step), plus how often the final plan gate and final page checks passed when
  a run reached them.

The cases are hand-written recorded replies, not live AI. These numbers show
whether the checks and the control flow behave as designed. They say nothing
yet about how often a real model gets things right. That needs live runs.
"""

import argparse
import copy
import json
import sys
from pathlib import Path

from .__main__ import read_json
from .builder import BuildError
from .planning_loop import CONTENT_AGENT, DESIGN_AGENT, run_planning_loop

AGENTS = (CONTENT_AGENT, DESIGN_AGENT)
ERRORS = {"TimeoutError": TimeoutError, "ConnectionError": ConnectionError}
STEP_KEYS = {"plan", "review", "raw", "error"}
GATE_REACHED = {"plan_gate", "build", "final_checks", "done"}
FINAL_CHECKS_REACHED = {"final_checks", "done"}


class CaseError(ValueError):
    """The cases file itself is malformed."""


def _expand_step(step, agent_name, base_plan, request_id, where):
    """Turn one compact recorded step into what the agent returns (or raises)."""
    if not isinstance(step, dict) or len(set(step) & STEP_KEYS) != 1:
        raise CaseError(f"{where}: each step needs exactly one of {sorted(STEP_KEYS)}")
    if "raw" in step:
        if not isinstance(step["raw"], str):
            raise CaseError(f"{where}: raw must be text")
        return step["raw"]
    if "error" in step:
        if step["error"] not in ERRORS:
            raise CaseError(f"{where}: error must be one of {sorted(ERRORS)}")
        return ERRORS[step["error"]]("recorded model error")
    if "plan" in step:
        if not isinstance(step["plan"], dict):
            raise CaseError(f"{where}: plan changes must be an object")
        plan = copy.deepcopy(base_plan)
        plan.update(copy.deepcopy(step["plan"]))
        return plan
    review = {"request_id": request_id, "agent_name": agent_name, "round": step.get("round"),
              "verdict": step["review"], "requests": copy.deepcopy(step.get("requests", []))}
    review.update(copy.deepcopy(step.get("changes", {})))
    return review


def _recorded(replies):
    queue = list(replies)

    def agent(task):
        if not queue:
            raise TimeoutError("no recorded reply left")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, str) else json.dumps(item)
    return agent


def load_cases(data, brief):
    """Check the cases file shape and expand each case into recorded agents."""
    if not isinstance(brief, dict):
        raise CaseError("brief must be a JSON object")
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list) or not data["cases"]:
        raise CaseError("cases file needs a non-empty cases list")
    base = data.get("base")
    if not isinstance(base, dict) or not all(isinstance(base.get(k), dict)
                                             for k in ("content_plan", "design_plan")):
        raise CaseError("cases file needs base.content_plan and base.design_plan objects")
    request_id = brief.get("request_id")
    bases = {CONTENT_AGENT: base["content_plan"], DESIGN_AGENT: base["design_plan"]}
    cases, seen = [], set()
    for index, case in enumerate(data["cases"], 1):
        where = f"case {index}"
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"]:
            raise CaseError(f"{where}: needs a text id")
        where = f"case {case['id']}"
        if case["id"] in seen:
            raise CaseError(f"{where}: duplicate id")
        seen.add(case["id"])
        expect = case.get("expect")
        if not isinstance(expect, dict) or not all(isinstance(expect.get(k), str)
                                                   for k in ("status", "stage")):
            raise CaseError(f"{where}: expect needs status and stage text")
        changes = case.get("brief_changes", {})
        if not isinstance(changes, dict):
            raise CaseError(f"{where}: brief_changes must be an object")
        replies = {}
        for name in AGENTS:
            steps = case.get(name, [])
            if not isinstance(steps, list):
                raise CaseError(f"{where}: {name} must be a list of steps")
            replies[name] = [_expand_step(step, name, bases[name], request_id, f"{where} {name} step {n}")
                             for n, step in enumerate(steps, 1)]
        cases.append({"id": case["id"], "description": case.get("description", ""),
                      "brief": dict(brief, **changes), "replies": replies,
                      "expect": {"status": expect["status"], "stage": expect["stage"]}})
    return cases


def run_case(case):
    result = run_planning_loop(case["brief"], _recorded(case["replies"][CONTENT_AGENT]),
                               _recorded(case["replies"][DESIGN_AGENT]))
    expect = case["expect"]
    has_page = result["html"] is not None
    matched = (result["status"] == expect["status"] and result["stage"] == expect["stage"]
               and has_page == (expect["status"] == "ready"))
    return {"id": case["id"], "expect": expect, "status": result["status"], "stage": result["stage"],
            "has_page": has_page, "matched": matched, "errors": result["errors"], "calls": result["calls"]}


def score(runs):
    """Aggregate per-case runs into the three dimensions. Counts, not just rates."""
    ready = [r for r in runs if r["expect"]["status"] == "ready"]
    failing = [r for r in runs if r["expect"]["status"] != "ready"]
    agents = {name: {"first_replies": 0, "first_accepted": 0, "retries": 0, "retries_accepted": 0,
                     "stopped_runs": 0, "unexpected_stops": 0} for name in AGENTS}
    handoffs = {}
    gate = {"reached": 0, "passed": 0}
    final_checks = {"reached": 0, "passed": 0}
    for run in runs:
        for call in run["calls"]:
            stats = agents[call["agent"]]
            if call["attempt"] == 1:
                stats["first_replies"] += 1
                stats["first_accepted"] += call["accepted"]
            else:
                stats["retries"] += 1
                stats["retries_accepted"] += call["accepted"]
            step = handoffs.setdefault(f"{call['agent']}:{call['kind']}", {"accepted": 0, "replies": 0})
            step["accepted"] += call["accepted"]
            step["replies"] += 1
        owner = run["stage"].split(":")[0]
        if owner in agents:
            agents[owner]["stopped_runs"] += 1
            agents[owner]["unexpected_stops"] += not run["matched"]
        if run["stage"] in GATE_REACHED:
            gate["reached"] += 1
            gate["passed"] += run["stage"] != "plan_gate"
        if run["stage"] in FINAL_CHECKS_REACHED:
            final_checks["reached"] += 1
            final_checks["passed"] += run["stage"] == "done"
    return {
        "end_to_end": {"matched": sum(r["matched"] for r in runs), "cases": len(runs),
                       "ready_built": sum(r["matched"] for r in ready), "ready_cases": len(ready),
                       "failures_stopped_safely": sum(r["matched"] for r in failing),
                       "failure_cases": len(failing)},
        "per_agent": agents,
        "handoffs": dict(sorted(handoffs.items())),
        "plan_gate": gate,
        "final_checks": final_checks,
    }


def _rate(part, whole):
    return f"{part}/{whole}" + (f" ({round(100 * part / whole)}%)" if whole else "")


def report(runs, scores):
    lines = []
    for run in runs:
        got = f"{run['status']}/{run['stage']}"
        want = f"{run['expect']['status']}/{run['expect']['stage']}"
        lines.append(f"  {'ok  ' if run['matched'] else 'MISS'} {run['id']}: {got}"
                     + ("" if run["matched"] else f" (expected {want})"))
    e2e = scores["end_to_end"]
    lines += ["", f"End-to-end success: {_rate(e2e['matched'], e2e['cases'])} cases ended as expected",
              f"  ready cases built a page: {_rate(e2e['ready_built'], e2e['ready_cases'])}",
              f"  failure cases stopped at the expected stage with no page: "
              f"{_rate(e2e['failures_stopped_safely'], e2e['failure_cases'])}",
              "", "Per-agent contribution:"]
    for name, s in scores["per_agent"].items():
        lines.append(f"  {name}: first reply accepted {_rate(s['first_accepted'], s['first_replies'])}, "
                     f"retry recovered {_rate(s['retries_accepted'], s['retries'])}, "
                     f"runs stopped at its step {s['stopped_runs']} (unexpected {s['unexpected_stops']})")
    lines += ["", "Handoff success (replies accepted at each handoff):"]
    for key, s in scores["handoffs"].items():
        lines.append(f"  {key}: {_rate(s['accepted'], s['replies'])}")
    lines.append(f"  final plan gate passed when reached: "
                 f"{_rate(scores['plan_gate']['passed'], scores['plan_gate']['reached'])}")
    lines.append(f"  final page checks passed when reached: "
                 f"{_rate(scores['final_checks']['passed'], scores['final_checks']['reached'])}")
    lines += ["", "Recorded replies only, not live AI: these numbers test the checks and control flow, "
              "not model quality."]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Score the review loop on recorded cases.")
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--json", action="store_true", help="print the scores as JSON")
    args = parser.parse_args(argv)
    try:
        cases = load_cases(read_json(args.cases), read_json(args.brief))
    except (CaseError, BuildError, OSError, RecursionError) as exc:
        print(f"Eval failed: {exc}", file=sys.stderr)
        return 1
    runs = [run_case(case) for case in cases]
    scores = score(runs)
    if args.json:
        print(json.dumps({"cases": [{k: r[k] for k in ("id", "status", "stage", "matched")} for r in runs],
                          "scores": scores}, indent=2))
    else:
        print(report(runs, scores))
    return 0 if all(r["matched"] for r in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
