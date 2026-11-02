"""Offline synthetic Tradier fixtures. No actual HTTP or credential-store access."""

import io
import json
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from market_sentinel import tradier, tradier_report

TOKEN = "synthetic-tradier-token"
START = date(2026, 1, 5)
END = date(2026, 2, 27)
KW = dict(symbol="CLX", environment="production", start=START, end=END, completed_through=END)


def fixture(values=None):
    # Fixed range [10,110]: close=10+x makes raw K=x. Dates are synthetic weekdays.
    values = [50] * 13 + [30, 60, 90, 30, 0, 0, 0, 60, 0, 0, 0] if values is None else values
    rows = []
    day = START
    for value in values:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        rows.append(dict(date=str(day), open=60, high=110, low=10, close=10 + value, volume=1000))
        day += timedelta(days=1)
    return {"history": {"day": rows}}


class OfflineCase(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.dict("os.environ", {}, clear=True).start()
        self.build = patch("market_sentinel.tradier.build_opener").start()
        self.open = self.build.return_value.open
        self.keychain = patch("market_sentinel.tradier.subprocess.run").start()
        self.keychain.side_effect = AssertionError("Real credential-store access forbidden")

    def response(self, payload=None, status=200):
        response = self.open.return_value.__enter__.return_value
        response.status = status
        response.read.return_value = json.dumps(fixture() if payload is None else payload).encode()
        return response

    def normalize(self, payload=None, **changes):
        return tradier.normalize_history(fixture() if payload is None else payload, **(KW | changes))

    def cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = tradier_report.main(args)
        self.assertNotIn(TOKEN, out.getvalue() + err.getvalue())
        return code, out.getvalue(), err.getvalue()


class AcquisitionTests(OfflineCase):
    def test_exact_production_get_and_parameters(self):
        response = self.response()
        history = tradier.fetch_history(TOKEN, **KW)
        request = self.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(urlsplit(request.full_url).netloc, "api.tradier.com")
        self.assertEqual(urlsplit(request.full_url).path, "/v1/markets/history")
        self.assertEqual(parse_qs(urlsplit(request.full_url).query), dict(
            symbol=["CLX"], interval=["daily"], start=[str(START)], end=[str(END)]))
        self.assertEqual(request.get_header("Authorization"), "Bearer " + TOKEN)
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertIsNone(request.data)
        self.assertNotIn(TOKEN, request.full_url)
        self.assertEqual(self.open.call_args.kwargs, {"timeout": 15})
        self.assertEqual(self.open.call_count, 1)
        response.read.assert_called_once_with(tradier.MAX_RESPONSE_BYTES + 1)
        self.assertEqual(len(history.bars), 24)
        self.keychain.assert_not_called()

    def test_sandbox_host_is_explicit(self):
        self.response()
        history = tradier.fetch_history(TOKEN, **(KW | dict(environment="sandbox")))
        self.assertEqual(urlsplit(self.open.call_args.args[0].full_url).netloc, "sandbox.tradier.com")
        self.assertEqual(history.environment, "sandbox")

    def test_no_redirect_or_proxy(self):
        self.response()
        tradier.fetch_history(TOKEN, **KW)
        handlers = self.build.call_args.args
        self.assertEqual(handlers[0].proxies, {})
        self.assertIsNone(handlers[1].redirect_request(None, None, 302, "", {}, "https://evil.invalid"))

    def test_bad_request_configuration_fails_before_http(self):
        for changes in (dict(environment="other"), dict(symbol="CLX&token=" + TOKEN),
                        dict(start=END, end=START), dict(start="2026-01-05"),
                        dict(end=START + timedelta(days=367)), dict(completed_through=START - timedelta(days=1))):
            with self.subTest(changes=changes), self.assertRaises(tradier.TradierError):
                tradier.fetch_history(TOKEN, **(KW | changes))
        self.build.assert_not_called()

    def test_authentication_and_entitlement_errors_are_safe(self):
        for status in (401, 403):
            self.open.side_effect = HTTPError("https://fixed.invalid", status, TOKEN, {}, io.BytesIO(TOKEN.encode()))
            with self.assertRaisesRegex(tradier.TradierError, "authentication/entitlement") as caught:
                tradier.fetch_history(TOKEN, **KW)
            self.assertNotIn(TOKEN, str(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__)

    def test_both_rate_limit_status_conventions(self):
        for status, body in ((429, TOKEN), (400, "Quota Violation: Expires 123 " + TOKEN)):
            self.open.side_effect = HTTPError("https://fixed.invalid", status, TOKEN, {}, io.BytesIO(body.encode()))
            with self.assertRaisesRegex(tradier.TradierError, "rate limit"):
                tradier.fetch_history(TOKEN, **KW)

    def test_http_failures_do_not_echo_response(self):
        for status in (400, 302, 404, 500, 503):
            self.open.side_effect = HTTPError("https://fixed.invalid", status, TOKEN, {}, io.BytesIO(TOKEN.encode()))
            with self.assertRaises(tradier.TradierError) as caught:
                tradier.fetch_history(TOKEN, **KW)
            self.assertNotIn(TOKEN, str(caught.exception))

    def test_network_errors_and_timeout_are_safe(self):
        for error in (TimeoutError(TOKEN), URLError(TOKEN), OSError(TOKEN)):
            self.open.side_effect = error
            with self.assertRaisesRegex(tradier.TradierError, "network/TLS") as caught:
                tradier.fetch_history(TOKEN, **KW)
            self.assertNotIn(TOKEN, str(caught.exception))

    def test_malformed_json(self):
        response = self.response()
        for raw in (TOKEN.encode(), b'\xff', b'{"history":'):
            response.read.return_value = raw
            with self.assertRaisesRegex(tradier.TradierError, "JSON") as caught:
                tradier.fetch_history(TOKEN, **KW)
            self.assertNotIn(TOKEN, str(caught.exception))

    def test_oversized_and_unexpected_success_status(self):
        response = self.response()
        response.read.return_value = b"x" * (tradier.MAX_RESPONSE_BYTES + 1)
        with self.assertRaises(tradier.TradierError):
            tradier.fetch_history(TOKEN, **KW)
        response.read.return_value = b'{}'
        response.status = 204
        with self.assertRaises(tradier.TradierError):
            tradier.fetch_history(TOKEN, **KW)


class NormalizationTests(OfflineCase):
    def test_sorting_is_explicit_and_does_not_mutate_response(self):
        payload = fixture()
        payload["history"]["day"].reverse()
        first = payload["history"]["day"][0]["date"]
        history = self.normalize(payload)
        self.assertTrue(history.reordered)
        self.assertEqual(history.bars[0].session, START)
        self.assertEqual(payload["history"]["day"][0]["date"], first)
        self.assertEqual(history.volumes, (1000,) * 24)

    def test_singleton_object(self):
        payload = fixture([50])
        payload["history"]["day"] = payload["history"]["day"][0]
        self.assertEqual(len(self.normalize(payload).bars), 1)

    def test_duplicates_rejected(self):
        payload = fixture()
        payload["history"]["day"].append(payload["history"]["day"][0])
        with self.assertRaisesRegex(tradier.TradierError, "Duplicate"):
            self.normalize(payload)

    def test_empty_and_wrong_shapes(self):
        for payload in (None, [], {}, {"history": None}, {"history": {}},
                        {"history": {"day": None}}, {"history": {"day": []}},
                        {"history": {"day": [None]}}, {"history": {"day": "missing"}}):
            with self.subTest(payload=payload), self.assertRaises(tradier.TradierError):
                tradier.normalize_history(payload, **KW)

    def test_each_required_field(self):
        for key in ("date", "open", "high", "low", "close"):
            payload = fixture()
            del payload["history"]["day"][0][key]
            with self.subTest(key=key), self.assertRaises(tradier.TradierError):
                self.normalize(payload)

    def test_invalid_prices_nonfinite_and_structure(self):
        for field in ("open", "high", "low", "close"):
            for value in (None, True, "60", 0, -1, float("nan"), float("inf"), 10**1000):
                payload = fixture()
                payload["history"]["day"][0][field] = value
                with self.subTest(field=field, kind=type(value).__name__), self.assertRaises(tradier.TradierError):
                    self.normalize(payload)
        for change in (dict(close=111), dict(open=9), dict(high=5), dict(low=120)):
            payload = fixture()
            payload["history"]["day"][0].update(change)
            with self.assertRaises(tradier.TradierError):
                self.normalize(payload)

    def test_volume_invalid_values(self):
        for value in (-1, True, "100", float("nan"), float("inf"), 10**1000):
            payload = fixture()
            payload["history"]["day"][0]["volume"] = value
            with self.subTest(kind=type(value).__name__), self.assertRaises(tradier.TradierError):
                self.normalize(payload)

    def test_optional_and_zero_volume(self):
        payload = fixture()
        del payload["history"]["day"][0]["volume"]
        payload["history"]["day"][1]["volume"] = None
        payload["history"]["day"][2]["volume"] = 0
        self.assertEqual(self.normalize(payload).volumes[:3], (None, None, 0))

    def test_bad_session_dates(self):
        for value in (None, "2026-1-05", "2026-02-30", "2026-01-10", "2025-12-31", "2026-03-02"):
            payload = fixture()
            payload["history"]["day"][0]["date"] = value
            with self.subTest(value=value), self.assertRaises(tradier.TradierError):
                self.normalize(payload)

    def test_missing_weekday_not_silently_filled_or_called_holiday(self):
        payload = fixture()
        del payload["history"]["day"][3]
        history = self.normalize(payload)
        self.assertEqual(len(history.bars), 23)
        report = tradier_report.history_report(history)
        self.assertIn("UNVERIFIED", report["continuity"])

    def test_exclude_uncertified_bars_before_calculation(self):
        payload = fixture()
        cutoff = date.fromisoformat(payload["history"]["day"][-2]["date"])
        history = self.normalize(payload, completed_through=cutoff)
        self.assertEqual(len(history.bars), 23)
        self.assertEqual(len(history.excluded_sessions), 1)
        report = tradier_report.history_report(history)
        self.assertEqual(report["returned_bars"], 24)
        self.assertEqual(report["valid_bars"], 23)
        self.assertEqual(report["last_returned_session"], payload["history"]["day"][-1]["date"])
        self.assertEqual(history.bars[-1].session, cutoff)
        self.assertFalse(tradier_report.history_report(history)["latest"]["crossed_below_20"])

    def test_invalid_excluded_rows_still_fail_closed(self):
        payload = fixture()
        payload["history"]["day"][-1]["close"] = None
        with self.assertRaises(tradier.TradierError):
            self.normalize(payload, completed_through=START)

    def test_no_completed_rows(self):
        payload = fixture([50])
        payload["history"]["day"][0]["date"] = "2026-01-06"
        with self.assertRaisesRegex(tradier.TradierError, "No observations"):
            self.normalize(payload, completed_through=START)


class ReportTests(OfflineCase):
    def test_real_talib_integration_against_independent_reference(self):
        history = self.normalize()
        report = tradier_report.history_report(history)
        self.assertEqual(report["latest"]["close"], 10)
        self.assertEqual(report["latest"]["k"], 0)
        self.assertAlmostEqual(report["latest"]["d"], 40 / 3, delta=1e-12)
        self.assertTrue(report["latest"]["crossed_below_20"])
        crossings = report["historical_crossings"]
        self.assertEqual(len(crossings), 2)
        self.assertEqual([(item["previous_k"], item["k"]) for item in crossings], [(40, 10), (20, 0)])
        self.assertEqual(report, tradier_report.history_report(history))
        self.assertIn("UNVERIFIED", report["continuity"])
        json.dumps(report, allow_nan=False)

    def test_no_crossing_is_distinct_from_insufficient_history(self):
        report = tradier_report.history_report(self.normalize(fixture([50] * 20)))
        self.assertEqual(report["historical_crossings"], [])
        self.assertEqual(report["latest"]["k"], 50)
        short = tradier_report.history_report(self.normalize(fixture([50])))
        self.assertIsNone(short["latest"]["k"])
        self.assertEqual(short["status"], "degraded")

    def test_stale_cutoff_is_explicit(self):
        report = tradier_report.history_report(self.normalize())
        self.assertTrue(report["stale_relative_to_cutoff"])
        self.assertEqual(report["status"], "degraded")

    def args(self):
        return ["--environment", "production", "--start", str(START), "--end", str(END),
                "--completed-through", str(END)]

    def test_no_fetch_reads_no_credentials_or_network(self):
        code, out, _ = self.cli(self.args())
        self.assertEqual(code, 2)
        self.assertIn("No data fetched", out)
        self.keychain.assert_not_called()
        self.build.assert_not_called()

    def test_cli_runs_only_three_symbols(self):
        payload = fixture()
        payload["history"]["day"][-1]["date"] = str(END)
        history = self.normalize(payload)
        with patch("market_sentinel.tradier_report.load_token", return_value=TOKEN), \
             patch("market_sentinel.tradier_report.fetch_history",
                   side_effect=lambda token, **kwargs: tradier.normalize_history(payload, **kwargs)) as fetch:
            code, out, _ = self.cli(self.args() + ["--fetch"])
        self.assertEqual(code, 0)
        self.assertEqual([call.kwargs["symbol"] for call in fetch.call_args_list], ["CLX", "CVX", "MCD"])
        self.assertIn("not a trading recommendation", json.loads(out)["label"])
        self.assertEqual([result["symbol"] for result in json.loads(out)["results"]], ["CLX", "CVX", "MCD"])

    def test_partial_failure_stops_and_marks_unattempted(self):
        with patch("market_sentinel.tradier_report.load_token", return_value=TOKEN), \
             patch("market_sentinel.tradier_report.fetch_history", side_effect=tradier.TradierError("Safe failure")) as fetch:
            code, out, _ = self.cli(self.args() + ["--fetch"])
        self.assertEqual(code, 1)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(len(json.loads(out)["results"]), 3)
        self.assertIn("not attempted", out)

    def test_unexpected_reporting_error_does_not_echo_credentials(self):
        with patch("market_sentinel.tradier_report.load_token", return_value=TOKEN), \
             patch("market_sentinel.tradier_report.fetch_history", side_effect=RuntimeError(TOKEN)):
            code, _, _ = self.cli(self.args() + ["--fetch"])
        self.assertEqual(code, 1)

    def test_current_session_range_rejected_before_credentials(self):
        with patch("market_sentinel.tradier_report.datetime") as clock:
            clock.now.return_value = datetime(2026, 2, 27, 23, tzinfo=timezone.utc)
            code, _, _ = self.cli(self.args() + ["--fetch"])
        self.assertEqual(code, 2)
        self.keychain.assert_not_called()
        self.build.assert_not_called()

    def test_unexpected_credential_error_is_sanitized(self):
        with patch("market_sentinel.tradier_report.load_token", side_effect=RuntimeError(TOKEN)):
            code, _, err = self.cli(self.args() + ["--fetch"])
        self.assertEqual(code, 1)
        self.assertIn("details suppressed", err)
        self.build.assert_not_called()

    def test_weekend_cutoff_rejected_before_credentials(self):
        args = ["--environment", "production", "--start", str(START), "--end", "2026-02-28",
                "--completed-through", "2026-02-28", "--fetch"]
        code, _, _ = self.cli(args)
        self.assertEqual(code, 2)
        self.keychain.assert_not_called()
        self.build.assert_not_called()

    def test_setup_failure_is_nonzero_and_reads_no_http(self):
        with patch("market_sentinel.tradier_report.load_token", side_effect=tradier.TradierError("Unavailable")):
            code, _, err = self.cli(self.args() + ["--fetch"])
        self.assertEqual(code, 1)
        self.assertIn("Unavailable", err)
        self.build.assert_not_called()

    def test_bad_argument_never_echoes_credential(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), self.assertRaises(SystemExit) as caught:
            tradier_report.main(["--start", TOKEN])
        self.assertEqual(caught.exception.code, 2)
        self.assertNotIn(TOKEN, out.getvalue() + err.getvalue())


class CredentialTests(OfflineCase):
    def test_environment_handoff_is_portable(self):
        with patch.dict("os.environ", {"TRADIER_TOKEN": TOKEN}), patch("sys.platform", "linux"):
            self.assertEqual(tradier.load_token("production"), TOKEN)
        self.keychain.assert_not_called()

    def test_environment_specific_keychain_item(self):
        self.keychain.side_effect = None
        self.keychain.return_value = Mock(returncode=0, stdout=TOKEN + "\n")
        with patch("sys.platform", "darwin"):
            for environment in ("production", "sandbox"):
                self.assertEqual(tradier.load_token(environment), TOKEN)
                self.assertEqual(self.keychain.call_args.args[0], ["/usr/bin/security", "find-generic-password",
                    "-s", "market-sentinel.tradier", "-a", environment + "-token", "-w"])
                self.assertEqual(self.keychain.call_args.kwargs["timeout"], 15)

    def test_bad_tokens_fail_without_exposure(self):
        for token in ("", "Bearer " + TOKEN, TOKEN + "\nInjected: bad", TOKEN + " ", "a" * 4097):
            with patch.dict("os.environ", {"TRADIER_TOKEN": token}):
                with self.assertRaises(tradier.TradierError) as caught:
                    tradier.load_token("production")
                self.assertNotIn(TOKEN, str(caught.exception))
        self.keychain.assert_not_called()

    def test_missing_keychain_and_timeouts_are_safe(self):
        with patch("sys.platform", "darwin"):
            self.keychain.side_effect = None
            self.keychain.return_value = Mock(returncode=44, stdout=TOKEN, stderr=TOKEN)
            with self.assertRaises(tradier.TradierError) as caught:
                tradier.load_token("production")
            self.assertNotIn(TOKEN, str(caught.exception))
            self.keychain.side_effect = subprocess.TimeoutExpired(TOKEN, 15, output=TOKEN)
            with self.assertRaises(tradier.TradierError) as caught:
                tradier.load_token("production")
            self.assertNotIn(TOKEN, str(caught.exception))

    def test_no_keychain_on_other_platforms(self):
        with patch("sys.platform", "linux"), self.assertRaises(tradier.TradierError):
            tradier.load_token("production")
        self.keychain.assert_not_called()


if __name__ == "__main__":
    unittest.main()
