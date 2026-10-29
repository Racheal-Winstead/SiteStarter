"""Shared text-field rules for the Builder and Coordinator input gate."""

BRIEF_LIMITS = {"request_id": 128, "name": 120, "purpose": 500,
                "about": 4000, "contact": 500}


def text_error(value, limit):
    if not isinstance(value, str) or not value.strip():
        return "must be non-empty text"
    if len(value) > limit:
        return f"must be at most {limit} characters"
    if any((ord(char) < 32 and char not in "\n\r\t")
           or 0xD800 <= ord(char) <= 0xDFFF for char in value):
        return "contains unsupported characters"
    return None
