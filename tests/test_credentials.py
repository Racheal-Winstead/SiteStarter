import contextlib
import io
import subprocess
import unittest
from unittest.mock import patch

from sitestarter.credentials import CredentialError, load_anthropic_key, main

FAKE = "FAKE-TEST-CREDENTIAL-NOT-A-REAL-KEY"


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_environment_precedence_without_keychain(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": FAKE}), patch("subprocess.run") as run:
            secret = load_anthropic_key()
        run.assert_not_called()
        self.assertEqual(secret.reveal(), FAKE)
        self.assertNotIn(FAKE, str(secret))
        self.assertNotIn(FAKE, repr(secret))

    def test_keychain_command_has_no_secret_and_captures_output(self):
        reply = subprocess.CompletedProcess([], 0, (FAKE + "\n").encode(), b"")
        with patch("sys.platform", "darwin"), patch("subprocess.run", return_value=reply) as run:
            self.assertEqual(load_anthropic_key().reveal(), FAKE)
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["/usr/bin/security", "find-generic-password", "-s", "SiteStarter-Anthropic", "-a", "sitestarter", "-w"])
        self.assertEqual(kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(kwargs["stderr"], subprocess.PIPE)
        self.assertEqual(kwargs["timeout"], 30)
        self.assertNotIn(FAKE, repr(run.call_args))

    def test_failures_never_expose_captured_output(self):
        for code in (44, 36, 128, 1):
            reply = subprocess.CompletedProcess([], code, FAKE.encode(), FAKE.encode())
            with self.subTest(code=code), patch("sys.platform", "darwin"), patch("subprocess.run", return_value=reply):
                with self.assertRaises(CredentialError) as error:
                    load_anthropic_key()
                self.assertNotIn(FAKE, str(error.exception))

    def test_timeout_and_os_errors_have_safe_messages(self):
        for failure in (subprocess.TimeoutExpired("security", 30, output=FAKE), OSError(FAKE)):
            with patch("sys.platform", "darwin"), patch("subprocess.run", side_effect=failure):
                with self.assertRaises(CredentialError) as error:
                    load_anthropic_key()
                self.assertNotIn(FAKE, str(error.exception))

    def test_unsupported_platform_does_not_call_security(self):
        with patch("sys.platform", "linux"), patch("subprocess.run") as run:
            with self.assertRaises(CredentialError):
                load_anthropic_key()
            run.assert_not_called()

    def test_malformed_environment_does_not_silently_use_keychain(self):
        for value in ("", " ", FAKE + "\n"):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": value}), patch("subprocess.run") as run:
                with self.assertRaises(CredentialError):
                    load_anthropic_key()
                run.assert_not_called()

    def test_empty_invalid_encoding_or_extra_newlines_are_rejected(self):
        for value in (b"", b"\n", b"\xff", b"bad key\n", b"key\n\n"):
            with patch("sys.platform", "darwin"), patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, value, b"")):
                with self.assertRaises(CredentialError):
                    load_anthropic_key()

    def test_opt_in_check_prints_only_safe_result(self):
        output = io.StringIO()
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": FAKE}), contextlib.redirect_stdout(output):
            self.assertEqual(main(), 0)
        self.assertNotIn(FAKE, output.getvalue())
        self.assertIn("No API call", output.getvalue())
