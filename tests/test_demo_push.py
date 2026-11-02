"""Offline fixed demonstration verification; no real credentials or HTTP."""

import io
import json
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch
from urllib.parse import parse_qs

from market_sentinel import demo_push, pushover

TOKEN = "T" * 30
USER = "U" * 30


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.load = patch("market_sentinel.demo_push.load_credentials", return_value=(TOKEN, USER)).start()
        self.build = patch("market_sentinel.pushover.build_opener").start()
        response = self.build.return_value.open.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = b'{"status":1}'

    def cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = demo_push.main(args)
        self.assertNotIn(TOKEN, out.getvalue()+err.getvalue())
        self.assertNotIn(USER, out.getvalue()+err.getvalue())
        return code, out.getvalue(), err.getvalue()

    def test_fixed_three_payloads_are_historical_demonstrations(self):
        self.assertEqual(len(demo_push.MESSAGES), 3)
        self.assertEqual([title for title, _ in demo_push.MESSAGES], [
            "Market Sentinel — Oversold", "Market Sentinel — Oversold", "Market Sentinel — Daily Receipt TEST"])
        for _, body in demo_push.MESSAGES:
            self.assertIn("October 30, 2026", body)
            self.assertIn("Demonstration using previously verified data.", body)
        self.assertIn("ADM — Stochastic %K 7.01, %D 5.80.", demo_push.MESSAGES[0][1])
        self.assertIn("CAT — Stochastic %K 12.69, %D 17.04.", demo_push.MESSAGES[1][1])
        for _, body in demo_push.MESSAGES[:2]:
            self.assertIn("Not a new crossing or trading instruction.", body)
        self.assertIn("13 across the historical sample", demo_push.MESSAGES[2][1])
        self.assertIn("Not a live scheduled monitoring result.", demo_push.MESSAGES[2][1])

    def test_three_exact_https_requests_no_extra_validation_call(self):
        code, out, _ = self.cli(["--send"])
        self.assertEqual(code, 0)
        calls = self.build.return_value.open.call_args_list
        self.assertEqual(len(calls), 3)
        for call, (title, body) in zip(calls, demo_push.MESSAGES):
            request = call.args[0]
            self.assertEqual(request.full_url, pushover.ENDPOINT)
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(call.kwargs, {"timeout": 10})
            self.assertEqual(parse_qs(request.data.decode()), dict(token=[TOKEN], user=[USER], title=[title], message=[body]))
        self.assertEqual([r["status"] for r in json.loads(out)["results"]], ["api_accepted"]*3)
        self.assertIn("NOT independently confirmed", out)

    def test_no_send_flag_reads_no_credentials_or_http(self):
        self.assertEqual(self.cli([])[0], 2)
        self.load.assert_not_called()
        self.build.assert_not_called()

    def test_timeout_stops_without_retry_or_remaining_requests(self):
        self.build.return_value.open.side_effect = TimeoutError(TOKEN+USER)
        code, out, _ = self.cli(["--send"])
        self.assertEqual(code, 1)
        self.assertEqual(self.build.return_value.open.call_count, 1)
        self.assertEqual([r["status"] for r in json.loads(out)["results"]],
                         ["failed_or_unknown", "not_attempted_after_failure", "not_attempted_after_failure"])

    def test_second_failure_does_not_repeat_first_or_attempt_third(self):
        with patch("market_sentinel.demo_push._send_message", side_effect=[None, pushover.PushError("Rejected request")]) as send:
            code, out, _ = self.cli(["--send"])
        self.assertEqual(code, 1)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(json.loads(out)["results"][0]["status"], "api_accepted")

    def test_unexpected_transport_exception_never_exposes_credentials(self):
        self.build.side_effect = RuntimeError(TOKEN+USER)
        code, out, _ = self.cli(["--send"])
        self.assertEqual(code, 1)
        self.assertIn("details suppressed", out)

    def test_credential_failure_sends_nothing(self):
        self.load.side_effect = pushover.PushError("Keychain unavailable")
        self.assertEqual(self.cli(["--send"])[0], 1)
        self.build.assert_not_called()

    def test_fixed_push_test_payload_stays_unchanged(self):
        pushover.send_test_push(TOKEN, USER)
        fields = parse_qs(self.build.return_value.open.call_args.args[0].data.decode())
        self.assertEqual(fields["title"], ["Market Sentinel — Test"])
        self.assertEqual(fields["message"], ["Push transport verification. No market signal or trading action."])


if __name__ == "__main__":
    unittest.main()
