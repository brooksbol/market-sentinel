"""Offline availability regressions: synthetic prices/credentials; no provider I/O."""
import copy
import json
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import numpy as np
from talib import abstract

from market_sentinel import scheduled_report as worker, tradier
from market_sentinel.stochastic import DailyOHLC, stochastic_14_3_3
import test_scheduled_report as support


def recent_fixture():
    cutoff = date(2026, 11, 11)
    day = date(2026, 9, 1)
    days, rows = {}, []
    while day <= cutoff:
        days[str(day)] = dict(start="09:30", end="16:00") if day.weekday() < 5 else None
        if day.weekday() < 5:
            rows.append(dict(date=str(day), open=60, high=110, low=10, close=60, volume=100))
        day += timedelta(days=1)
    return cutoff, days, rows


class RecentHistoryTests(unittest.TestCase):
    def acquire(self, rows, days, cutoff):
        def fetch(token, **kw):
            return tradier.normalize_history(dict(history=dict(day=rows)), **kw)
        with patch.object(worker, "fetch_history", side_effect=fetch) as get:
            result = worker.acquire_screening("synthetic", cutoff, days)
        return result, get

    def test_invalid_march_is_excluded_but_diagnosed_and_only_19_requested(self):
        cutoff, days, rows = recent_fixture()
        rows.insert(0, dict(date="2026-03-19", open="NaN", high="NaN", low="NaN", close=106.62))
        report, get = self.acquire(rows, days, cutoff)
        self.assertEqual(get.call_count, 19)
        for result in report["results"]:
            self.assertEqual(result["valid_bars"], 19)
            self.assertIn("2026-03-19", result["invalid_old_sessions"])
            self.assertEqual(result["latest"]["k"], 50)
            self.assertTrue(result["latest"]["crossing_available"])
        self.assertEqual(get.call_args.kwargs["start"], date.fromisoformat(rows[-19]["date"]))
        self.assertNotIn('"NaN"', json.dumps(report, allow_nan=False))

    def test_invalid_missing_duplicate_or_out_of_order_recent_bars_fail(self):
        cutoff, days, rows = recent_fixture()
        for fault in ("invalid", "missing", "duplicate", "reordered", "future"):
            damaged = copy.deepcopy(rows)
            if fault == "invalid": damaged[-10]["low"] = "NaN"
            if fault == "missing": damaged.pop(-10)
            if fault == "duplicate": damaged.insert(-1, copy.deepcopy(damaged[-2]))
            if fault == "reordered": damaged[-2], damaged[-3] = damaged[-3], damaged[-2]
            if fault == "future": damaged.append(dict(damaged[-1], date="2026-11-12"))
            with self.subTest(fault=fault), self.assertRaises((worker.ScheduleError, tradier.TradierError)):
                self.acquire(damaged, days, cutoff)

    def test_calendar_holiday_and_missing_calendar_day(self):
        cutoff, days, rows = recent_fixture()
        holiday = rows[-10]["date"]
        days[holiday] = None
        rows = [r for r in rows if r["date"] != holiday]
        report, _ = self.acquire(rows, days, cutoff)
        self.assertEqual(report["results"][0]["valid_bars"], 19)
        del days[holiday]
        with self.assertRaisesRegex(worker.ScheduleError, "Incomplete recent exchange calendar"):
            self.acquire(rows, days, cutoff)
        with self.assertRaises(worker.ScheduleError):
            self.acquire(rows, {str(cutoff): days[str(cutoff)]}, cutoff)

    def test_current_window_warnings_remain_visible_and_flat_windows_block(self):
        cutoff, days, rows = recent_fixture()
        rows[-1]["open"] = 111
        report, _ = self.acquire(rows, days, cutoff)
        self.assertEqual(report["results"][0]["warnings"][0]["code"], "open_outside_range")
        for row in rows: row.update(open=60, high=60, low=60, close=60)
        with self.assertRaisesRegex(worker.ScheduleError, "Unavailable indicator/comparison"):
            self.acquire(rows, days, cutoff)

    def test_fetch_requests_only_required_range_and_opts_into_old_exclusion(self):
        cutoff, _, rows = recent_fixture()
        start = date.fromisoformat(rows[-19]["date"])
        with patch.object(tradier, "_get_json", return_value=dict(history=dict(day=rows))) as get:
            history = tradier.fetch_history("synthetic", symbol="CLX", environment="production",
                                            start=start, end=cutoff, completed_through=cutoff,
                                            exclude_older=True)
        self.assertEqual(get.call_args.args[3], dict(symbol="CLX", interval="daily", start=str(start), end=str(cutoff)))
        self.assertEqual(len(history.bars), 19)


