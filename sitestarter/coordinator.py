"""Coordinator's input gate only; no model calls, sessions, or execution loop.

The form submits name, purpose, about, contact, and an optional style choice.
Accepted briefs retain the Builder's existing text-based contract.
"""

import argparse
import json
from pathlib import Path
import uuid

from .brief_contract import BRIEF_LIMITS, text_error
from .builder import validate_brief

FORM_FIELDS = tuple(key for key in BRIEF_LIMITS if key != "request_id")
DEFAULT_STYLE = "calm_welcoming"
STYLE_GUIDANCE = {
    "calm_welcoming": "Soft colors, comfortable spacing, and welcoming typography. Maintain readable text and sufficient contrast.",
    "clean_professional": "Restrained colors, clear typography, and orderly spacing. Maintain readable text and sufficient contrast.",
    "bold_expressive": "Strong accent colors and prominent headings. Maintain readable text and sufficient contrast.",
}


def validate_submission(submission):
    """Return field errors without changing inputs, allocating IDs, or calling agents."""
    if not isinstance(submission, dict):
        return {"_form": "Submit the form as a JSON object."}
    errors = {}
    if set(submission) - (set(FORM_FIELDS) | {"style_preferences"}):
        errors["_form"] = "The form contains unsupported fields. Request IDs are assigned by the Coordinator."
    for key in FORM_FIELDS:
        error = text_error(submission.get(key), BRIEF_LIMITS[key])
        if error:
            errors[key] = f"This field {error}."
    style = submission.get("style_preferences", DEFAULT_STYLE)
    if not isinstance(style, str) or style not in STYLE_GUIDANCE:
        errors["style_preferences"] = "Choose Calm & welcoming, Clean & professional, or Bold & expressive."
    return errors


def prepare_brief(submission):
    """Create a validated brief. 'accepted' means input accepted, never page Ready."""
    errors = validate_submission(submission)
    if errors:
        return {"status": "needs_input", "stage": "brief", "request_id": None,
                "field_errors": errors, "brief": None}
    brief = {key: submission[key] for key in FORM_FIELDS}
    brief["request_id"] = str(uuid.uuid4())
    choice = submission.get("style_preferences", DEFAULT_STYLE)
    brief["style_preferences"] = STYLE_GUIDANCE[choice]
    # Defense against accidental drift between the form and downstream contract.
    if validate_brief(brief):
        raise RuntimeError("Coordinator and Builder brief contracts differ")
    return {"status": "accepted", "stage": "brief", "request_id": brief["request_id"],
            "field_errors": {}, "brief": brief}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate a form submission without launching agents.")
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        from .__main__ import read_json
        from .builder import BuildError
        submission = read_json(args.input)
    except (OSError, BuildError, RecursionError):
        print(json.dumps({"status": "needs_input", "stage": "brief",
                          "field_errors": {"_form": "Could not read a valid, bounded JSON submission."}}))
        return 1
    result = prepare_brief(submission)
    # Do not print submitted contact details or other business text to console logs.
    print(json.dumps({key: value for key, value in result.items() if key != "brief"}, indent=2))
    return 0 if result["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
