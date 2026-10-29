"""Content agent <-> design agent review loop, then the final plan gate.

Flow (all checks are plain code; agents only return JSON text):

1. Both agents write a first plan from the same brief. Each plan is checked
   at its handoff (schema, request_id, contact preserved) before anyone else
   sees it.
2. Review rounds. The design agent reviews the content plan and the content
   agent reviews the design plan. Each review is checked at its handoff. A
   review either agrees or asks for specific changes to specific fields.
3. If both agree, go to the final plan gate. If either asks for changes, that
   agent's partner revises its plan, the revised plan is checked again, and
   the next round starts. At most MAX_REVIEW_ROUNDS rounds (two revision
   cycles). If they still disagree, the run stops as failed and nothing is
   built.
4. Final plan gate: both plans are re-checked together. An agent saying
   "agree" never skips a check; the gate re-runs every limit itself.
5. The builder makes the page and the final page checks run.

Each agent step gets two attempts (the first plus one retry with the errors).
A model error, invalid JSON, or a failed check uses an attempt. A needs_input
plan stops the run so the user can be asked. A deadline caps the whole run: it
is checked before and right after every agent call, and again before the plan
gate, before building, and before returning a page. A reply that arrives after
the deadline is discarded.

Limitation: agent calls are plain synchronous functions. If one blocks, this
code cannot interrupt it; it only refuses the late reply once the call returns.
A live provider needs its own request timeout (for example the HTTP client's
timeout set to the 45-second per-attempt limit) so a stuck call ends.

Scope: this module is the loop and its checks. The Content Agent and the
Coordinator belong to Racheal; here the content agent is any function that
returns text, so tests and the demo use recorded replies, not a live model.
Agents run one after another in this code; running the first two plans at
the same time is Coordinator work.
"""

import builtins
import hashlib
import json
import re
import time

from .builder import BuildError, build_site, validate_brief
from .design_agent import MAX_DEPTH, _nesting_depth, validate_design_plan
from .final_checks import check_final_html, find_instruction_like_text

CONTENT_AGENT = "content_agent"
DESIGN_AGENT = "design_agent"
MAX_ATTEMPTS = 2
MAX_REVIEW_ROUNDS = 3
DEADLINE_SECONDS = 240
HEADING_MAX = 80
ABOUT_MAX = 4000
REASON_MAX = 300
MAX_REQUESTS = 5

CONTENT_FIELDS = {"request_id", "agent_name", "status", "heading", "about_text",
                  "contact", "missing_information", "warnings"}
REVIEW_FIELDS = {"request_id", "agent_name", "round", "verdict", "requests"}
# What each reviewer may ask its partner to change.
REVIEWABLE = {
    DESIGN_AGENT: {"heading", "about_text"},          # design reviews content
    CONTENT_AGENT: {"colors", "typography", "spacing"},  # content reviews design
}


class _Stop(Exception):
    def __init__(self, status, stage, errors):
        super().__init__(stage)
        self.status, self.stage, self.errors = status, stage, list(errors)


def _text(value, limit):
    return isinstance(value, str) and value.strip() != "" and len(value) <= limit


def _string_list(value):
    return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)


