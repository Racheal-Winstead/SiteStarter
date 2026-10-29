"""In-memory, session-owned recorded runs and a server-enforced output gate."""
import copy
import hashlib
import re
import secrets
import threading
import time

from .recorded_run import run_recorded

PATTERNS = (
    ("ignore_previous", re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior)\s+(?:rules|instructions)", re.I)),
    ("markup", re.compile(r"<\s*/?\s*(?:script|iframe|object|embed)\b|\bon\w+\s*=|javascript:", re.I)),
)


def review_warnings(brief, result):
    """Narrow product-review heuristic, not a prompt-injection security boundary."""
    content = result.get("content_plan") or {}
    facts = dict(brief, heading=content.get("heading", ""), about=content.get("about_text", brief["about"]))
    warnings = []
    for field in ("name", "purpose", "heading", "about", "contact"):
        for code, pattern in PATTERNS:
            match = pattern.search(facts[field])
            if match:
                warnings.append({"field": field, "code": code, "passage": facts[field][:4000]})
                break
    return warnings


class RunStore:
    def __init__(self, clock=time.monotonic, ttl=1800, max_sessions=100):
        self.clock, self.ttl, self.max_sessions = clock, ttl, max_sessions
        self.lock = threading.RLock()
        self.sessions = {}

    def _expire(self):
        now = self.clock()
        for sid in list(self.sessions):
            if now - self.sessions[sid]["activity"] >= self.ttl:
                del self.sessions[sid]

    def start(self, brief, sid=None):
        with self.lock:
            self._expire()
            if sid not in self.sessions:
                if len(self.sessions) >= self.max_sessions:
                    raise OverflowError("Too many local sessions")
                sid = secrets.token_urlsafe(32)
            # A new request invalidates the session's prior draft and confirmations.
            record = {"request_id": brief["request_id"], "status": "running", "stage": "planning",
                      "events": ["Brief validated; recorded-response run started."], "warnings": [],
                      "revision": None, "html": None, "brief": copy.deepcopy(brief), "rounds": 0}
            self.sessions[sid] = {"activity": self.clock(), "record": record}
            return sid, record["request_id"]

    def _record(self, sid, rid):
        self._expire()
        session = self.sessions.get(sid)
        if not session or session["record"]["request_id"] != rid:
            raise KeyError("Run unavailable or expired")
        return session["record"]

    def snapshot(self, sid, rid):
        with self.lock:
            r = self._record(sid, rid)
            # Polling never renews activity or returns unreleased HTML.
            return copy.deepcopy({k: r[k] for k in ("request_id", "status", "stage", "events", "warnings", "revision", "rounds")})

    def execute(self, sid, rid, runner=run_recorded):
        with self.lock:
            try:
                r = self._record(sid, rid)
            except KeyError:
                return
            if r["status"] != "running" or r.get("claimed"):
                return
            r["claimed"] = True
            brief = copy.deepcopy(r["brief"])

        def emit(event):
            with self.lock:
                current = self._record(sid, rid)
                current["events"].append(event)

        try:
            result = runner(brief, emit)
            warnings = review_warnings(brief, result) if result["status"] == "ready" else []
            with self.lock:
                r = self._record(sid, rid)  # Late callbacks cannot recreate an expired/edited run.
                r["rounds"] = result.get("rounds", 0)
                for call in result.get("calls", []):
                    r["events"].append(f"{call['agent']} {call['kind']} round {call['round']} attempt {call['attempt']}: " + ("accepted" if call["accepted"] else "rejected"))
                if result["status"] != "ready" or not result.get("html"):
                    r.update(status="timed_out" if result.get("stage") == "timed_out" else ("needs_input" if result["status"] == "needs_input" else "failed"), stage=result["stage"])
                    r["events"].append("Run stopped; output withheld. Review your brief and submit a new run.")
                    return
                r["events"].append("Plan gate, Builder, and final HTML checks passed.")
                r["html"] = result["html"]
                r["revision"] = hashlib.sha256((rid + result["html"]).encode()).hexdigest()
                r["warnings"] = warnings
                r["status"] = "review_required" if warnings else "ready"
                r["stage"] = "review" if warnings else "done"
                r["events"].append("Content warnings require your review; output withheld." if warnings else "Output released: Ready.")
        except KeyError:
            return
        except Exception:
            with self.lock:
                try:
                    r = self._record(sid, rid)
                    r.update(status="failed", stage="execution", html=None)
                    r["events"].append("Run failed; output withheld.")
                except KeyError:
                    pass

    def confirm(self, sid, rid, revision):
        with self.lock:
            r = self._record(sid, rid)
            if r["status"] != "review_required" or not isinstance(revision, str) or not secrets.compare_digest(revision, r["revision"]):
                raise PermissionError("Confirmation does not match a pending reviewed draft")
            r.update(status="ready", stage="done")
            r["events"].extend(["User explicitly confirmed warnings for this draft revision.", "Output released: Ready."])
            self.sessions[sid]["activity"] = self.clock()
            return self.snapshot(sid, rid)

    def output(self, sid, rid):
        with self.lock:
            r = self._record(sid, rid)
            if r["status"] != "ready" or not r["html"]:
                raise PermissionError("Output is not released")
            return r["html"]
