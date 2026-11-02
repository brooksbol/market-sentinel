"""Offline full-universe formatting, length and one-message transport contracts."""

import copy
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode
import io

from market_sentinel import daily_report, pushover
from market_sentinel.universe import SYMBOLS

TOKEN, USER = "T"*30, "U"*30
SESSION = "2026-10-30"


def screening():
    # Synthetic evaluated rows: no market acquisition or exchange-calendar claim.
    results = [dict(symbol=symbol, status="calculated", last_session=SESSION,
                    completed_through=SESSION, stale_relative_to_cutoff=False,
                    latest=dict(close=100+i, k=30+i, d=20+i, crossing_available=True, crossed_below_20=False),
                    warnings=[], warning_count=0) for i, symbol in enumerate(SYMBOLS)]
    return dict(summary=dict(completed_session=SESSION, configured_symbols=19,
                 acquired_symbols=19, evaluated_symbols=19, usable_latest_symbols=19,
                 new_downward_crossings=0, warning_count=0, status="complete"), results=results)


def row_lines(body):
    return [line for line in body.splitlines() if line.split() and line.split()[0] in SYMBOLS]


def warn(report, index=0, session="2026-04-21", excluded=False):
    result = report["results"][index]
    result["warnings"].append(dict(session=session, code="close_below_low", value=9, low=10, high=110,
                                   excluded_from_calculation=excluded))
    result["warning_count"] += 1
    result["status"] = "calculated_with_warnings"
    report["summary"]["warning_count"] += 1
    report["summary"]["status"] = "complete_with_warnings"