class NumericalPolicyTests(unittest.TestCase):
    def points(self, high, low, close):
        return stochastic_14_3_3([DailyOHLC(date(2026, 1, 1)+timedelta(days=i), float(c), float(h), float(l), float(c))
                                 for i, (h, l, c) in enumerate(zip(high, low, close))])

    def test_lookback_and_minimum_adjacent_outputs(self):
        self.assertEqual(abstract.Function("STOCH", fastk_period=14, slowk_period=3, slowk_matype=0, slowd_period=3, slowd_matype=0).lookback, 17)
        p = self.points(np.full(19, 110.), np.full(19, 10.), np.full(19, 60.))
        self.assertTrue(all(x.k is None and x.d is None for x in p[:17]))
        self.assertEqual([(x.k, x.d) for x in p[17:]], [(50., 50.), (50., 50.)])
        self.assertEqual(worker.HISTORY_SESSIONS, 19)

    def test_1000_long_vs_recent_histories_numerical_bound_and_crossings(self):
        maximum, changed = 0., 0
        for seed in range(1000):
            rng = np.random.default_rng(seed)
            low = rng.uniform(5, 200, 190)
            high = low + rng.uniform(.001, 50, 190)
            close = low + rng.random(190)*(high-low)
            long = self.points(high, low, close)
            short = self.points(high[-19:], low[-19:], close[-19:])
            for a, b in zip(long[-2:], short[-2:]):
                maximum = max(maximum, abs(a.k-b.k), abs(a.d-b.d))
            changed += long[-1].crossed_below_20 != short[-1].crossed_below_20
        self.assertLess(maximum, 3e-13)
        self.assertEqual(changed, 0)

    def test_exact_threshold_can_differ_from_long_accumulated_roundoff(self):
        rng = np.random.default_rng(0)
        high, low = np.full(190, 110.), np.full(190, 10.)
        close = rng.uniform(11, 109, 190)
        close[-4], close[-3:] = 31, 30
        long = self.points(high, low, close)
        short = self.points(high[-19:], low[-19:], close[-19:])
        self.assertLess(abs(long[-1].k-short[-1].k), 1e-12)
        # The new basis is explicit: no rounding/tolerance or long-history fallback.
        self.assertEqual(short[-1].k, 20.)
        self.assertFalse(short[-1].crossed_below_20)
        self.assertTrue(long[-1].crossed_below_20)


