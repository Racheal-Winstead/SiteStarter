"""Run the content <-> design review loop offline with recorded replies.

    python3 -m sitestarter.loop_demo --brief examples/bakery-brief.json \
        --replies examples/bakery-loop-replies.json

There is no live model here. The replies file holds hand-written stand-ins
for each agent's output, played back in order. They still go through every
handoff check, the review rounds, the final plan gate, the builder, and the
final page checks.
"""

import argparse
import json
import sys
from pathlib import Path

from .__main__ import read_json
from .builder import BuildError
from .planning_loop import run_planning_loop


def recorded(replies, name):
    queue = list(replies.get(name, [])) if isinstance(replies, dict) else []

    def agent(task):
        if not queue:
            raise TimeoutError(f"no recorded reply left for {name}")
        item = queue.pop(0)
        return item if isinstance(item, str) else json.dumps(item)
    return agent


def main(argv=None):
    parser = argparse.ArgumentParser(description="Replay recorded agent replies through the review loop.")
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--replies", required=True, type=Path,
                        help='JSON with "content_agent" and "design_agent" lists of recorded replies')
    parser.add_argument("--output", type=Path, default=Path("dist/loop.html"))
    args = parser.parse_args(argv)

    try:
        brief = read_json(args.brief)
        replies = read_json(args.replies)
    except (BuildError, OSError, RecursionError) as exc:
        print(f"Loop demo failed: {exc}", file=sys.stderr)
        return 1

    result = run_planning_loop(brief, recorded(replies, "content_agent"), recorded(replies, "design_agent"))
    for call in result["calls"]:
        mark = "accepted" if call["accepted"] else "rejected"
        print(f"  round {call['round']} {call['agent']} {call['kind']} attempt {call['attempt']}: {mark}")
    print(f"request_id={result['request_id']} status={result['status']} stage={result['stage']} "
          f"rounds={result['rounds']}")
    if result["status"] != "ready":
        for error in result["errors"]:
            print(f"  - {error}", file=sys.stderr)
        return 1
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as target:
            target.write(result["html"])
    except OSError as exc:
        print(f"Loop demo failed: {exc}", file=sys.stderr)
        return 1
    print(f"Built {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
