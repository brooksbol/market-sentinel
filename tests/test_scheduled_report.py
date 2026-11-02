"""Offline scheduler, calendar, replay and send-intent tests. No real credentials."""

import calendar
import copy
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from market_sentinel import scheduled_report as worker, tradier
from test_daily_report import screening
from test_tradier import fixture


NOW = datetime(2026, 11, 2, 15, 0, tzinfo=worker.ET)


def month_payload(year=2026, month=11):
    rows = []
    for n in range(1, calendar.monthrange(year, month)[1] + 1):
        day = date(year, month, n)
        rows.append(dict(date=str(day), status="closed" if day.weekday() >= 5 else "open",
                         open=dict(start="09:30", end="16:00")))
    return dict(calendar=dict(year=year, month=month, days=dict(day=rows)))


def sessions():
    result = {}
    for year, month in ((2026, 10), (2026, 11)):
        result.update(worker.normalize_calendar(month_payload(year, month), year, month))
    return result


class CalendarTests(unittest.TestCase):
    def test_complete_month_and_holiday(self):
        payload = month_payload()
        payload["calendar"]["days"]["day"][25]["status"] = "closed"
        result = worker.normalize_calendar(payload, 2026, 11)
        self.assertEqual(len(result), 30)
        self.assertIsNone(result["2026-11-26"])
        self.assertEqual(result["2026-11-02"], dict(start="09:30", end="16:00"))

    def test_missing_duplicate_unknown_status_wrong_month_and_bad_hours_rejected(self):
        for kind in ("missing", "duplicate", "status", "month", "hours", "timezone", "weekend", "shape"):
            payload = month_payload()
            rows = payload["calendar"]["days"]["day"]
            if kind == "missing": rows.pop()
            if kind == "duplicate": rows[-1] = copy.deepcopy(rows[-2])
            if kind == "status": rows[1]["status"] = "unknown"
            if kind == "month": payload["calendar"]["month"] = 10
            if kind == "hours": rows[1]["open"]["end"] = "09:00"
            if kind == "timezone": rows[1]["open"]["end"] = "16:00+00:00"
            if kind == "weekend": rows[0]["status"] = "open"
            if kind == "shape": payload = []
            with self.subTest(kind=kind), self.assertRaises(worker.ScheduleError):
                worker.normalize_calendar(payload, 2026, 11)

    def test_production_calendar_http_uses_existing_safe_get(self):
        with patch("market_sentinel.tradier.build_opener") as build:
            response = build.return_value.open.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = json.dumps(month_payload()).encode()
            result = tradier._get_json("synthetic-token", "production", "calendar", dict(month=11, year=2026))
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://api.tradier.com/v1/markets/calendar?month=11&year=2026")
            self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-token")
            self.assertEqual(result, month_payload())
            self.assertEqual(build.return_value.open.call_args.kwargs, dict(timeout=15))
            with self.assertRaises(tradier.TradierError):
                tradier._get_json("synthetic-token", "production", "accounts", {})
            self.assertEqual(build.return_value.open.call_count, 1)

    def test_opening_boundary_and_previous_session_not_intraday(self):
        for minute, expected in ((30, 0), (31, 1)):
            now = datetime(2026, 11, 2, 9, minute, tzinfo=worker.ET)
            due = worker.due_reports(now, date(2026, 11, 2), sessions())
            self.assertEqual(len(due), expected)
            if expected:
                self.assertEqual(due[0]["session"], "2026-10-30")

    def test_closing_boundary_and_utc_host_clock(self):
        before = datetime(2026, 11, 2, 21, 0, tzinfo=timezone.utc)
        after = before + timedelta(minutes=1)
        self.assertEqual(len(worker.due_reports(before, date(2026, 11, 2), sessions())), 1)
        due = worker.due_reports(after, date(2026, 11, 2), sessions())
        self.assertEqual(due[-1]["session"], "2026-11-02")
        self.assertEqual(due[-1]["kind"], "closing")

    def test_dst_changes_utc_offset_without_changing_local_time(self):
        due = worker.due_reports(datetime(2026, 11, 2, 17, tzinfo=worker.ET), date(2026, 10, 30), sessions())
        self.assertEqual(due[0]["due"], "2026-10-30T09:31:00-04:00")
        self.assertEqual(due[-2]["due"], "2026-11-02T09:31:00-05:00")
        self.assertEqual(len(due), 4)  # Weekend produces no new report.

    def test_early_close_and_holiday(self):
        days = sessions()
        days["2026-11-26"] = None
        days["2026-11-27"]["end"] = "13:00"
        due = worker.due_reports(datetime(2026, 11, 27, 13, 1, tzinfo=worker.ET), date(2026, 11, 26), days)
        self.assertEqual([item["kind"] for item in due], ["opening", "closing"])
        self.assertEqual(due[0]["session"], "2026-11-25")
        self.assertIn("13:01", due[1]["due"])

    def test_naive_clock_and_missing_previous_session_fail(self):
        with self.assertRaises(worker.ScheduleError):
            worker.due_reports(datetime(2026, 11, 2), date(2026, 11, 2), sessions())
        with self.assertRaises(worker.ScheduleError):
            worker.due_reports(NOW, date(2026, 11, 2), {"2026-11-02": dict(start="09:30", end="16:00")})

    def test_backlog_order_and_activation_boundary(self):
        due = worker.due_reports(datetime(2026, 11, 4, 17, tzinfo=worker.ET), date(2026, 11, 2), sessions())
        self.assertEqual([item["id"] for item in due], [f"2026-11-{day:02}:{kind}" for day in (2, 3, 4) for kind in ("opening", "closing")])


