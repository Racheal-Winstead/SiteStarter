"""Backend-only Anthropic credential loading; never called by the recorded demo."""
import os
import subprocess
import sys

KEYCHAIN_SERVICE = "SiteStarter-Anthropic"
KEYCHAIN_ACCOUNT = "sitestarter"


class CredentialError(RuntimeError):
    """Safe, fixed diagnostic that never includes credential values."""


class Secret:
    """Redact incidental printing. Reveal only to the future provider client.

    This is not encrypted process memory. Never serialize the revealed value
    into a response, log, exception message, or subprocess argument.
    """
    __slots__ = ("_value",)

    def __init__(self, value):
        self._value = value

    def __repr__(self):
        return "Secret([REDACTED])"

    def __str__(self):
        return "[REDACTED]"

    def reveal(self):
        """Return only for backend provider-client authentication."""
        return self._value


def _validated(value):
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        raise CredentialError("The credential is empty or contains whitespace/control characters. Correct it privately in Keychain Access.")
    return Secret(value)


def load_anthropic_key():
    """Prefer explicit environment configuration, else read the named macOS item.

    Captures security's stdout in memory; never prints it or writes a key file.
    Keychain may prompt the user. Denial, cancellation, or timeout never falls
    back to another Keychain item or changes access-control settings.
    """
    if "ANTHROPIC_API_KEY" in os.environ:
        return _validated(os.environ["ANTHROPIC_API_KEY"])
    if sys.platform != "darwin":
        raise CredentialError("macOS Keychain is unavailable. Configure ANTHROPIC_API_KEY privately on this backend.")
    try:
        completed = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
             "-a", KEYCHAIN_ACCOUNT, "-w"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30, check=False,
        )
    except subprocess.TimeoutExpired:
        raise CredentialError("Keychain access timed out. Retry and respond to any macOS permission prompt.") from None
    except OSError:
        raise CredentialError("Could not access macOS Keychain.") from None
    if completed.returncode == 44:
        raise CredentialError("Keychain item not found. Save SiteStarter-Anthropic with account sitestarter in your login keychain.")
    if completed.returncode != 0:
        raise CredentialError("Keychain access was denied, cancelled, or unavailable. Check the item privately in Keychain Access.")
    try:
        value = completed.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise CredentialError("The Keychain credential is not valid text. Correct it privately in Keychain Access.") from None
    # security terminates successful output with a newline; do not silently
    # normalize whitespace inside a malformed stored credential.
    if value.endswith("\n"):
        value = value[:-1]
    return _validated(value)


def main():
    """Opt-in check: actually reads a secret, but prints only a fixed outcome."""
    try:
        secret = load_anthropic_key()
    except CredentialError as exc:
        print(f"Credential unavailable: {exc}", file=sys.stderr)
        return 1
    del secret
    print("Credential loaded; value hidden. No API call was made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
