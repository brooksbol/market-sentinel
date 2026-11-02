"""Attention-first policy. Public retained facts plus offline synthetic fixtures.

Three OHLC rows below were observed in protected production evidence on
2026-11-02, at the pre-policy commit 16413cb. No credential or live request is
needed. All surrounding bars are explicitly synthetic, not exchange history.
"""

import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from unittest.mock import patch

import numpy as np

from market_sentinel.stochastic import DailyOHLC, crossed_below_20, stochastic_14_3_3
from market_sentinel import tradier, tradier_report

START = date(2026, 1, 5)
END = date(2026, 2, 27)
PARAMS = dict(symbol="CLX", environment="production", start=START, end=END, completed_through=END)
SYNTHETIC_TOKEN = "synthetic-token"
OBSERVED = (
    ("CLX", dict(date="2026-04-21", open=102.31, high=102.6, low=99.36, close=98.37, volume=3000855)),
    ("MCD", dict(date="2026-03-02", open=341.06, high=341.75, low=334.4101, close=332.96, volume=4555391)),
    ("MCD", dict(date="2026-08-31", open=265.0, high=266.07, low=263.385, close=261.68, volume=5244145)),
)


def payload(close=40, opening=60):
    rows = []
    day = START
    for _ in range(20):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        rows.append(dict(date=str(day), open=opening, high=110, low=10, close=40, volume=100))
        day += timedelta(days=1)
    rows[-1].update(date=str(END), close=close)
    return {"history": {"day": rows}}


def history(data):
    return tradier.normalize_history(data, **PARAMS)


class PolicyTests(unittest.TestCase):
    def test_all_three_retained_anomalies_accepted_unchanged_and_calculated(self):
        for symbol, observed in OBSERVED:
            with self.subTest(symbol=symbol, day=observed["date"]):
                end = date.fromisoformat(observed["date"])
                rows = []
                day = end - timedelta(days=40)
                while day < end:
                    if day.weekday() < 5:
                        rows.append(dict(observed, date=str(day), close=observed["open"]))
                    day += timedelta(days=1)
                rows.append(dict(observed))
                original = json.dumps(rows)
                result = tradier.normalize_history({"history": {"day": rows}}, symbol=symbol,
                    environment="production", start=end-timedelta(days=40), end=end, completed_through=end)
                self.assertEqual(json.dumps(rows), original)
                self.assertEqual(len(result.warnings), 1)
                self.assertEqual((result.warnings[0].session, result.warnings[0].code), (end, "close_below_low"))
                for key in ("open", "high", "low", "close"):
                    self.assertEqual(getattr(result.bars[-1], key), observed[key])
                self.assertEqual(result.volumes[-1], observed["volume"])
                report = tradier_report.history_report(result)
                self.assertIsNotNone(report["latest"]["k"])
                self.assertIsNotNone(report["latest"]["d"])
                self.assertEqual(report["warning_count"], 1)
                self.assertEqual(report["status"], "calculated_with_warnings")

    def test_close_above_high_and_open_outside_each_warn(self):
        result = history(payload(close=111, opening=9))
        self.assertEqual(len(result.warnings), 21)
        report = tradier_report.history_report(result)
        self.assertEqual(report["warning_counts"], {"open_outside_range": 20, "close_above_high": 1})
        self.assertEqual(report["warnings"][-2]["code"], "close_above_high")
        self.assertEqual(report["warnings"][-2]["session"], str(END))
        self.assertEqual(report["warnings"][-2]["value"], 111)
        self.assertEqual(result.bars[-1].open, 9)
        self.assertEqual(result.bars[-1].close, 111)

    def test_open_above_high_is_also_a_warning(self):
        result = history(payload(opening=111))
        self.assertEqual(len(result.warnings), 20)
        self.assertTrue(all(w.code == "open_outside_range" for w in result.warnings))

    def test_range_boundaries_are_not_warnings(self):
        for opening, close in ((10, 110), (110, 10)):
            result = history(payload(close=close, opening=opening))
            self.assertEqual(result.warnings, ())

    def test_warned_close_can_create_unchanged_threshold_crossing(self):
        result = history(payload(close=1))
        points = stochastic_14_3_3(result.bars)
        self.assertEqual(points[-1].raw_k, -9)
        self.assertEqual(points[-2].k, 30)
        self.assertEqual(points[-1].k, 17)  # (30+30-9)/3, no clamping or repair.
        self.assertAlmostEqual(points[-1].d, 77/3, delta=1e-12)
        self.assertTrue(points[-1].crossed_below_20)
        self.assertEqual(points[-1].warnings, result.warnings)
        report = tradier_report.history_report(result)
        self.assertTrue(report["latest"]["crossed_below_20"])
        self.assertEqual(len(report["historical_crossings"]), 1)
        self.assertEqual(report["warning_count"], 1)

    def test_finite_indicators_outside_zero_to_one_hundred_remain_comparable(self):
        for close, expected in ((1, -9), (120, 110)):
            bars = [DailyOHLC(START+timedelta(days=i), 60, 110, 10, close) for i in range(20)]
            point = stochastic_14_3_3(bars)[-1]
            self.assertAlmostEqual(point.k, expected, delta=1e-12)
            self.assertAlmostEqual(point.d, expected, delta=1e-12)
            self.assertEqual(len(point.warnings), 1)
        self.assertTrue(crossed_below_20(101, -1))
        self.assertFalse(crossed_below_20(-1, -2))
        self.assertTrue(crossed_below_20(20, 19.999999999))
        self.assertFalse(crossed_below_20(21, 20))

    def test_missing_nonfinite_nonpositive_and_inverted_ranges_still_fail(self):
        for change in (dict(close=None), dict(open=float("nan")), dict(close=float("inf")),
                       dict(close=0), dict(open=-1), dict(high=9), dict(low=-1)):
            data = payload()
            data["history"]["day"][-1].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(tradier.TradierError, "Structurally invalid OHLC"):
                history(data)

    def test_order_and_duplicates_still_fail_even_when_prices_only_warn(self):
        for duplicate in (True, False):
            data = payload(close=1)
            if duplicate:
                data["history"]["day"].append(data["history"]["day"][-1])
            else:
                data["history"]["day"].reverse()
            with self.assertRaises(tradier.TradierError):
                history(data)

    def test_excluded_observation_warning_is_visible_without_affecting_indicator(self):
        data = payload(close=1)
        cutoff = date.fromisoformat(data["history"]["day"][-2]["date"])
        result = tradier.normalize_history(data, **(PARAMS | dict(completed_through=cutoff)))
        report = tradier_report.history_report(result)
        self.assertEqual(report["warning_count"], 1)
        self.assertTrue(report["warnings"][0]["excluded_from_calculation"])
        self.assertEqual(report["latest"]["k"], 30)
        self.assertFalse(report["latest"]["crossed_below_20"])

    def test_nonfinite_library_outputs_are_visible_as_unavailable(self):
        result = history(payload(close=1))
        k = np.full(20, 30.); d = np.full(20, 30.)
        k[-1] = np.inf; d[-1] = np.nan
        with patch("market_sentinel.stochastic.talib.STOCH", return_value=(k, d)):
            report = tradier_report.history_report(result)
        self.assertIsNone(report["latest"]["k"])
        self.assertIsNone(report["latest"]["d"])
        self.assertIsNone(report["latest"]["crossed_below_20"])
        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["unavailable_after_warmup"], [dict(session=str(END), k=None, d=None)])
        self.assertEqual(report["warning_count"], 1)
        json.dumps(report, allow_nan=False)

    def test_informational_raw_overflow_does_not_suppress_finite_library_outputs(self):
        bars = [DailyOHLC(START+timedelta(days=i), 1, 2, 1, 1e308) for i in range(20)]
        with patch("market_sentinel.stochastic.talib.STOCH", return_value=(np.full(20, 30.), np.full(20, 40.))):
            point = stochastic_14_3_3(bars)[-1]
        self.assertIsNone(point.raw_k)
        self.assertEqual((point.k, point.d), (30, 40))
        self.assertEqual(len(point.warnings), 1)

    def test_arithmetic_overflow_does_not_fabricate_indicator_values(self):
        bars = [DailyOHLC(START+timedelta(days=i), 1, 2, 1, 1e308) for i in range(20)]
        with np.errstate(over="ignore", invalid="ignore"):
            point = stochastic_14_3_3(bars)[-1]
        self.assertIsNone(point.raw_k)
        self.assertIsNone(point.k)
        self.assertIsNone(point.d)
        self.assertFalse(point.crossed_below_20)
        self.assertEqual(len(point.warnings), 1)


