"""Offline build command: python3 -m sitestarter --help."""

import argparse
import json
import sys
from pathlib import Path

from .builder import BuildError, build_site

MAX_INPUT_BYTES = 64 * 1024


def read_json(path):
    # Limit the actual read, including for special files or files growing after stat.
    with path.open("rb") as source:
        data = source.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise BuildError(f"{path}: input exceeds 64 KiB")
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError) as exc:
        raise BuildError(f"{path}: expected valid UTF-8 JSON") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build an offline SiteStarter HTML draft from supplied facts and a design plan.")
    parser.add_argument("--brief", required=True, type=Path, help="JSON with request_id, name, purpose, about, contact")
    parser.add_argument("--plan", required=True, type=Path, help="Complete design-plan JSON matching the brief")
    parser.add_argument("--output", type=Path, default=Path("dist/index.html"), help="New output file (default: dist/index.html)")
    args = parser.parse_args(argv)
    try:
        # Validate everything before creating the output directory or file.
        page = build_site(read_json(args.brief), read_json(args.plan))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also refuses symlinks and accidental input overwrites.
        with args.output.open("x", encoding="utf-8") as target:
            target.write(page)
    except (BuildError, OSError, RecursionError) as exc:
        message = "input nesting is too deep" if isinstance(exc, RecursionError) else str(exc)
        print(f"Build failed: {message}", file=sys.stderr)
        return 1
    print(f"Built {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