def validate_content_plan(plan, brief):
    """Handoff check for a content plan. Returns a list of errors."""
    if not isinstance(plan, dict):
        return ["content plan must be a JSON object"]
    if _nesting_depth(plan, MAX_DEPTH) > MAX_DEPTH:
        return [f"content plan nests deeper than {MAX_DEPTH} levels"]
    errors = []
    extra = sorted(set(plan) - CONTENT_FIELDS)
    if extra:
        errors.append("content plan has unexpected fields: " + ", ".join(extra))
    if plan.get("request_id") != brief.get("request_id"):
        errors.append("request_id does not match the brief")
    if plan.get("agent_name") != CONTENT_AGENT:
        errors.append(f'agent_name must be "{CONTENT_AGENT}"')
    status = plan.get("status")
    if status not in ("complete", "needs_input", "failed"):
        errors.append("status must be complete, needs_input, or failed")
    missing = plan.get("missing_information", [])
    if not _string_list(missing):
        errors.append("missing_information must be a list of non-empty strings")
    elif status == "complete" and missing:
        errors.append("a complete plan cannot have missing_information")
    elif status == "needs_input" and not missing:
        errors.append("needs_input must include at least one question")
    if not _string_list(plan.get("warnings", [])):
        errors.append("warnings must be a list of non-empty strings")
    if status != "complete":
        return errors
    if not _text(plan.get("heading"), HEADING_MAX):
        errors.append(f"heading must be non-empty text of at most {HEADING_MAX} characters")
    if not _text(plan.get("about_text"), ABOUT_MAX):
        errors.append(f"about_text must be non-empty text of at most {ABOUT_MAX} characters")
    if plan.get("contact") != brief.get("contact"):
        errors.append("contact must match the brief exactly")
    return errors


def validate_review(review, brief, reviewer, round_number):
    """Handoff check for one agent's review of its partner's plan."""
    if not isinstance(review, dict):
        return ["review must be a JSON object"]
    if _nesting_depth(review, MAX_DEPTH) > MAX_DEPTH:
        return [f"review nests deeper than {MAX_DEPTH} levels"]
    errors = []
    extra = sorted(set(review) - REVIEW_FIELDS)
    if extra:
        errors.append("review has unexpected fields: " + ", ".join(extra))
    if review.get("request_id") != brief.get("request_id"):
        errors.append("request_id does not match the brief")
    if review.get("agent_name") != reviewer:
        errors.append(f'agent_name must be "{reviewer}"')
    if review.get("round") != round_number or isinstance(review.get("round"), bool):
        errors.append(f"round must be {round_number}")
    verdict = review.get("verdict")
    if verdict not in ("agree", "revise"):
        errors.append('verdict must be "agree" or "revise"')
    requests = review.get("requests")
    if not isinstance(requests, list):
        errors.append("requests must be a list")
        return errors
    if verdict == "agree" and requests:
        errors.append("an agree review cannot include change requests")
    if verdict == "revise" and not 1 <= len(requests) <= MAX_REQUESTS:
        errors.append(f"a revise review needs 1 to {MAX_REQUESTS} change requests")
    allowed = REVIEWABLE[reviewer]
    for item in requests:
        if not isinstance(item, dict) or set(item) != {"target_field", "reason"}:
            errors.append("each request must have exactly target_field and reason")
        elif not isinstance(item["target_field"], str):
            # Type-check first: a list or dict here is unhashable and would crash a set lookup.
            errors.append("each target_field must be text")
        elif item["target_field"] not in allowed:
            errors.append(f"{reviewer} may only ask to change {sorted(allowed)}")
        elif not _text(item["reason"], REASON_MAX):
            errors.append(f"each reason must be non-empty text of at most {REASON_MAX} characters")
    return errors


def final_plan_gate(brief, content, design):
    """Re-check both plans together before building. Agent verdicts are not trusted."""
    errors = [f"content: {e}" for e in validate_content_plan(content, brief)]
    errors += [f"design: {e}" for e in validate_design_plan(design, brief)]
    if not errors:
        if content["status"] != "complete" or design["status"] != "complete":
            errors.append("both plans must be complete")
        if not (brief["request_id"] == content["request_id"] == design["request_id"]):
            errors.append("request_id differs between brief and plans")
    return errors


def _parse(raw):
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None
    except RecursionError:
        return None


def _digest(value):
    """Short fingerprint, so a trace shows what moved between steps without copying user text."""
    try:
        data = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    except (TypeError, ValueError, RecursionError):
        data = f"<unserializable {type(value).__name__}>"
    return hashlib.sha256(data.encode("utf-8", "surrogatepass")).hexdigest()[:12]


def _changed_fields(old, new):
    if not isinstance(old, dict) or not isinstance(new, dict):
        return []
    return sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))