class BatchTests(unittest.TestCase):
    def run_report(self, fetch):
        out = io.StringIO()
        with patch("market_sentinel.tradier_report.load_token", return_value=SYNTHETIC_TOKEN), \
             patch("market_sentinel.tradier_report.fetch_history", side_effect=fetch), redirect_stdout(out):
            code = tradier_report.main(["--environment", "production", "--start", str(START),
                "--end", str(END), "--completed-through", str(END), "--fetch"])
        self.assertNotIn(SYNTHETIC_TOKEN, out.getvalue())
        return code, json.loads(out.getvalue())

    def test_warned_nineteen_symbol_run_completes_and_counts_crossings(self):
        def fetch(token, **kwargs):
            return tradier.normalize_history(payload(close=1), **kwargs)
        code, report = self.run_report(fetch)
        self.assertEqual(code, 0)
        self.assertEqual(report["summary"]["status"], "complete_with_warnings")
        self.assertEqual(report["summary"]["evaluated_symbols"], 19)
        self.assertEqual(report["summary"]["acquired_symbols"], 19)
        self.assertEqual(report["summary"]["warning_count"], 19)
        self.assertEqual(report["summary"]["new_downward_crossings"], 19)

    def test_quiet_complete_is_distinct_from_one_failed_symbol(self):
        for fail_one in (False, True):
            calls = []
            def fetch(token, **kwargs):
                calls.append(kwargs["symbol"])
                if fail_one and kwargs["symbol"] == "MCD":
                    raise tradier.TradierError("Structurally invalid OHLC.")
                return tradier.normalize_history(payload(), **kwargs)
            code, report = self.run_report(fetch)
            self.assertEqual(calls, list(tradier_report.SYMBOLS))
            self.assertEqual(code, 1 if fail_one else 0)
            self.assertEqual(report["summary"]["status"], "incomplete" if fail_one else "complete")
            self.assertEqual(report["summary"]["evaluated_symbols"], 18 if fail_one else 19)
            self.assertEqual(report["summary"]["new_downward_crossings"], 0)

    def test_unavailable_indicator_prevents_complete_quiet_claim(self):
        def fetch(token, **kwargs):
            data = payload()
            for row in data["history"]["day"]:
                row.update(open=100, high=100, low=100, close=100)
            return tradier.normalize_history(data, **kwargs)
        code, report = self.run_report(fetch)
        self.assertEqual(code, 1)
        self.assertEqual(report["summary"]["acquired_symbols"], 19)
        self.assertEqual(report["summary"]["usable_latest_symbols"], 0)
        self.assertEqual(report["summary"]["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