class FormatTests(unittest.TestCase):
    def test_all_nineteen_symbols_once_including_above_twenty(self):
        body = daily_report.format_daily_report(screening())
        symbols = [line.split()[0] for line in row_lines(body)]
        self.assertEqual(len(symbols), 19)
        self.assertEqual(set(symbols), set(SYMBOLS))
        self.assertEqual(len(symbols), len(set(symbols)))
        self.assertIn("19/19 | Stoch 14,3,3", body)
        self.assertNotIn(daily_report.TITLE, body)

    def test_full_precision_sort_precedes_display_rounding(self):
        report = screening()
        report["results"][0]["latest"]["k"] = 5.049  # CLX
        report["results"][1]["latest"]["k"] = 5.041  # O, same displayed 5.0
        rows = row_lines(daily_report.format_daily_report(report))
        self.assertEqual([line.split()[0] for line in rows[:2]], ["O", "CLX"])
        self.assertEqual([line.split()[2] for line in rows[:2]], ["5.0", "5.0"])

    def test_symbol_breaks_exact_ties_independent_of_input_order(self):
        report = screening()
        for row in report["results"]:
            row["latest"]["k"] = 50
        first = daily_report.format_daily_report(report)
        report["results"].reverse()
        self.assertEqual(first, daily_report.format_daily_report(report))
        self.assertEqual([line.split()[0] for line in row_lines(first)], sorted(SYMBOLS))

    def test_known_close_k_d_display_and_column_alignment(self):
        report = screening()
        target = next(row for row in report["results"] if row["symbol"] == "ADM")
        target["latest"].update(close=76.91, k=7.006803452414438, d=5.795976047115096)
        target = next(row for row in report["results"] if row["symbol"] == "CAT")
        target["latest"].update(close=622.75, k=12.693158708717277, d=17.037625449216605)
        rows = row_lines(daily_report.format_daily_report(report))
        self.assertEqual(rows[0].split(), ["ADM", "76.91", "7.0", "5.8"])
        self.assertEqual(rows[1].split(), ["CAT", "622.75", "12.7", "17.0"])
        self.assertEqual(len({len(line) for line in rows}), 1)

    def test_crossing_and_oversold_are_distinct_full_precision_counts(self):
        report = screening()
        report["results"][0]["latest"].update(k=19.99999999, crossed_below_20=True)
        report["results"][1]["latest"].update(k=10, crossed_below_20=False)
        report["results"][2]["latest"].update(k=20, crossed_below_20=False)
        report["summary"]["new_downward_crossings"] = 1
        body = daily_report.format_daily_report(report)
        self.assertIn("Crossings: 1 | Below 20: 2", body)
        self.assertIn("20.0", body)  # Rounded presentation never changes the below count.

    def test_complete_demo_fits_and_explicitly_is_not_scheduled(self):
        body = daily_report.format_daily_report(screening(), demonstration=True)
        self.assertLessEqual(len(body), 1024)
        self.assertEqual(len(body.encode("utf-8")), len(body))
        self.assertIn("DEMONSTRATION", body)
        self.assertIn("Not a live scheduled result", body)
        self.assertEqual(len(row_lines(body)), 19)

    def test_incomplete_summary_cannot_claim_success(self):
        for field in ("configured_symbols", "acquired_symbols", "evaluated_symbols", "usable_latest_symbols"):
            report = screening(); report["summary"][field] = 18
            with self.subTest(field=field), self.assertRaises(daily_report.ReportError):
                daily_report.format_daily_report(report)

    def test_missing_duplicate_unknown_and_extra_rows_rejected(self):
        for change in ("missing", "duplicate", "unknown", "extra"):
            report = screening()
            if change == "missing": report["results"].pop()
            if change == "duplicate": report["results"][-1] = report["results"][0]
            if change == "unknown": report["results"][-1]["symbol"] = "UNKNOWN"
            if change == "extra": report["results"].append(copy.deepcopy(report["results"][0]))
            with self.subTest(change=change), self.assertRaises(daily_report.ReportError):
                daily_report.format_daily_report(report)

    def test_failed_unavailable_and_stale_rows_rejected(self):
        for change in (dict(status="failed"), dict(status="degraded"), dict(stale_relative_to_cutoff=True)):
            report = screening(); report["results"][0].update(change)
            with self.assertRaises(daily_report.ReportError): daily_report.format_daily_report(report)

    def test_missing_invalid_and_nonfinite_numerical_values_rejected(self):
        for field in ("close", "k", "d"):
            for value in (None, float("nan"), float("inf"), True, "20"):
                report = screening(); report["results"][0]["latest"][field] = value
                with self.subTest(field=field, kind=type(value).__name__), self.assertRaises(daily_report.ReportError):
                    daily_report.format_daily_report(report)
        report = screening(); report["results"][0]["latest"]["close"] = 0
        with self.assertRaises(daily_report.ReportError): daily_report.format_daily_report(report)

    def test_finite_warned_indicators_outside_normal_range_are_preserved(self):
        report = screening(); warn(report)
        report["results"][0]["latest"].update(k=-2.5, d=101.2)
        self.assertIn("-2.5 101.2", daily_report.format_daily_report(report))

    def test_unavailable_crossing_is_not_zero(self):
        for value in (None, 0, "false"):
            report = screening(); report["results"][0]["latest"]["crossed_below_20"] = value
            with self.assertRaises(daily_report.ReportError): daily_report.format_daily_report(report)
        report = screening(); report["results"][0]["latest"]["crossing_available"] = False
        with self.assertRaises(daily_report.ReportError): daily_report.format_daily_report(report)

    def test_mixed_dates_and_noncanonical_dates_rejected(self):
        for field in ("last_session", "completed_through"):
            report = screening(); report["results"][0][field] = "2026-10-29"
            with self.assertRaises(daily_report.ReportError): daily_report.format_daily_report(report)
        for day in (None, "20261030", "2026-02-30"):
            report = screening(); report["summary"]["completed_session"] = day
            with self.assertRaises(daily_report.ReportError): daily_report.format_daily_report(report)

    def test_warnings_distinguish_sample_from_report_session(self):
        report = screening(); warn(report); warn(report, 1, SESSION)
        self.assertIn("Warnings: 2 sample; 1 on session", daily_report.format_daily_report(report))
        report = screening()
        for _ in range(13): warn(report)
        self.assertIn("Warnings: 13 sample; 0 on session", daily_report.format_daily_report(report))

    def test_excluded_warning_is_never_called_report_session_warning(self):
        report = screening(); warn(report, session="2026-11-02", excluded=True)
        self.assertIn("Warnings: 1 sample; 0 on session", daily_report.format_daily_report(report))

    def test_inconsistent_counts_flags_and_warning_scope_fail(self):
        report = screening(); report["summary"]["new_downward_crossings"] = 1
        with self.assertRaises(daily_report.ReportError): daily_report.format_daily_report(report)
        report = screening(); report["results"][0]["latest"]["crossed_below_20"] = True
        with self.assertRaises(daily_report.ReportError): daily_report.format_daily_report(report)
        report = screening(); warn(report); report["summary"]["warning_count"] = 0
        with self.assertRaises(daily_report.ReportError): daily_report.format_daily_report(report)
        report = screening(); warn(report, excluded=True)
        with self.assertRaises(daily_report.ReportError): daily_report.format_daily_report(report)

    def test_oversize_is_rejected_before_transport_without_dropping_rows(self):
        report = screening()
        for row in report["results"]: row["latest"]["close"] = 1e100
        original = copy.deepcopy(report)
        with patch("market_sentinel.pushover.build_opener") as build, self.assertRaises(daily_report.ReportError):
            daily_report.send_daily_report(TOKEN, USER, report)
        build.assert_not_called()
        self.assertEqual(report, original)

    def test_format_is_pure_deterministic_and_does_not_mutate_input(self):
        report = screening(); original = copy.deepcopy(report)
        with patch("builtins.open", side_effect=AssertionError("No files")), \
             patch("subprocess.run", side_effect=AssertionError("No credentials")), \
             patch("socket.create_connection", side_effect=AssertionError("No network")):
            first = daily_report.format_daily_report(report)
            self.assertEqual(first, daily_report.format_daily_report(report))
        self.assertEqual(report, original)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.build = patch("market_sentinel.pushover.build_opener").start()
        response = self.build.return_value.open.return_value.__enter__.return_value
        response.status = 200; response.read.return_value = b'{"status":1}'

    def test_one_complete_monospace_message_with_no_delivery_override(self):
        report = screening()
        daily_report.send_daily_report(TOKEN, USER, report, demonstration=True)
        self.assertEqual(self.build.return_value.open.call_count, 1)
        request = self.build.return_value.open.call_args.args[0]
        fields = parse_qs(request.data.decode())
        self.assertEqual(request.full_url, pushover.ENDPOINT)
        self.assertEqual(fields, dict(token=[TOKEN], user=[USER], title=[daily_report.TITLE+" TEST"],
            message=[daily_report.format_daily_report(report, demonstration=True)], monospace=["1"]))
        self.assertNotIn("html", fields)
        self.assertNotIn("priority", fields)
        self.assertNotIn("sound", fields)

    def test_normal_report_title_is_distinct_from_demo(self):
        daily_report.send_daily_report(TOKEN, USER, screening())
        self.assertEqual(parse_qs(self.build.return_value.open.call_args.args[0].data.decode())["title"], [daily_report.TITLE])

    def test_incomplete_report_never_sends_partial_or_extra_message(self):
        report = screening(); report["results"].pop()
        with self.assertRaises(daily_report.ReportError): daily_report.send_daily_report(TOKEN, USER, report)
        self.build.assert_not_called()

    def test_provider_rejection_is_safe_and_never_retried(self):
        self.build.return_value.open.side_effect = HTTPError(pushover.ENDPOINT, 400, TOKEN, {}, io.BytesIO(USER.encode()))
        with self.assertRaises(pushover.PushError) as caught: daily_report.send_daily_report(TOKEN, USER, screening())
        self.assertNotIn(TOKEN, str(caught.exception)); self.assertNotIn(USER, str(caught.exception))
        self.assertEqual(self.build.return_value.open.call_count, 1)

    def test_ambiguous_timeout_is_safe_and_never_retried(self):
        self.build.return_value.open.side_effect = TimeoutError(TOKEN+USER)
        with self.assertRaisesRegex(pushover.PushError, "acceptance is unknown") as caught:
            daily_report.send_daily_report(TOKEN, USER, screening())
        self.assertNotIn(TOKEN, str(caught.exception)); self.assertNotIn(USER, str(caught.exception))
        self.assertEqual(self.build.return_value.open.call_count, 1)

    def test_unicode_limits_count_characters_not_utf8_or_post_bytes(self):
        message = "😀"*1024
        pushover._send_message(TOKEN, USER, "Unicode", message, monospace=True)
        request = self.build.return_value.open.call_args.args[0]
        self.assertEqual(parse_qs(request.data.decode())["message"], [message])
        self.assertEqual(len(message), 1024)
        self.assertEqual(len(message.encode("utf-8")), 4096)
        self.assertGreater(len(request.data), 4096)

    def test_unexpected_transport_failure_is_sanitized(self):
        self.build.side_effect = RuntimeError(TOKEN+USER)
        with self.assertRaises(pushover.PushError) as caught:
            daily_report.send_daily_report(TOKEN, USER, screening())
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertNotIn(USER, str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertEqual(self.build.call_count, 1)

    def test_unicode_oversize_surrogate_and_title_fail_before_http(self):
        for title, message in (("t", "😀"*1025), ("t", "e\u0301"*513), ("t", "\ud800"), ("t"*251, "body")):
            with self.assertRaises(pushover.PushError): pushover._send_message(TOKEN, USER, title, message)
        self.build.assert_not_called()

    def test_percent_encoding_does_not_consume_character_budget(self):
        message = "&"*1024
        pushover._send_message(TOKEN, USER, "t", message)
        self.assertEqual(parse_qs(self.build.return_value.open.call_args.args[0].data.decode())["message"], [message])
        self.assertGreater(len(urlencode({"message": message})), 1024)


if __name__ == "__main__":
    unittest.main()
