"""Hand-derived synthetic references, not a second Stochastic implementation.

Fixed range [10, 110] makes close=10+x have raw K=x after warm-up.
The reference raw sequence 30,60,90,30,0,0,0,60,0,0,0 gives:
K: -, -, 60,60,40,10,0,20,20,20,0
D: -, -, -, -, 160/3,110/3,50/3,10,40/3,20,40/3
Only raw-sequence positions 6 and 11 (one-based) cross below 20.
"""

import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta
from unittest.mock import patch

from market_sentinel.stochastic import DailyOHLC, crossed_below_20, stochastic_14_3_3

START = date(2026, 1, 1)


def fixed_range(raw_closes):
    """Synthetic sessions, not an exchange calendar; raw_closes are percentages."""
    return [DailyOHLC(START + timedelta(days=i), 60, 110, 10, 10 + x)
            for i, x in enumerate(raw_closes)]


def with_raw_sequence(raw_values):
    return fixed_range([50] * 13 + list(raw_values))


class CalculationTests(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(stochastic_14_3_3([]), ())

    def test_exact_warmup_boundaries(self):
        for count in range(1, 20):
            with self.subTest(count=count):
                point = stochastic_14_3_3(fixed_range([50] * count))[-1]
                self.assertEqual(point.raw_k, 50 if count >= 14 else None)
                self.assertEqual(point.k, 50 if count >= 16 else None)
                self.assertEqual(point.d, 50 if count >= 18 else None)
                self.assertFalse(point.zero_range)
                self.assertFalse(point.crossed_below_20)

    def test_rolling_extremes_leave_the_window_independently(self):
        bars = fixed_range([50] * 16)
        bars[0] = replace(bars[0], high=210)
        bars[1] = replace(bars[1], low=1)
        points = stochastic_14_3_3(bars)
        # Close=60: range [1,210], then [1,110], then [10,110].
        for index, expected in ((13, 5900 / 209), (14, 5900 / 109), (15, 50)):
            self.assertAlmostEqual(points[index].raw_k, expected, delta=1e-12)

    def test_current_bar_participates_in_rolling_extremes(self):
        bars = fixed_range([50] * 14)
        bars[-1] = replace(bars[-1], high=210, close=110)
        self.assertEqual(stochastic_14_3_3(bars)[-1].raw_k, 50)

    def test_raw_arithmetic_uses_close_and_not_open(self):
        bars = fixed_range([50] * 13 + [25])
        bars[-1] = replace(bars[-1], open=100)
        self.assertEqual(stochastic_14_3_3(bars)[-1].raw_k, 25)

    def test_smoothing_and_d_against_hand_derived_table(self):
        raw = [30, 60, 90, 30, 0, 0, 0, 60, 0, 0, 0]
        k = [None, None, 60, 60, 40, 10, 0, 20, 20, 20, 0]
        d = [None, None, None, None, 160 / 3, 110 / 3, 50 / 3, 10, 40 / 3, 20, 40 / 3]
        points = stochastic_14_3_3(with_raw_sequence(raw))[13:]
        for index, point in enumerate(points):
            with self.subTest(raw_position=index + 1):
                self.assertAlmostEqual(point.raw_k, raw[index], delta=1e-12)
                for actual, expected in ((point.k, k[index]), (point.d, d[index])):
                    if expected is None:
                        self.assertIsNone(actual)
                    else:
                        self.assertAlmostEqual(actual, expected, delta=1e-12)
                self.assertEqual(point.crossed_below_20, index in (5, 10))

    def test_constant_prices_are_undefined_not_zero(self):
        bars = [DailyOHLC(START + timedelta(days=i), 100, 100, 100, 100) for i in range(25)]
        for index, point in enumerate(stochastic_14_3_3(bars)):
            self.assertIsNone(point.raw_k)
            self.assertIsNone(point.k)
            self.assertIsNone(point.d)
            self.assertEqual(point.zero_range, index >= 13)
            self.assertFalse(point.crossed_below_20)

    def test_constant_closes_with_nonzero_range_are_valid(self):
        point = stochastic_14_3_3(fixed_range([50] * 18))[-1]
        self.assertEqual((point.raw_k, point.k, point.d), (50, 50, 50))

    def test_zero_range_requires_new_consecutive_smoothing_windows(self):
        bars = fixed_range([50] * 18)
        bars += [DailyOHLC(START + timedelta(days=i), 100, 100, 100, 100)
                 for i in range(18, 32)]
        bars += [DailyOHLC(START + timedelta(days=i), 100, 110, 90, 90)
                 for i in range(32, 37)]
        points = stochastic_14_3_3(bars)
        self.assertGreaterEqual(points[30].k, 20)
        self.assertTrue(points[31].zero_range)
        for index in (31, 32, 33):
            self.assertIsNone(points[index].k)
        self.assertEqual(points[34].k, 0)
        self.assertIsNone(points[34].d)
        self.assertIsNone(points[35].d)
        self.assertEqual(points[36].d, 0)
        self.assertFalse(any(point.crossed_below_20 for point in points[31:]))

    def test_rising_series_closing_at_high_is_100(self):
        bars = [DailyOHLC(START + timedelta(days=i), i + 2, i + 3, i + 1, i + 3)
                for i in range(25)]
        point = stochastic_14_3_3(bars)[-1]
        self.assertEqual((point.raw_k, point.k, point.d), (100, 100, 100))

    def test_falling_series_closing_at_low_is_valid_zero(self):
        bars = [DailyOHLC(START + timedelta(days=i), 30 - i, 31 - i, 29 - i, 29 - i)
                for i in range(25)]
        point = stochastic_14_3_3(bars)[-1]
        self.assertEqual((point.raw_k, point.k, point.d), (0, 0, 0))
        self.assertFalse(point.zero_range)
        self.assertFalse(point.crossed_below_20)

    def test_oscillating_series_fractional_reference(self):
        points = stochastic_14_3_3(fixed_range([0, 100] * 10))
        self.assertAlmostEqual(points[17].k, 200 / 3, delta=1e-12)
        self.assertAlmostEqual(points[17].d, 500 / 9, delta=1e-12)
        self.assertAlmostEqual(points[18].k, 100 / 3, delta=1e-12)
        self.assertAlmostEqual(points[18].d, 400 / 9, delta=1e-12)

    def test_only_smoothed_k_triggers_not_raw_or_d(self):
        points = stochastic_14_3_3(with_raw_sequence([30, 60, 90, 30, 0, 0]))
        self.assertEqual(points[-2].raw_k, 0)
        self.assertEqual(points[-2].k, 40)
        self.assertFalse(points[-2].crossed_below_20)
        self.assertEqual(points[-1].k, 10)
        self.assertGreater(points[-1].d, 20)
        self.assertTrue(points[-1].crossed_below_20)

    def test_k_crossing_can_precede_first_d(self):
        points = stochastic_14_3_3(with_raw_sequence([30, 30, 0, 0]))
        self.assertEqual(points[-2].k, 20)
        self.assertEqual(points[-1].k, 10)
        self.assertIsNone(points[-1].d)
        self.assertTrue(points[-1].crossed_below_20)

    def test_end_to_end_crossing_does_not_round_to_20(self):
        points = stochastic_14_3_3(with_raw_sequence([20.00000003] * 3 + [19.99999991]))
        previous, current = points[-2:]
        self.assertGreater(previous.k, 20)
        self.assertLess(current.k, 20)
        self.assertEqual(round(current.k, 6), 20)
        self.assertTrue(current.crossed_below_20)

    def test_no_future_lookahead_or_mutation_and_immutable_results(self):
        bars = with_raw_sequence([30, 30, 0, 0, 90, 90])
        original = list(bars)
        full = stochastic_14_3_3(bars)
        self.assertEqual(full[:17], stochastic_14_3_3(bars[:17]))
        self.assertEqual(full, stochastic_14_3_3(iter(bars)))
        self.assertEqual(bars, original)
        self.assertEqual(tuple(point.session for point in full), tuple(bar.session for bar in bars))
        with self.assertRaises(FrozenInstanceError):
            full[-1].k = 99

    def test_calculation_needs_no_io(self):
        bars = fixed_range([50] * 18)
        with patch("builtins.open", side_effect=AssertionError("filesystem forbidden")), \
             patch("socket.create_connection", side_effect=AssertionError("network forbidden")), \
             patch("subprocess.run", side_effect=AssertionError("subprocess forbidden")):
            self.assertEqual(stochastic_14_3_3(bars)[-1].k, 50)


class ValidationTests(unittest.TestCase):
    def test_invalid_ohlc_structure(self):
        bar = fixed_range([50])[0]
        for changes in ({"low": 0}, {"low": -1}, {"high": -1}, {"high": 5},
                        {"open": 111}, {"open": 9}, {"close": 111}, {"close": 9}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                stochastic_14_3_3([replace(bar, **changes)])

    def test_all_price_fields_reject_nonfinite_missing_and_nonnumeric_values(self):
        bar = fixed_range([50])[0]
        for field in ("open", "high", "low", "close"):
            for value in (None, float("nan"), float("inf"), -float("inf"), True, "60", 10**1000):
                with self.subTest(field=field, kind=type(value).__name__), self.assertRaises(ValueError):
                    stochastic_14_3_3([replace(bar, **{field: value})])

    def test_missing_or_wrong_observation_is_rejected(self):
        for value in (None, {}, (START, 60, 110, 10, 60)):
            with self.subTest(kind=type(value).__name__), self.assertRaises(ValueError):
                stochastic_14_3_3([value])

    def test_all_ohlc_fields_are_required(self):
        with self.assertRaises(TypeError):
            DailyOHLC(session=START, high=110, low=10, close=60)

    def test_duplicate_or_reversed_sessions_are_rejected(self):
        bars = fixed_range([50, 50])
        for observations in ([bars[0], bars[0]], list(reversed(bars))):
            with self.subTest(observations=observations), self.assertRaises(ValueError):
                stochastic_14_3_3(observations)

    def test_session_must_be_date_not_datetime_string_or_missing(self):
        bar = fixed_range([50])[0]
        for session in (None, "2026-01-01", datetime(2026, 1, 1)):
            with self.subTest(kind=type(session).__name__), self.assertRaises(ValueError):
                stochastic_14_3_3([replace(bar, session=session)])

    def test_date_gaps_are_preserved_without_calendar_inference_or_filling(self):
        bars = fixed_range([50] * 14)
        bars[-1] = replace(bars[-1], session=START + timedelta(days=30))
        points = stochastic_14_3_3(bars)
        self.assertEqual(len(points), 14)
        self.assertEqual(points[-1].session, bars[-1].session)
        self.assertEqual(points[-1].raw_k, 50)

    def test_large_finite_prices_do_not_overflow_raw_k(self):
        bars = [DailyOHLC(START + timedelta(days=i), 1e308, 1.7e308, 1e307, 1e308)
                for i in range(18)]
        # (1e308 - 1e307) / (1.7e308 - 1e307) = 9/16.
        self.assertAlmostEqual(stochastic_14_3_3(bars)[-1].k, 56.25, delta=1e-12)


class CrossingTests(unittest.TestCase):
    def test_exact_boundaries_direction_and_no_repeated_below(self):
        for previous, current, expected in ((20, 19, True), (21, 19, True),
                                            (19, 18, False), (21, 20, False),
                                            (20, 20, False), (19, 21, False),
                                            (19, 20, False), (100, 0, True)):
            with self.subTest(previous=previous, current=current):
                self.assertEqual(crossed_below_20(previous, current), expected)

    def test_unavailable_adjacent_values_do_not_cross(self):
        for values in ((None, None), (None, 19), (21, None)):
            with self.subTest(values=values):
                self.assertFalse(crossed_below_20(*values))
        self.assertFalse(any(point.crossed_below_20
                             for point in stochastic_14_3_3(fixed_range([0] * 16))))

    def test_recovery_to_exactly_20_allows_another_crossing(self):
        # Stateless adjacent comparisons: no separate re-arming state needed.
        self.assertEqual([crossed_below_20(a, b) for a, b in zip(
            [21, 19, 18, 20], [19, 18, 20, 19])], [True, False, False, True])

    def test_near_threshold_is_not_rounded(self):
        self.assertTrue(crossed_below_20(20.000000001, 19.999999999))
        self.assertFalse(crossed_below_20(19.999999999, 19))

    def test_invalid_values_are_errors_even_with_an_unavailable_neighbor(self):
        for invalid in (float("nan"), float("inf"), -1, 101, True, "20"):
            for values in ((invalid, 19), (21, invalid), (None, invalid)):
                with self.subTest(kind=type(invalid).__name__), self.assertRaises(ValueError):
                    crossed_below_20(*values)


if __name__ == "__main__":
    unittest.main()
