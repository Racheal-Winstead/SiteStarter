"""Build a self-contained page from supplied facts and a validated design plan.

This deterministic renderer is an offline building block, not the AI Builder
or Coordinator described in the architecture. No model, network, or files are
accessed here. Untrusted text is escaped and only validated values enter CSS.
"""

from html import escape

from .design_agent import contrast_ratio, validate_design_plan
from .brief_contract import BRIEF_LIMITS, text_error


class BuildError(ValueError):
    """The inputs cannot produce a validated page."""


def validate_brief(brief):
    """Require explicit facts rather than inventing missing business content."""
    if not isinstance(brief, dict):
        return ["brief must be a JSON object"]
    errors = []
    for key, limit in BRIEF_LIMITS.items():
        error = text_error(brief.get(key), limit)
        if error:
            errors.append(f"brief.{key} {error}")
    return errors


def build_site(brief, plan):
    """Return HTML, or raise BuildError before exposing invalid output.

    The caller supplies approved text in name/purpose/about/contact. Unknown
    brief fields and model-generated prose are never used in the page.
    """
    errors = validate_brief(brief)
    if errors:
        raise BuildError("; ".join(errors))
    errors = validate_design_plan(plan, brief)
    if errors:
        raise BuildError("; ".join(errors))
    if plan["status"] != "complete":
        raise BuildError("design plan must be complete before building")

    text = {key: escape(brief[key], quote=True)
            for key in ("name", "purpose", "about", "contact")}
    colors, fonts = plan["colors"], plan["typography"]
    spacing, mobile = plan["spacing"], plan["responsive_rules"]
    # Accent is valid as a color, but not necessarily readable as text.
    # Choose its foreground instead of assuming a white button label is safe.
    button_text = max(("#000000", "#FFFFFF"),
                      key=lambda color: contrast_ratio(color, colors["accent"]))
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
  <title>{text["name"]}</title>
  <meta name="description" content="{text["purpose"]}">
  <style>
    :root {{ color-scheme: light; --background: {colors["background"]};
      --text: {colors["text"]}; --accent: {colors["accent"]}; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--background); color: var(--text);
      font-family: {fonts["body_font"]}, sans-serif; font-size: {fonts["base_size_px"]}px;
      line-height: 1.7; overflow-wrap: anywhere; }}
    .shell {{ width: min(calc(100% - 48px), {spacing["max_width_px"]}px); margin: auto; }}
    a {{ color: inherit; text-underline-offset: .25em; }}
    a:focus-visible {{ outline: 3px solid currentColor; outline-offset: 6px; }}
    .skip {{ position: absolute; left: 24px; top: -100px; padding: 12px;
      background: var(--background); z-index: 1; }}
    .skip:focus {{ top: 12px; }}
    header {{ display: flex; align-items: center; justify-content: space-between;
      gap: 24px; padding: 28px 0; border-bottom: 1px solid currentColor; }}
    .brand {{ font-weight: 700; text-decoration: none; }}
    nav {{ display: flex; gap: 28px; flex-shrink: 0; }}
    main {{ padding-bottom: {spacing["section_gap_px"]}px; }}
    section {{ padding: {spacing["section_gap_px"]}px 0; }}
    h1, h2 {{ font-family: {fonts["heading_font"]}, serif; line-height: 1.12;
      font-weight: 600; letter-spacing: -.035em; margin: 0 0 24px; }}
    h1 {{ font-size: clamp(2.7rem, 7vw, 5.5rem); max-width: 16ch; }}
    h2 {{ font-size: clamp(1.9rem, 4vw, 2.7rem); }}
    p {{ margin: 0; max-width: 65ch; white-space: pre-line; }}
    #heading {{ padding-top: max(64px, {spacing["section_gap_px"]}px);
      padding-bottom: max(64px, {spacing["section_gap_px"]}px); }}
    #heading p {{ font-size: 1.2em; max-width: 48ch; }}
    .button {{ display: inline-block; margin-top: 32px; padding: 14px 24px;
      background: var(--accent); color: {button_text}; border-radius: 999px;
      text-decoration: none; font-weight: 700; }}
    .detail {{ display: grid; grid-template-columns: 1fr 2fr; gap: 32px;
      border-top: 1px solid currentColor; }}
    footer {{ padding: 24px 0; border-top: 1px solid currentColor; font-size: .85em; }}
    @media (max-width: {mobile["breakpoint_px"]}px) {{
      .shell {{ width: calc(100% - 32px); }}
      header {{ align-items: flex-start; flex-direction: column; gap: 12px; }}
      .detail {{ grid-template-columns: 1fr; gap: 0; }}
      h1 {{ font-size: clamp(2.5rem, 11vw, 4rem); }}
      nav {{ flex-wrap: wrap; }}
    }}
  </style>
</head>
<body>
  <a class="skip" href="#main">Skip to content</a>
  <div class="shell">
    <header>
      <a class="brand" href="#heading">{text["name"]}</a>
      <nav aria-label="Main navigation"><a href="#about">About</a><a href="#contact">Contact</a></nav>
    </header>
    <main id="main" tabindex="-1">
      <section id="heading" aria-labelledby="page-title">
        <h1 id="page-title">{text["name"]}</h1>
        <p>{text["purpose"]}</p>
        <a class="button" href="#contact">Get in touch <span aria-hidden="true">↗</span></a>
      </section>
      <section id="about" class="detail" aria-labelledby="about-title">
        <h2 id="about-title">About</h2><p>{text["about"]}</p>
      </section>
      <section id="contact" class="detail" aria-labelledby="contact-title">
        <h2 id="contact-title">Contact</h2><p>{text["contact"]}</p>
      </section>
    </main>
    <footer>{text["name"]}</footer>
  </div>
</body>
</html>
'''