class IndependentSlotTests(unittest.TestCase):
    setUp = support.WorkerTests.setUp
    saved = support.WorkerTests.saved

    def test_blocked_opening_does_not_block_closing_and_failures_are_retained(self):
        now = support.NOW.replace(hour=17)
        self.acquire.side_effect = worker.ScheduleError("CLX: invalid recent OHLC")
        worker.run_once(self.root, now)
        # Opening retry is eligible, but the unattempted closing takes precedence.
        self.acquire.side_effect = None
        with patch.object(worker, "notification_body", return_value="synthetic closing report"):
            worker.run_once(self.root, now+timedelta(minutes=16))
        state = self.saved()["deliveries"]
        self.assertEqual(state["2026-11-02:opening"]["status"], "waiting")
        self.assertIn("CLX", state["2026-11-02:opening"]["last_failure"]["status"])
        self.assertEqual(state["2026-11-02:closing"]["status"], "accepted")
        self.assertEqual(self.acquire.call_count, 2)
        self.assertEqual(self.send.call_count, 2)  # Alert + closing, no opening.
        self.assertIsNotNone(self.saved()["last_failure"])

    def test_alert_suppression_persists_across_retries_and_restart(self):
        self.acquire.side_effect = RuntimeError("synthetic-secret")
        def send(*args, **kw):
            record = self.saved()["deliveries"]["2026-11-02:opening"]
            self.assertEqual(record["status"], "waiting")
            self.assertEqual(record["failure_alert"]["status"], "attempting")
        self.send.side_effect = send
        for minute in (0, 1, 15, 16, 30):
            worker.run_once(self.root, support.NOW+timedelta(minutes=minute))
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.acquire.call_count, 3)
        record = self.saved()["deliveries"]["2026-11-02:opening"]
        self.assertEqual(record["failure_alert"]["status"], "accepted")
        self.assertEqual(record["failure_count"], 3)
        self.assertNotIn("synthetic-secret", (self.root/'state.json').read_text())
        self.acquire.side_effect = None
        self.send.side_effect = None
        worker.run_once(self.root, support.NOW+timedelta(minutes=45))
        record = self.saved()["deliveries"]["2026-11-02:opening"]
        self.assertEqual(record["status"], "accepted")
        self.assertIn("recovered", record)
        self.assertIn("last_failure", record)
        self.assertEqual(self.send.call_count, 2)  # Recovered report is the recovery notice.

    def test_unknown_alert_never_resends_but_report_can_recover(self):
        self.acquire.side_effect = RuntimeError("synthetic-secret")
        self.send.side_effect = TimeoutError("synthetic-secret")
        worker.run_once(self.root, support.NOW)
        worker.run_once(self.root, support.NOW+timedelta(minutes=15))
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.saved()["deliveries"]["2026-11-02:opening"]["failure_alert"]["status"], "unknown")
        self.acquire.side_effect = None
        self.send.side_effect = None
        worker.run_once(self.root, support.NOW+timedelta(minutes=30))
        self.assertEqual(self.saved()["deliveries"]["2026-11-02:opening"]["status"], "accepted")
        self.assertEqual(self.send.call_count, 2)

    def test_interrupted_alert_does_not_resend(self):
        self.acquire.side_effect = RuntimeError("synthetic-secret")
        worker.run_once(self.root, support.NOW)
        state = self.saved()
        state["deliveries"]["2026-11-02:opening"]["failure_alert"]["status"] = "attempting"
        worker.save_json(self.root/'state.json', state)
        worker.run_once(self.root, support.NOW+timedelta(minutes=15))
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.saved()["deliveries"]["2026-11-02:opening"]["failure_alert"]["status"], "unknown")

    def test_credentials_fail_before_alert_intent_and_retry_is_safe(self):
        self.acquire.side_effect = RuntimeError("synthetic-secret")
        self.credentials.side_effect = RuntimeError("synthetic-secret")
        worker.run_once(self.root, support.NOW)
        self.send.assert_not_called()
        record = self.saved()["deliveries"]["2026-11-02:opening"]
        self.assertEqual(record["failure_alert"]["status"], "waiting")
        self.assertNotIn("attempted", record["failure_alert"])
        self.credentials.side_effect = None
        worker.run_once(self.root, support.NOW+timedelta(minutes=15))
        self.assertEqual(self.send.call_count, 1)

    def test_legacy_global_retry_migrates_without_blocking_fresh_slot(self):
        now = support.NOW.replace(hour=17)
        state = self.saved()
        state.update(retry_after=(now+timedelta(minutes=10)).timestamp(),
                     last_failure=dict(at=(now-timedelta(minutes=5)).isoformat(), status="Old failure. No report sent."))
        worker.save_json(self.root/'state.json', state)
        with patch.object(worker, "notification_body", return_value="synthetic closing report"):
            worker.run_once(self.root, now)
        state = self.saved()
        self.assertEqual(state["retry_after"], 0)
        self.assertEqual(state["deliveries"]["2026-11-02:opening"]["status"], "waiting")
        self.assertEqual(state["deliveries"]["2026-11-02:closing"]["status"], "accepted")
        self.assertEqual(self.acquire.call_count, 1)

    def test_calendar_failure_alert_backoff_and_daily_deduplication(self):
        self.http.side_effect = RuntimeError("synthetic-secret")
        for minute in (0, 1, 15, 30):
            worker.run_once(self.root, support.NOW+timedelta(minutes=minute))
        self.assertEqual(self.send.call_count, 1)
        self.acquire.assert_not_called()
        self.assertEqual(self.saved()["calendar_failures"]["2026-11-02"]["failure_alert"]["status"], "accepted")

    def test_corrupt_alert_state_is_preserved_without_resending(self):
        state = self.saved()
        state["deliveries"]["2026-11-02:opening"] = dict(status="waiting", failure_alert=dict(status="invalid"))
        worker.save_json(self.root/"state.json", state)
        original = (self.root/"state.json").read_bytes()
        with self.assertRaises(worker.ScheduleError):
            worker.run_once(self.root, support.NOW)
        self.assertEqual((self.root/"state.json").read_bytes(), original)
        self.send.assert_not_called()

    def test_interrupted_alert_is_marked_unknown_even_when_report_recovers(self):
        self.acquire.side_effect = RuntimeError("synthetic-secret")
        worker.run_once(self.root, support.NOW)
        state = self.saved()
        state["deliveries"]["2026-11-02:opening"]["failure_alert"]["status"] = "attempting"
        worker.save_json(self.root/"state.json", state)
        self.acquire.side_effect = None
        worker.run_once(self.root, support.NOW+timedelta(minutes=15))
        record = self.saved()["deliveries"]["2026-11-02:opening"]
        self.assertEqual(record["failure_alert"]["status"], "unknown")
        self.assertEqual(record["status"], "accepted")
        self.assertEqual(self.send.call_count, 2)
