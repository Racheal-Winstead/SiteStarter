"""Score the final-validation warning patterns on a fixed set of texts.

    python -m sitestarter.warning_eval --cases examples/warning-cases.json [--json]

Each text is checked as the "about" field of a page. A should_warn text that
gets a warning is a catch; a should_not_warn text that gets one is a false
alarm. The case file's baseline is the bar: fewer catches than min_caught, or
more false alarms than max_false_alarms, exits 1. A should_warn case marked
known_miss is expected to slip through today; if it starts being caught, the
run says so, so the baseline can be raised.

Output names cases by id only. The texts stay in the case file.
"""

import argparse
import json
import sys

from .final_checks import find_instruction_like_text


class WarningCaseError(ValueError):
    pass


def load_cases(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise WarningCaseError(f"could not read {path}: {exc}") from None
    if not isinstance(data, dict):
        raise WarningCaseError("case file must be a JSON object")
    baseline = data.get("baseline")
    if (not isinstance(baseline, dict)
            or not all(isinstance(baseline.get(k), int) and not isinstance(baseline.get(k), bool)
                       and baseline.get(k) >= 0 for k in ("min_caught", "max_false_alarms"))):
        raise WarningCaseError("baseline needs non-negative integers min_caught and max_false_alarms")
    seen = set()
    for group in ("should_warn", "should_not_warn"):
        cases = data.get(group)
        if not isinstance(cases, list) or not cases:
            raise WarningCaseError(f"{group} must be a non-empty list")
        for i, case in enumerate(cases):
            where = f"{group}[{i}]"
            if not isinstance(case, dict):
                raise WarningCaseError(f"{where} must be an object")
            cid, text = case.get("id"), case.get("text")
            if not isinstance(cid, str) or not cid.strip():
                raise WarningCaseError(f"{where}: id must be a non-empty string")
            if cid in seen:
                raise WarningCaseError(f"{where}: duplicate id {cid!r}")
            seen.add(cid)
            if not isinstance(text, str) or not text.strip():
                raise WarningCaseError(f"{where} ({cid}): text must be a non-empty string")
            if "known_miss" in case and (group != "should_warn" or not isinstance(case["known_miss"], bool)):
                raise WarningCaseError(f"{where} ({cid}): known_miss is a true/false flag on should_warn cases")
    if baseline["min_caught"] > len(data["should_warn"]):
        raise WarningCaseError("baseline min_caught is more than the number of should_warn cases")
    return data


def _warned(text):
    warnings = find_instruction_like_text({"about": text})
    return warnings[0]["pattern"] if warnings else None


def score(data):
    caught, missed, newly_caught, false_alarms = [], [], [], []
    for case in data["should_warn"]:
        pattern = _warned(case["text"])
        if pattern:
            caught.append({"id": case["id"], "pattern": pattern})
            if case.get("known_miss"):
                newly_caught.append(case["id"])
        else:
            missed.append({"id": case["id"], "known_miss": bool(case.get("known_miss"))})
    for case in data["should_not_warn"]:
        pattern = _warned(case["text"])
        if pattern:
            false_alarms.append({"id": case["id"], "pattern": pattern})
    baseline = data["baseline"]
    failures = []
    if len(caught) < baseline["min_caught"]:
        failures.append(f"caught {len(caught)}, baseline needs at least {baseline['min_caught']}")
    if len(false_alarms) > baseline["max_false_alarms"]:
        failures.append(f"{len(false_alarms)} false alarms, baseline allows {baseline['max_false_alarms']}")
    return {"should_warn": len(data["should_warn"]), "should_not_warn": len(data["should_not_warn"]),
            "caught": caught, "missed": missed, "newly_caught": newly_caught,
            "false_alarms": false_alarms, "baseline": baseline, "failures": failures,
            "passed": not failures}


def _report(result):
    lines = [f"Caught {len(result['caught'])} of {result['should_warn']} instruction-like texts.",
             f"False alarms: {len(result['false_alarms'])} of {result['should_not_warn']} ordinary texts."]
    for miss in result["missed"]:
        note = " (known miss)" if miss["known_miss"] else ""
        lines.append(f"  missed: {miss['id']}{note}")
    for alarm in result["false_alarms"]:
        lines.append(f"  false alarm: {alarm['id']} ({alarm['pattern']})")
    for cid in result["newly_caught"]:
        lines.append(f"  now caught, was a known miss: {cid}. Consider raising the baseline.")
    b = result["baseline"]
    lines.append(f"Baseline: at least {b['min_caught']} caught, at most {b['max_false_alarms']} false alarms.")
    if result["passed"]:
        lines.append("Warning eval passed. These patterns are a flag for a person, not a security boundary.")
    else:
        lines.extend(f"Warning eval failed: {f}" for f in result["failures"])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Score the final-validation warning patterns.")
    parser.add_argument("--cases", required=True, help="path to the warning case file")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    try:
        data = load_cases(args.cases)
    except WarningCaseError as exc:
        print(f"Warning eval failed: {exc}", file=sys.stderr)
        return 2
    result = score(data)
    print(json.dumps(result, indent=2) if args.json else _report(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
