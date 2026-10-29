"""Scripted response templates for wiring QA, not live agents or model-quality evals."""
import copy
import json

from .planning_loop import run_planning_loop

DESIGN = {
    "agent_name": "design_agent", "status": "complete",
    "colors": {"background": "#FFF8EE", "text": "#3B2412", "accent": "#8B5A2B"},
    "typography": {"heading_font": "Georgia", "body_font": "system-ui", "base_size_px": 18},
    "section_order": ["heading", "about", "contact"],
    "spacing": {"section_gap_px": 48, "max_width_px": 1000},
    "responsive_rules": {"breakpoint_px": 600, "mobile_layout": "single_column"}, "warnings": [],
}


def run_recorded(brief, emit):
    """Replay a fixed review script, substituting approved facts and request ID.

    The scripted revision switches the heading from the supplied name to the
    supplied purpose. No business facts are synthesized. Styles are fixed to
    the recorded fixture, not evidence of the model following preferences.
    """
    def content(task):
        emit("Content response template: " + task["kind"])
        if task["kind"] == "review":
            value = {"request_id": brief["request_id"], "agent_name": "content_agent",
                     "round": task["round"], "verdict": "agree", "requests": []}
        else:
            value = {"request_id": brief["request_id"], "agent_name": "content_agent",
                     "status": "complete", "heading": (brief["purpose"] if task["kind"] == "revise" else brief["name"])[:80],
                     "about_text": brief["about"], "contact": brief["contact"],
                     "missing_information": [], "warnings": []}
        return json.dumps(value)

    def design(task):
        emit("Design response template: " + task["kind"])
        if task["kind"] == "plan":
            value = copy.deepcopy(DESIGN)
            value["request_id"] = brief["request_id"]
        else:
            revise = task["round"] == 1
            value = {"request_id": brief["request_id"], "agent_name": "design_agent",
                     "round": task["round"], "verdict": "revise" if revise else "agree",
                     "requests": [{"target_field": "heading", "reason": "Use the supplied visitor goal as the heading."}] if revise else []}
        return json.dumps(value)

    return run_planning_loop(brief, content, design)