class AcquisitionTests(unittest.TestCase):
    def test_calendar_coverage_and_existing_stochastic_integration(self):
        cutoff = date(2026, 10, 30)
        days = {}
        start = cutoff - timedelta(days=270)
        day = start
        rows = []
        while day <= cutoff:
            days[str(day)] = dict(start="09:30", end="16:00") if day.weekday() < 5 else None
            if day.weekday() < 5:
                rows.append(dict(date=str(day), open=60, high=110, low=10, close=60, volume=1000))
            day += timedelta(days=1)
        def fetch(token, **kw):
            return tradier.normalize_history({"history": {"day": rows}}, **kw)
        with patch.object(worker, "fetch_history", side_effect=fetch) as get:
            report = worker.acquire_screening("synthetic", cutoff, days)
        self.assertEqual(get.call_count, 19)
        self.assertEqual(report["summary"]["usable_latest_symbols"], 19)
        self.assertEqual(report["results"][0]["latest"]["k"], 50)
        self.assertEqual(report["results"][0]["latest"]["d"], 50)
        rows.pop()  # A stale close cannot silently become a successful report.
        with patch.object(worker, "fetch_history", side_effect=fetch), self.assertRaisesRegex(worker.ScheduleError, "Missing, stale"):
            worker.acquire_screening("synthetic", cutoff, days)

    def test_context_and_character_preflight(self):
        slot = dict(kind="opening", observation="2026-11-02", session="2026-10-30")
        body = worker.notification_body(screening(), slot)
        self.assertTrue(body.startswith("Opening 2026-11-02 ET\n2026-10-30"))
        self.assertLessEqual(len(body), 1024)
        self.assertNotIn("DEMONSTRATION", body)
        with self.assertRaises(worker.ScheduleError):
            worker.notification_body(screening(), dict(slot, session="2026-11-02"))
        with patch.object(worker, "format_daily_report", return_value="x"*1024), self.assertRaises(Exception):
            worker.notification_body(screening(), slot)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = dict(version=1, activated="2026-11-02", deliveries={}, calendars={})
        worker.save_json(self.root / "state.json", self.state)
        self.addCleanup(patch.stopall)
        self.token = patch.object(worker, "load_token", return_value="synthetic-secret").start()
        self.credentials = patch.object(worker, "load_credentials", return_value=("A"*30, "U"*30)).start()
        self.http = patch.object(worker, "_get_json", side_effect=lambda token, env, endpoint, kw: month_payload(kw["year"], kw["month"])).start()
        self.acquire = patch.object(worker, "acquire_screening", return_value=screening()).start()
        self.send = patch.object(worker, "_send_message").start()

    def saved(self):
        return worker.read_state(self.root)

    def test_unattended_acceptance_durable_intent_and_repeat_no_send(self):
        def send(*args, **kwargs):
            self.assertEqual(self.saved()["deliveries"]["2026-11-02:opening"]["status"], "attempting")
        self.send.side_effect = send
        self.assertEqual(worker.run_once(self.root, NOW), 0)
        self.assertEqual(self.saved()["deliveries"]["2026-11-02:opening"]["status"], "accepted")
        self.assertEqual(worker.run_once(self.root, NOW + timedelta(minutes=1)), 0)
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.acquire.call_count, 1)
        self.assertEqual(self.send.call_args.kwargs, dict(monospace=True))
        self.assertIn("Opening 2026-11-02 ET", self.send.call_args.args[3])
        self.assertNotIn("synthetic-secret", (self.root / "worker.log").read_text())

    def test_after_initial_calendar_cache_idle_check_reads_no_credentials(self):
        worker.run_once(self.root, NOW)
        self.token.reset_mock(); self.credentials.reset_mock(); self.http.reset_mock()
        worker.run_once(self.root, NOW + timedelta(minutes=1))
        self.token.assert_not_called(); self.credentials.assert_not_called(); self.http.assert_not_called()

    def test_data_failure_delays_and_retries_without_false_quiet_push(self):
        self.acquire.side_effect = RuntimeError("synthetic-secret")
        self.assertEqual(worker.run_once(self.root, NOW), 1)
        self.send.assert_not_called()
        worker.run_once(self.root, NOW + timedelta(minutes=1))
        self.assertEqual(self.acquire.call_count, 1)
        self.acquire.side_effect = None
        worker.run_once(self.root, NOW + timedelta(minutes=15))
        self.assertEqual(self.send.call_count, 1)
        self.assertNotIn("synthetic-secret", (self.root / "state.json").read_text())

    def test_push_ambiguous_failure_never_retried(self):
        self.send.side_effect = TimeoutError("synthetic-secret")
        self.assertEqual(worker.run_once(self.root, NOW), 1)
        self.assertEqual(self.saved()["deliveries"]["2026-11-02:opening"]["status"], "unknown")
        worker.run_once(self.root, NOW + timedelta(minutes=1))
        self.assertEqual(self.send.call_count, 1)
        self.assertNotIn("synthetic-secret", (self.root / "worker.log").read_text())

    def test_interrupted_intent_never_retried_but_future_slot_can_send(self):
        state = self.saved()
        state["deliveries"]["2026-11-02:opening"] = dict(status="attempting")
        worker.save_json(self.root / "state.json", state)
        self.assertEqual(worker.run_once(self.root, NOW), 0)
        self.send.assert_not_called()
        self.assertEqual(self.saved()["deliveries"]["2026-11-02:opening"]["status"], "unknown")
        # Existing formatter must receive the proper new-session results.
        result = screening()
        result["summary"]["completed_session"] = "2026-11-02"
        for row in result["results"]:
            row.update(last_session="2026-11-02", completed_through="2026-11-02")
        self.acquire.return_value = result
        worker.run_once(self.root, NOW.replace(hour=17))
        self.assertEqual(self.send.call_count, 1)
        self.assertIn("Closing", self.send.call_args.args[3])

    def test_multiple_days_catch_up_one_slot_per_tick(self):
        # Inspect target/session selection without pretending mock source data is real.
        with patch.object(worker, "notification_body", return_value="synthetic complete body"):
            for _ in range(6):
                worker.run_once(self.root, NOW.replace(day=4, hour=17))
        self.assertEqual(self.send.call_count, 6)
        self.assertEqual(list(self.saved()["deliveries"]), [f"2026-11-{day:02}:{kind}" for day in (2,3,4) for kind in ("opening", "closing")])
        self.assertEqual([str(call.args[1]) for call in self.acquire.call_args_list],
                         ["2026-10-30", "2026-11-02", "2026-11-02", "2026-11-03", "2026-11-03", "2026-11-04"])

    def test_calendar_failure_stops_before_prices_or_push(self):
        self.http.side_effect = RuntimeError("synthetic-secret")
        self.assertEqual(worker.run_once(self.root, NOW), 1)
        self.acquire.assert_not_called(); self.send.assert_not_called()

    def test_malformed_ledger_never_reset(self):
        (self.root / "state.json").write_text("bad")
        with self.assertRaises(ValueError): worker.run_once(self.root, NOW)
        self.assertEqual((self.root / "state.json").read_text(), "bad")
        self.send.assert_not_called()

    def test_overlap_excluded_by_lock(self):
        import fcntl
        with (self.root / "worker.lock").open("a") as locked:
            fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(worker.run_once(self.root, NOW), 0)
        self.http.assert_not_called(); self.send.assert_not_called()

    def test_atomic_state_permissions_and_log_permissions(self):
        worker.run_once(self.root, NOW)
        for name in ("state.json", "worker.log", "worker.lock", "2026-11-02-opening.json"):
            self.assertEqual((self.root / name).stat().st_mode & 0o777, 0o600)

    def test_plist_no_secrets_and_every_minute_with_startup(self):
        config = worker.launch_agent(Path("/tmp/venv/bin/python"), self.root, Path("/tmp/source"))
        self.assertTrue(config["RunAtLoad"])
        self.assertEqual(config["StartCalendarInterval"], [dict(Minute=n) for n in range(60)])
        self.assertEqual(config["ProgramArguments"][-1], "--run")
        self.assertEqual(config["WorkingDirectory"], "/tmp/source")
        self.assertNotIn("EnvironmentVariables", config)


if __name__ == "__main__":
    unittest.main()
