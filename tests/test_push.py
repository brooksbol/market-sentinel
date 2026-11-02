"""Offline tests: synthetic credentials, mocked HTTP and mocked Keychain only."""

import io
import json
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

from market_sentinel import pushover
from market_sentinel.__main__ import main

# Clearly synthetic, format-valid strings. Never use real credentials in fixtures.
TOKEN = "T" * 30
USER = "U" * 30
ENV = {"PUSHOVER_APP_TOKEN": TOKEN, "PUSHOVER_USER_KEY": USER}


class OfflineCase(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.dict("os.environ", {}, clear=True).start()
        self.build = patch("market_sentinel.pushover.build_opener").start()
        self.open = self.build.return_value.open
        self.keychain = patch("market_sentinel.pushover.subprocess.run").start()
        self.keychain.side_effect = AssertionError("Real Keychain access forbidden in tests")

    def response(self, payload, status=200):
        response = self.open.return_value.__enter__.return_value
        response.status = status
        response.read.return_value = (
            payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        )
        return response

    def assert_safe(self, text):
        self.assertNotIn(TOKEN, text)
        self.assertNotIn(USER, text)

    def cli(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        self.assert_safe(stdout.getvalue() + stderr.getvalue())
        return code, stdout.getvalue(), stderr.getvalue()


class TransportTests(OfflineCase):
    def test_request_is_exact_fixed_https_post(self):
        response = self.response({"status": 1, "request": "synthetic-request"})
        pushover.send_test_push(TOKEN, USER)
        request = self.open.call_args.args[0]
        self.assertEqual(request.full_url, pushover.ENDPOINT)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(parse_qs(request.data.decode()), {
            "token": [TOKEN], "user": [USER],
            "title": ["Market Sentinel — Test"],
            "message": ["Push transport verification. No market signal or trading action."],
        })
        self.assertIn("application/x-www-form-urlencoded", request.get_header("Content-type"))
        self.assertNotIn(TOKEN, request.full_url + str(request.headers))
        self.assertEqual(self.open.call_args.kwargs, {"timeout": 10})
        response.read.assert_called_once_with(pushover.MAX_RESPONSE_BYTES + 1)
        self.assertEqual(self.open.call_count, 1)
        self.keychain.assert_not_called()

    def test_redirects_and_ambient_proxies_are_disabled(self):
        self.response({"status": 1})
        pushover.send_test_push(TOKEN, USER)
        handlers = self.build.call_args.args
        self.assertEqual(handlers[0].proxies, {})
        self.assertIsNone(handlers[1].redirect_request(
            None, None, 302, "redirect", {}, "https://elsewhere.invalid"))

    def test_rejected_provider_status_never_echoes_body(self):
        self.response({"status": 0, "errors": [TOKEN, USER]})
        with self.assertRaises(pushover.PushError) as caught:
            pushover.send_test_push(TOKEN, USER)
        self.assert_safe(str(caught.exception))

    def test_auth_http_errors_are_sanitized_and_not_retried(self):
        for code in (400, 401, 403):
            with self.subTest(code=code):
                self.open.reset_mock()
                self.open.side_effect = HTTPError(
                    pushover.ENDPOINT, code, TOKEN, {}, io.BytesIO(USER.encode()))
                with self.assertRaisesRegex(pushover.PushError, "credentials or request") as caught:
                    pushover.send_test_push(TOKEN, USER)
                self.assert_safe(str(caught.exception))
                self.assertEqual(self.open.call_count, 1)

    def test_quota_and_server_errors(self):
        for code, expected in ((429, "quota"), (500, "HTTP failure"), (302, "HTTP failure")):
            with self.subTest(code=code):
                self.open.side_effect = HTTPError(
                    pushover.ENDPOINT, code, TOKEN, {}, io.BytesIO(USER.encode()))
                with self.assertRaisesRegex(pushover.PushError, expected) as caught:
                    pushover.send_test_push(TOKEN, USER)
                self.assert_safe(str(caught.exception))

    def test_timeout_and_network_failures_are_ambiguous_and_not_retried(self):
        for error in (TimeoutError(TOKEN), URLError(USER), OSError(TOKEN + USER)):
            with self.subTest(error=type(error).__name__):
                self.open.reset_mock()
                self.open.side_effect = error
                with self.assertRaisesRegex(pushover.PushError, "acceptance is unknown") as caught:
                    pushover.send_test_push(TOKEN, USER)
                self.assert_safe(str(caught.exception))
                self.assertEqual(self.open.call_count, 1)

    def test_malformed_and_invalid_success_shapes_fail_closed(self):
        for payload in (b"not-json", b"\xff", [], None, {}, {"status": True},
                        {"status": "1"}, {"status": 1.0}):
            with self.subTest(payload=payload):
                self.response(payload)
                with self.assertRaises(pushover.PushError):
                    pushover.send_test_push(TOKEN, USER)

    def test_oversized_and_non_200_responses_fail(self):
        self.response(b"x" * (pushover.MAX_RESPONSE_BYTES + 1))
        with self.assertRaises(pushover.PushError):
            pushover.send_test_push(TOKEN, USER)
        self.response({"status": 1}, status=201)
        with self.assertRaises(pushover.PushError):
            pushover.send_test_push(TOKEN, USER)

    def test_invalid_credentials_never_reach_http(self):
        for token, user in (("", USER), (TOKEN, "bad"), ("\n" + TOKEN, USER)):
            with self.subTest(token_length=len(token)):
                with self.assertRaises(pushover.PushError):
                    pushover.send_test_push(token, user)
        self.build.assert_not_called()


class CredentialTests(OfflineCase):
    def test_complete_environment_handoff_avoids_keychain(self):
        with patch.dict("os.environ", ENV):
            self.assertEqual(pushover.load_credentials(), (TOKEN, USER))
        self.keychain.assert_not_called()

    def test_partial_or_empty_environment_fails_without_keychain(self):
        for env in ({"PUSHOVER_APP_TOKEN": TOKEN}, {"PUSHOVER_USER_KEY": USER},
                    {"PUSHOVER_APP_TOKEN": "", "PUSHOVER_USER_KEY": USER}):
            with self.subTest(keys=list(env)), patch.dict("os.environ", env, clear=True):
                with self.assertRaisesRegex(pushover.PushError, "both"):
                    pushover.load_credentials()
        self.keychain.assert_not_called()

    def test_mac_keychain_uses_fixed_service_accounts_and_no_secret_arguments(self):
        self.keychain.side_effect = [
            Mock(returncode=0, stdout=TOKEN + "\n"), Mock(returncode=0, stdout=USER + "\n")]
        with patch("market_sentinel.pushover.sys.platform", "darwin"):
            self.assertEqual(pushover.load_credentials(), (TOKEN, USER))
        for call, account in zip(self.keychain.call_args_list, ("application-token", "user-key")):
            self.assertEqual(call.args[0], ["/usr/bin/security", "find-generic-password",
                             "-s", "market-sentinel.pushover", "-a", account, "-w"])
            self.assert_safe(str(call))
            self.assertTrue(call.kwargs["capture_output"])
            self.assertEqual(call.kwargs["timeout"], 15)

    def test_keychain_rejection_and_timeout_do_not_leak(self):
        for result in (Mock(returncode=44, stdout=TOKEN, stderr=USER),
                       subprocess.TimeoutExpired([TOKEN], 15, output=USER)):
            with self.subTest(result=type(result).__name__):
                self.keychain.side_effect = result if isinstance(result, Exception) else None
                self.keychain.return_value = result
                with patch("market_sentinel.pushover.sys.platform", "darwin"):
                    with self.assertRaises(pushover.PushError) as caught:
                        pushover.load_credentials()
                self.assert_safe(str(caught.exception))

    def test_non_mac_without_environment_fails_cleanly(self):
        with patch("market_sentinel.pushover.sys.platform", "linux"):
            with self.assertRaises(pushover.PushError):
                pushover.load_credentials()
        self.keychain.assert_not_called()


class CliTests(OfflineCase):
    def test_no_send_flag_never_reads_credentials_or_sends(self):
        code, stdout, _ = self.cli(["push-test"])
        self.assertEqual(code, 2)
        self.assertIn("No notification sent", stdout)
        self.build.assert_not_called()
        self.keychain.assert_not_called()

    def test_api_acceptance_does_not_claim_phone_delivery(self):
        self.response({"status": 1, "request": "synthetic-request"})
        with patch.dict("os.environ", ENV):
            code, stdout, stderr = self.cli(["push-test", "--send"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("API accepted", stdout)
        self.assertIn("Phone delivery is NOT confirmed", stdout)

    def test_failed_requests_have_nonzero_exit_and_no_success_claim(self):
        self.open.side_effect = TimeoutError(TOKEN + USER)
        with patch.dict("os.environ", ENV):
            code, stdout, stderr = self.cli(["push-test", "--send"])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("acceptance is unknown", stderr)

    def test_bad_environment_reports_no_credentials(self):
        with patch.dict("os.environ", {"PUSHOVER_APP_TOKEN": TOKEN}):
            code, _, stderr = self.cli(["push-test", "--send"])
        self.assertEqual(code, 1)
        self.assertIn("Set both", stderr)
        self.build.assert_not_called()

    def test_unexpected_exception_is_not_logged(self):
        self.build.side_effect = RuntimeError(TOKEN + USER)
        with patch.dict("os.environ", ENV):
            code, _, stderr = self.cli(["push-test", "--send"])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", stderr)

    def test_invalid_arguments_do_not_echo_pasted_secrets(self):
        for argv in ([TOKEN], ["push-test", "--token", TOKEN]):
            with self.subTest(argv_kind=argv[0] == "push-test"):
                output = io.StringIO()
                with redirect_stderr(output), self.assertRaises(SystemExit) as caught:
                    main(argv)
                self.assertEqual(caught.exception.code, 2)
                self.assert_safe(output.getvalue())
        self.build.assert_not_called()
        self.keychain.assert_not_called()


if __name__ == "__main__":
    unittest.main()
