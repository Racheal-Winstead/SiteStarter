# Coordinator input gate

This first Coordinator component validates form input and translates style choices.
It does not implement agent scheduling, sessions, deadlines, retries, or a web server.
Sam's Design Agent prompt is unchanged.

The form submits `name`, `purpose`, `about`, `contact`, and optionally
`style_preferences`. Do not submit `request_id`: the Coordinator creates it only
after validation succeeds. All supplied business text is preserved exactly.

`brief_contract.py` shares required text rules with the existing Builder:
name 120 characters, purpose 500, about 4000, contact 500, generated request ID 128.
Blank values, non-text values, and unsupported characters are rejected. Contact
remains a text string, allowing phone numbers and multiline details; this is not
email/address/phone ownership or format verification. Separate contact fields
and their conversion into this string remain interface integration work.

Style values are `calm_welcoming`, `clean_professional`, and `bold_expressive`.
Omission defaults to `calm_welcoming`; explicit invalid values produce a field
error. The Coordinator translates the choice to descriptive text in the existing
`style_preferences` field. Legacy Builder/demo inputs still accept descriptive
style text; the restricted choices apply only to new form submissions.

`prepare_brief(submission)` returns `needs_input` with field errors and no brief
on invalid input, or `accepted` with a generated request ID and approved brief.
Accepted means the input passed, never that a website is Ready. The caller must
launch no agents on `needs_input`. Unknown fields are rejected rather than used
as workflow state. This function makes no model calls and stores no session state.

Run the synthetic example:

```sh
python3 -m sitestarter.coordinator --input examples/form-submission.json
python3 -m unittest discover -s tests -v
```

The CLI reports status/errors without logging the submitted business text. It
does not save or generate a website. A live model is not needed for these checks.
