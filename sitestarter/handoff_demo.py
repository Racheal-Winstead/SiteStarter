"""Run the design agent -> builder handoff offline.

    python3 -m sitestarter.handoff_demo --brief examples/bakery-brief.json \
        --model-response examples/bakery-design.json

There is no live model yet. --model-response is a recorded design-agent reply
that stands in for the model call; it still goes through the design agent's
validation, the builder, and the final page checks. Pass --model-response
twice to replay a rejected first reply and a retry.
"""

import argparse
import sys
from pathlib import Path

from .__main__ import read_json
from .builder import BuildError
from .handoff import plan_and_build


def main(argv=None):
    parser = argparse.ArgumentParser(description="Replay recorded design-agent replies through the handoff to the builder.")
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--model-response", required=True, type=Path, action="append",
                        help="Recorded model reply (raw text). Repeat for a retry.")
    parser.add_argument("--output", type=Path, default=Path("dist/handoff.html"))
    args = parser.parse_args(argv)

    try:
        brief = read_json(args.brief)
        replies = []
        for path in args.model_response[:2]:
            with path.open("rb") as source:
                replies.append(source.read(64 * 1024).decode("utf-8", errors="replace"))
    except (BuildError, OSError, RecursionError) as exc:
        print(f"Handoff failed: {exc}", file=sys.stderr)
        return 1

    def recorded_model(messages):
        if not replies:
            raise TimeoutError("no recorded reply left")
        return replies.pop(0)

    result = plan_and_build(brief, recorded_model)
    print(f"request_id={result['request_id']} status={result['status']} "
          f"stage={result['stage']} design_attempts={result['design_attempts']}")
    if result["status"] != "ready":
        for error in result["errors"]:
            print(f"  - {error}", file=sys.stderr)
        return 1
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as target:
            target.write(result["html"])
    except OSError as exc:
        print(f"Handoff failed: {exc}", file=sys.stderr)
        return 1
    print(f"Built {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