# --- Keeping input text out of the trace -------------------------------------
# The trace may be logged or shown to someone other than the user, so it only
# keeps text this code wrote: field names from the contracts and error
# messages from the list below. Anything else (an agent's made-up field name,
# its questions, an unknown exception name, tag names from a generated page)
# becomes a fingerprint.
BRIEF_FIELDS = {"request_id", "name", "purpose", "about", "contact", "style_preferences"}
DESIGN_FIELDS = {"request_id", "agent_name", "status", "colors", "typography", "section_order",
                 "spacing", "responsive_rules", "warnings"}
TASK_FIELDS = {"kind", "request_id", "brief", "round", "content_plan", "design_plan", "plan",
               "requests", "errors"}
TRACE_FIELD_NAMES = frozenset(BRIEF_FIELDS | DESIGN_FIELDS | TASK_FIELDS | CONTENT_FIELDS | REVIEW_FIELDS)
_TAGS = frozenset({"html", "head", "body", "title", "meta", "style", "header", "main", "section", "footer",
                   "nav", "div", "span", "p", "a", "h1", "h2", "h3", "ul", "ol", "li", "strong", "em",
                   "br", "address", "script", "iframe", "frame", "frameset", "object", "embed", "applet",
                   "img", "picture", "source", "video", "audio", "track", "svg", "math", "link", "base",
                   "form", "input", "button", "textarea", "select"})
_ATTRS = frozenset({"src", "srcset", "action", "formaction", "data", "poster", "background", "ping",
                    "xlink:href", "href", "style", "onerror", "onload", "onclick", "onmouseover",
                    "onfocus", "onblur", "onchange", "onsubmit", "onkeydown", "onkeyup", "oninput"})
_N = r"\d+(?:\.\d+)?"
_SAFE_ERRORS = [re.compile(p) for p in (
    r"(content plan|review|plan) must be a JSON object",
    rf"(content plan|review|plan) nests deeper than {_N} levels",
    r"request_id does not match the brief",
    r'agent_name must be "(content_agent|design_agent)"',
    r"status must be complete, needs_input, or failed",
    r"missing_information must be a list of non-empty strings",
    r"a complete plan cannot have missing_information",
    r"needs_input must include at least one question",
    r"warnings must be a list( of non-empty strings)?",
    rf"(heading|about_text) must be non-empty text of at most {_N} characters",
    r"contact must match the brief exactly",
    rf"round must be {_N}",
    r'verdict must be "agree" or "revise"',
    r"requests must be a list",
    r"an agree review cannot include change requests",
    rf"a revise review needs 1 to {_N} change requests",
    r"each request must have exactly target_field and reason",
    r"each target_field must be text",
    r"(content_agent|design_agent) may only ask to change \[[a-z_', ]+\]",
    rf"each reason must be non-empty text of at most {_N} characters",
    r"response was not valid JSON",
    rf"(content_agent|design_agent) replied after the {_N}s deadline; reply discarded",
    rf"run passed the {_N}s deadline (before an agent call|before the final plan gate|before building"
    r"|before returning the page)",
    r"agent reported failed",
    rf"content and design plans did not agree after {_N} rounds",
    r"both plans must be complete",
    r"request_id differs between brief and plans",
    r"(colors|typography|spacing|responsive_rules) must be a JSON object",
    r"plan must not contain URLs or external assets",
    r"colors\.(background|text|accent) must be a 6-digit hex value like #FFF8EE",
    rf"text/background contrast is {_N}:1, needs at least {_N}:1",
    r"typography\.(heading_font|body_font) must be one of \[[A-Za-z', -]+\]",
    rf"typography\.base_size_px must be a whole number from {_N} to {_N}",
    r'section_order must be exactly \["heading", "about", "contact"\]',
    rf"spacing\.(section_gap_px|max_width_px) must be from {_N} to {_N}",
    rf"responsive_rules\.(breakpoint_px) must be from {_N} to {_N}",
    r"responsive_rules\.mobile_layout must be [a-z_ \"]+",
    r"brief\.(request_id|name|purpose|about|contact) must be non-empty text",
    rf"brief\.(request_id|name|purpose|about|contact) must be at most {_N} characters",
    r"brief\.(request_id|name|purpose|about|contact) contains unsupported characters",
    r"brief must be a JSON object",
    r"design plan must be complete before building",
    r"page is empty",
    r"page is larger than 256 KiB",
    r"page contains a meta refresh",
    r"stylesheet can fetch a resource",
    r"page is missing the default-src 'none' content security policy",
    r"page must have exactly one h1",
    r"page does not show the approved (name|contact) exactly as supplied",
)]
_UNEXPECTED = re.compile(r"(content plan|review) has unexpected fields: (.*)", re.DOTALL)
_EXCEPTION = re.compile(r"(model call failed|response could not be checked|page could not be parsed): (.*)",
                        re.DOTALL)
