"""Design agent -> builder handoff.

Runs the design agent on a brief, passes its accepted plan to the builder,
then runs the final page checks. This is the part of the pipeline Sam owns
(design agent, builder, final checks). It is not the Coordinator: it does not
run the Content Agent, enforce deadlines, or keep session state. The
Coordinator can call plan_and_build once the content plan is accepted.

Nothing reaches the builder unless the design agent's plan was accepted, and
nothing is returned as ready unless the final checks pass on the built page.
"""

from .builder import BuildError, build_site, validate_brief
from .design_agent import run_design_agent
from .final_checks import check_final_html


def _result(brief, status, stage, errors, plan=None, html=None, design_attempts=0):
    request_id = brief.get("request_id") if isinstance(brief, dict) else None
    return {
        "request_id": request_id,
        "status": status,          # ready | needs_input | failed
        "stage": stage,            # brief | design | build | final_checks | done
        "errors": list(errors),
        "plan": plan,
        "html": html,
        "design_attempts": design_attempts,
    }


def plan_and_build(brief, call_model):
    """Plan the design for one brief, build the page, and check it.

    call_model(messages) returns the model's raw text; tests pass a scripted
    fake, so no API key is needed. Returns a dict that never carries HTML
    unless status is "ready".
    """
    # Check the facts first so a bad brief never costs a model call.
    errors = validate_brief(brief)
    if errors:
        return _result(brief, "failed", "brief", errors)

    design = run_design_agent(brief, call_model)
    attempts = design["attempts"]
    if design["status"] == "needs_input":
        return _result(brief, "needs_input", "design", design["plan"].get("warnings", []),
                       plan=design["plan"], design_attempts=attempts)
    if design["status"] != "accepted":
        return _result(brief, "failed", "design", design["errors"], design_attempts=attempts)

    plan = design["plan"]
    try:
        html = build_site(brief, plan)
    except BuildError as exc:
        return _result(brief, "failed", "build", [str(exc)], plan=plan, design_attempts=attempts)

    errors = check_final_html(html, brief)
    if errors:
        return _result(brief, "failed", "final_checks", errors, plan=plan, design_attempts=attempts)

    return _result(brief, "ready", "done", [], plan=plan, html=html, design_attempts=attempts)
