"""Final checks on built HTML before anyone can preview or download it.

These run on the finished page, not on the inputs, so they still catch a
problem if the builder changes later (or becomes a model-backed agent).
Every check reads the page itself or the approved brief; none of them trust
what an agent says about its own output.
"""

import re
from html.parser import HTMLParser

REQUIRED_SECTIONS = ["heading", "about", "contact"]
BLOCKED_TAGS = {
    "script", "iframe", "frame", "frameset", "object", "embed", "applet", "img",
    "picture", "source", "video", "audio", "track", "svg", "math", "link", "base",
    "form", "input", "button", "textarea", "select",
}
URL_ATTRS = {"src", "srcset", "action", "formaction", "data", "poster", "background", "ping", "xlink:href"}
CSS_FETCH = re.compile(r"(url\s*\(|@import|expression\s*\()", re.IGNORECASE)
MAX_HTML_BYTES = 256 * 1024
CSP = "default-src 'none'"


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.text = []
        self.styles = []
        self._in_style = False

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, attrs))
        self._in_style = tag == "style"

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, attrs))

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        (self.styles if self._in_style else self.text).append(data)


def check_final_html(html, brief):
    """Return a list of problems. An empty list means the page can be shown."""
    if not isinstance(html, str) or not html.strip():
        return ["page is empty"]
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        return ["page is larger than 256 KiB"]

    page = _Page()
    try:
        page.feed(html)
        page.close()
    except Exception as exc:  # malformed markup should stop the run, not crash it
        return [f"page could not be parsed: {type(exc).__name__}"]

    errors = []
    tag_names = [tag for tag, _ in page.tags]

    blocked = sorted({tag for tag in tag_names if tag in BLOCKED_TAGS})
    if blocked:
        errors.append("page contains blocked elements: " + ", ".join(blocked))

    for tag, attrs in page.tags:
        for name, value in attrs:
            value = value or ""
            if name.startswith("on"):
                errors.append(f"<{tag}> has an event handler attribute ({name})")
            elif name in URL_ATTRS:
                errors.append(f"<{tag}> loads a resource through {name}")
            elif name == "href" and not value.startswith("#"):
                errors.append(f"<{tag}> links outside the page")
            elif name == "style" and CSS_FETCH.search(value):
                errors.append(f"<{tag}> inline style can fetch a resource")
            elif tag == "meta" and name == "http-equiv" and value.lower() == "refresh":
                errors.append("page contains a meta refresh")

    if any(CSS_FETCH.search(css) for css in page.styles):
        errors.append("stylesheet can fetch a resource")

    csp = [dict(attrs).get("content", "") for tag, attrs in page.tags
           if tag == "meta" and (dict(attrs).get("http-equiv") or "").lower() == "content-security-policy"]
    if not any(c.startswith(CSP) for c in csp):
        errors.append("page is missing the default-src 'none' content security policy")

    sections = [dict(attrs).get("id") for tag, attrs in page.tags if tag == "section"]
    if sections != REQUIRED_SECTIONS:
        errors.append(f"sections must be {REQUIRED_SECTIONS}, found {sections}")
    if tag_names.count("h1") != 1:
        errors.append("page must have exactly one h1")

    text = page.text
    if isinstance(brief, dict):
        for key in ("name", "contact"):
            value = brief.get(key)
            if isinstance(value, str) and value not in text:
                errors.append(f"page does not show the approved {key} exactly as supplied")
    else:
        errors.append("brief must be a JSON object")

    return errors