_TAG_ERROR = re.compile(r"<([^>]*)> (has an event handler attribute \((.*)\)|loads a resource through (.*)"
                        r"|links outside the page|inline style can fetch a resource)", re.DOTALL)
_BLOCKED = re.compile(r"page contains blocked elements: (.*)", re.DOTALL)
_PREFIXED = re.compile(r"(content|design): (.*)", re.DOTALL)


def _trace_name(name):
    return name if isinstance(name, str) and name in TRACE_FIELD_NAMES else f"field#{_digest(name)}"


def _trace_error(message):
    """An error message as it may appear in the trace: kept if this code wrote all
    of it, otherwise rewritten so no input text gets through."""
    if not isinstance(message, str):
        return f"error#{_digest(message)}"
    if any(p.fullmatch(message) for p in _SAFE_ERRORS):
        return message
    m = _PREFIXED.fullmatch(message)
    if m:
        return f"{m.group(1)}: {_trace_error(m.group(2))}"
    m = _UNEXPECTED.fullmatch(message)
    if m:
        return f"{m.group(1)} has unexpected fields: " + ", ".join(_trace_name(n) for n in m.group(2).split(", "))
    m = _EXCEPTION.fullmatch(message)
    if m:
        name = m.group(2)
        known = isinstance(getattr(builtins, name, None), type) and issubclass(getattr(builtins, name), BaseException)
        return f"{m.group(1)}: " + (name if known else f"exception#{_digest(name)}")
    m = _TAG_ERROR.fullmatch(message)
    if m:
        tag = m.group(1) if m.group(1) in _TAGS else f"tag#{_digest(m.group(1))}"
        attr = m.group(3) if m.group(3) is not None else m.group(4)
        if attr is None:
            return f"<{tag}> {m.group(2)}"
        shown = attr if attr in _ATTRS else f"attribute#{_digest(attr)}"
        if m.group(3) is not None:
            return f"<{tag}> has an event handler attribute ({shown})"
        return f"<{tag}> loads a resource through {shown}"
    m = _BLOCKED.fullmatch(message)
    if m:
        return "page contains blocked elements: " + ", ".join(
            t if t in _TAGS else f"tag#{_digest(t)}" for t in m.group(1).split(", "))
    if message.startswith("sections must be "):
        return f"sections must be {['heading', 'about', 'contact']}, found other sections #{_digest(message)}"
    return f"unrecognized error #{_digest(message)}"


def _trace_errors(errors):
    return [_trace_error(e) for e in errors]


def _trace_fields(value):
    """Fingerprint per top-level field, with unknown field names fingerprinted too."""
    if not isinstance(value, dict):
        return None
    return {_trace_name(key): _digest(item)
            for key, item in sorted(value.items(), key=lambda kv: str(kv[0]))}


def run_planning_loop(brief, content_agent, design_agent, clock=time.monotonic,
                      deadline_seconds=DEADLINE_SECONDS):
    """Run plans -> review rounds -> final plan gate -> build -> final checks.

    content_agent(task) and design_agent(task) return raw model text. Each task
    is a dict with kind ("plan", "review", or "revise"), request_id, the brief,
    and what that step needs. Returns a dict; html is set only when ready.

    The result also has "trace" (one event per check and agent call, in
    order; agent text appears only as fingerprints and lengths) and
    "warnings" (non-blocking notes from final validation on a ready page).
    """
    log = []
    trace = []
    warnings = []

    def emit(event):
        event["seq"] = len(trace) + 1
        trace.append(event)
        return event
    started = clock()
    state = {"content": None, "design": None, "rounds": 0}

    def check_deadline(when):
        if clock() - started > deadline_seconds:
            raise _Stop("failed", "timed_out", [f"run passed the {deadline_seconds}s deadline {when}"])

    def call(agent_name, agent, task, check):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            check_deadline("before an agent call")
            entry = {"agent": agent_name, "kind": task["kind"], "round": task.get("round", 0),
                     "attempt": attempt}
            event = {"event": "agent_call", "agent": agent_name, "kind": task["kind"],
                     "round": task.get("round", 0), "attempt": attempt,
                     "sent": {"fields": sorted(_trace_name(k) for k in task if k != "brief"),
                              "digest": _digest(task)},
                     "received": None}
            try:
                raw = agent(task)
            except Exception as exc:  # provider errors and timeouts use the attempt
                errors = [f"model call failed: {type(exc).__name__}"]
            else:
                event["received"] = {"chars": len(raw) if isinstance(raw, str) else None,
                                     "digest": _digest(raw), "json": False}
                if clock() - started > deadline_seconds:
                    # A reply that arrives after the deadline is discarded, never used.
                    entry.update(accepted=False, late=True)
                    log.append(entry)
                    message = f"{agent_name} replied after the {deadline_seconds}s deadline; reply discarded"
                    emit(dict(event, accepted=False, late=True, errors=_trace_errors([message])))
                    raise _Stop("failed", "timed_out", [message])
                value = _parse(raw)
                if value is None:
                    errors = ["response was not valid JSON"]
                else:
                    event["received"].update(json=True, fields=_trace_fields(value))
                    try:
                        errors = check(value)
                    except Exception as exc:  # a check must never crash the run
                        errors = [f"response could not be checked: {type(exc).__name__}"]
            entry["accepted"] = not errors
            log.append(entry)
            emit(dict(event, accepted=not errors, errors=_trace_errors(errors)))
            if not errors:
                return value
            task = dict(task, errors=errors)
        stage = f"{agent_name}:{task['kind']}"
        raise _Stop("failed", stage, errors)

    def accept_plan(agent_name, plan):
        if plan["status"] == "needs_input":
            questions = plan.get("missing_information") or plan.get("warnings") or ["agent needs input"]
            raise _Stop("needs_input", f"{agent_name}:plan", questions)
        if plan["status"] == "failed":
            raise _Stop("failed", f"{agent_name}:plan", ["agent reported failed"])
        return plan

    def content_check(plan):
        return validate_content_plan(plan, brief)

    def design_check(plan):
        return validate_design_plan(plan, brief)

    def result(status, stage, errors, html=None):
        return {"request_id": brief.get("request_id") if isinstance(brief, dict) else None,
                "status": status, "stage": stage, "errors": list(errors),
                "rounds": state["rounds"], "content_plan": state["content"],
                "design_plan": state["design"], "html": html, "calls": log,
                "trace": trace, "warnings": list(warnings) if html is not None else []}

    def finish(status, stage, errors, html=None):
        if status == "needs_input":
            # These are the agent's own questions for the user: fingerprint them.
            shown = [f"question#{_digest(q)}" for q in errors]
        else:
            shown = _trace_errors(errors)
        returned = result(status, stage, errors, html)
        event = {"event": "result", "status": status, "stage": stage, "errors": shown}
        if returned["warnings"]:
            # What was handed back with the page, so a trace shows the warning reached
            # the result and not only final checks. Field, code and pattern id, never the text.
            event["warnings"] = [{k: w[k] for k in ("field", "code", "pattern")} for w in returned["warnings"]]
        emit(event)
        return returned

    def revise(agent_name, agent, task, check, old_plan):
        """Run a revision and record which requested fields it actually changed."""
        new_plan = call(agent_name, agent, task, check)
        requested = sorted({r["target_field"] for r in task["requests"]})
        changed = _changed_fields(old_plan, new_plan)
        trace[-1].update(requested_fields=sorted(_trace_name(f) for f in requested),
                         changed_fields=sorted(_trace_name(f) for f in changed),
                         ignored_requests=sorted(_trace_name(f) for f in set(requested) - set(changed)))
        return new_plan

    errors = validate_brief(brief)
    emit({"event": "brief_check", "passed": not errors, "errors": _trace_errors(errors),
          "fields": _trace_fields(brief)})
    if errors:
        return finish("failed", "brief", errors)

    try:
        base = {"request_id": brief["request_id"], "brief": brief}
        state["content"] = accept_plan(CONTENT_AGENT, call(
            CONTENT_AGENT, content_agent, dict(base, kind="plan"), content_check))
        state["design"] = accept_plan(DESIGN_AGENT, call(
            DESIGN_AGENT, design_agent, dict(base, kind="plan"), design_check))

        for round_number in range(1, MAX_REVIEW_ROUNDS + 1):
            state["rounds"] = round_number
            design_review = call(DESIGN_AGENT, design_agent, dict(
                base, kind="review", round=round_number, content_plan=state["content"]),
                lambda r, n=round_number: validate_review(r, brief, DESIGN_AGENT, n))
            content_review = call(CONTENT_AGENT, content_agent, dict(
                base, kind="review", round=round_number, design_plan=state["design"]),
                lambda r, n=round_number: validate_review(r, brief, CONTENT_AGENT, n))
            if design_review["verdict"] == "agree" and content_review["verdict"] == "agree":
                break
            if round_number == MAX_REVIEW_ROUNDS:
                raise _Stop("failed", "review_loop", [
                    f"content and design plans did not agree after {MAX_REVIEW_ROUNDS} rounds"])
            if design_review["verdict"] == "revise":
                state["content"] = accept_plan(CONTENT_AGENT, revise(CONTENT_AGENT, content_agent, dict(
                    base, kind="revise", round=round_number, plan=state["content"],
                    requests=design_review["requests"]), content_check, state["content"]))
            if content_review["verdict"] == "revise":
                state["design"] = accept_plan(DESIGN_AGENT, revise(DESIGN_AGENT, design_agent, dict(
                    base, kind="revise", round=round_number, plan=state["design"],
                    requests=content_review["requests"]), design_check, state["design"]))
        check_deadline("before the final plan gate")
    except _Stop as stop:
        return finish(stop.status, stop.stage, stop.errors)

    errors = final_plan_gate(brief, state["content"], state["design"])
    emit({"event": "plan_gate", "passed": not errors, "errors": _trace_errors(errors)})
    if errors:
        return finish("failed", "plan_gate", errors)

    content = state["content"]
    page_facts = {"request_id": brief["request_id"], "name": brief["name"],
                  "purpose": content["heading"], "about": content["about_text"],
                  "contact": content["contact"]}
    try:
        check_deadline("before building")
        html = build_site(page_facts, state["design"])
    except BuildError as exc:
        emit({"event": "build", "passed": False, "errors": _trace_errors(str(exc).split("; "))})
        return finish("failed", "build", [str(exc)])
    except _Stop as stop:
        return finish(stop.status, stop.stage, stop.errors)
    emit({"event": "build", "passed": True, "errors": [], "html_digest": _digest(html)})
    errors = check_final_html(html, page_facts)
    warnings.extend(find_instruction_like_text(page_facts))
    emit({"event": "final_checks", "passed": not errors, "errors": _trace_errors(errors),
          "warnings": [{"field": w["field"], "code": w["code"], "pattern": w["pattern"]} for w in warnings]})
    if errors:
        return finish("failed", "final_checks", errors)
    try:
        check_deadline("before returning the page")
    except _Stop as stop:
        return finish(stop.status, stop.stage, stop.errors)
    return finish("ready", "done", [], html=html)
