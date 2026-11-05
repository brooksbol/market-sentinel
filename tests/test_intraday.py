"""Synthetic timestamped market observations; network and secrets forbidden."""

import copy
import http.client
import json
import tempfile
import threading
import unittest
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from market_sentinel import intraday as core, intraday_provider, realtime, realtime_view, report_history, tradier
from market_sentinel.intraday_state import Ledger, read_view
from market_sentinel.sessions import ET, normalize_calendar
from market_sentinel.stochastic import DailyOHLC, stochastic_14_3_3
from market_sentinel.universe import SYMBOLS
from test_scheduled_report import month_payload

OPEN = datetime(2026, 11, 5, 9, 30, tzinfo=ET)
CLOSE = OPEN.replace(hour=16, minute=0)
NOW = OPEN + timedelta(minutes=6, seconds=5)


def history():
    # Synthetic adjacent weekdays; flat [10,110] ranges give raw K=close-10.
    days, day = [], OPEN.date() - timedelta(days=40)
    while day < OPEN.date():
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return tuple(DailyOHLC(d, 60, 110, 10, 35) for d in days)


def payload(n=7):
    return dict(series=dict(data=[dict(timestamp=int((OPEN+timedelta(minutes=i)).timestamp()),
        time=(OPEN+timedelta(minutes=i)).replace(tzinfo=None).isoformat(), open=20, high=40, low=10, close=15)
        for i in range(n)]))


def observation(k=19, minute=6, baseline=25, symbol='XOM'):
    at = OPEN + timedelta(minutes=minute)
    return dict(symbol=symbol, session=str(OPEN.date()), observed=at.isoformat(), detected=(at+timedelta(seconds=5)).isoformat(),
                price=15, k=k, d=22, completed=dict(session='2026-11-04', k=baseline, d=30),
                candle=dict(session='2026-11-05', open=20, high=40, low=10, close=15),
                provenance=core.CONVENTION, historical_warnings=0, last_confirmed_crossing=None)


class Offline(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch('market_sentinel.tradier.build_opener', side_effect=AssertionError('Network forbidden')).start()
        patch('market_sentinel.tradier.subprocess.run', side_effect=AssertionError('Secrets forbidden')).start()
        patch('market_sentinel.pushover.build_opener', side_effect=AssertionError('Push forbidden')).start()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'private/state.sqlite3'

    def ledger(self):
        result = Ledger(self.path)
        self.addCleanup(result.close)
        return result


class CalculationTests(Offline):
    def test_completed_daily_fixture_unchanged_independent_sma(self):
        bars = history()
        before = stochastic_14_3_3(bars)
        candle, at = core.developing_candle(payload(), OPEN, CLOSE, NOW)
        result = core.evaluate('XOM', bars, candle, at, NOW, previous_session=bars[-1].session)
        # Independent arithmetic: final raw=5; K=(25+25+5)/3;
        # D=(25+25+55/3)/3. No TA-Lib call generates these expected values.
        self.assertAlmostEqual(result['k'], 55/3, places=12)
        self.assertAlmostEqual(result['d'], (25+25+55/3)/3, places=12)
        self.assertEqual(result['completed']['k'], 25)
        self.assertEqual(stochastic_14_3_3(bars), before)
        self.assertEqual(candle, DailyOHLC(OPEN.date(), 20, 40, 10, 15))
        self.assertEqual(at, OPEN+timedelta(minutes=6))

    def test_real_developing_ohlc_not_last_price_pseudo_candle(self):
        data = payload()
        data['series']['data'][1].update(high=105, low=2)
        bar, _ = core.developing_candle(data, OPEN, CLOSE, NOW)
        self.assertEqual((bar.open, bar.high, bar.low, bar.close), (20, 105, 2, 15))
        # Current minute is still developing and must not enter OHLC.
        data['series']['data'][-1].update(high=999)
        self.assertEqual(core.developing_candle(data, OPEN, CLOSE, NOW)[0], bar)

    def test_duplicate_current_candle_and_wrong_cutoff_refused(self):
        bar, at = core.developing_candle(payload(), OPEN, CLOSE, NOW)
        for bars, cutoff in ((history()+ (bar,), OPEN.date()), (history(), date(2026,11,3))):
            with self.assertRaises(ValueError):
                core.evaluate('XOM', bars, bar, at, NOW, previous_session=cutoff)

    def test_incomplete_stale_bad_prices_and_timestamps_refused(self):
        variants = []
        for field, value in [('close', None), ('high', 9), ('low', -1), ('open', float('nan')), ('close', 50), ('timestamp', True), ('time', '2026-11-05T14:30:00')]:
            data = payload(); data['series']['data'][2][field] = value; variants.append(data)
        data=payload(); data['series']['data'].pop(2); variants.append(data)
        data=payload(); data['series']['data'].pop(0); variants.append(data)
        data=payload(); data['series']['data'].reverse(); variants.append(data)
        data=payload(); data['series']['data'].append(data['series']['data'][-1]); variants.append(data)
        variants.extend([{}, {'series':None}, {'series':{'data':[]}}])
        for data in variants:
            with self.subTest(data=str(data)[:80]), self.assertRaises(ValueError):
                core.developing_candle(data, OPEN, CLOSE, NOW)
        for at in (NOW+timedelta(minutes=10), CLOSE, OPEN-timedelta(seconds=1)):
            with self.assertRaises(ValueError):
                core.developing_candle(payload(), OPEN, CLOSE, at)

    def test_calendar_holiday_early_close_dst_mountain_and_startup(self):
        data = month_payload()
        data['calendar']['days']['day'][25]['status']='closed'
        data['calendar']['days']['day'][26]['open']['end']='13:00'
        sessions = normalize_calendar(data,2026,11)
        self.assertIsNone(core.session_bounds(datetime(2026,11,26,15,tzinfo=ET), sessions))
        opening, closing=core.session_bounds(datetime(2026,11,27,12,tzinfo=ET), sessions)
        self.assertEqual(closing.hour,13)
        self.assertEqual(closing.astimezone(timezone.utc).hour,18)
        from zoneinfo import ZoneInfo
        self.assertEqual(opening.astimezone(ZoneInfo('America/Denver')).hour,7)
        october=normalize_calendar(month_payload(2026,10),2026,10)
        self.assertEqual(core.session_bounds(datetime(2026,10,30,12,tzinfo=ET),october)[0].astimezone(timezone.utc).hour,13)
        self.assertEqual(core.session_bounds(NOW,sessions)[0],OPEN)
        with self.assertRaises(ValueError): core.session_bounds(NOW,{})
        with self.assertRaises(ValueError): core.session_bounds(NOW.replace(tzinfo=None),sessions)


class EventTests(Offline):
    def test_first_observation_qualifies_unknown_crossing_time(self):
        event=core.transition(None,observation())
        self.assertEqual(event['type'],'entered_oversold')
        self.assertEqual(event['qualification'],'first_observation_since_completed_close')
        self.assertEqual(event['previous']['session'],'2026-11-04')

    def test_full_precision_boundary_recovery_and_repeat(self):
        self.assertEqual(core.transition(observation(20,3),observation(19.999999999,6))['type'],'entered_oversold')
        self.assertIsNone(core.transition(observation(21,3),observation(20,6)))
        self.assertEqual(core.transition(observation(19,3),observation(20,6))['type'],'recovered')
        self.assertEqual(core.transition(None,observation(baseline=19))['type'],'already_oversold')
        self.assertEqual(core.transition(observation(20,3),observation(19,10))['qualification'],'observation_gap')

    def test_restart_duplicates_once_per_session_and_immutable_evidence(self):
        ledger=self.ledger()
        first=ledger.record(observation(),send=True)
        self.assertEqual(first['policy'],'send_reserved')
        ledger.outcome(first['id'],'api_accepted',NOW.isoformat())
        ledger2=Ledger(self.path)
        try:
            self.assertIsNone(ledger2.record(observation(),send=True))
            self.assertIsNone(ledger2.record(observation(18,7),send=True))
            self.assertEqual(ledger2.record(observation(21,8),send=True)['type'],'recovered')
            again=ledger2.record(observation(17,9),send=True)
            self.assertEqual(again['policy'],'duplicate_session_suppressed')
            self.assertEqual(ledger2.db.execute('SELECT count(*) FROM attempts').fetchone()[0],1)
            events=read_view(self.path)['events']
            self.assertEqual(events[-1]['current']['k'],19)
            self.assertEqual(events[-1]['delivery'],'api_accepted')
        finally: ledger2.close()

    def test_missing_interval_records_qualified_transition_without_send(self):
        ledger=self.ledger()
        ledger.record(observation(25,3),send=True)
        ledger.degraded('XOM')
        event=ledger.record(observation(19,6),send=True)
        self.assertEqual(event['qualification'],'observation_gap')
        self.assertEqual(event['policy'],'gap_suppressed')
        self.assertEqual(ledger.db.execute('SELECT count(*) FROM attempts').fetchone()[0],0)

    def test_preview_never_replayed_as_live_notification(self):
        ledger=self.ledger()
        self.assertEqual(ledger.record(observation())['policy'],'preview_only')
        ledger.record(observation(25,7),send=True)
        self.assertEqual(ledger.record(observation(19,8),send=True)['policy'],'duplicate_session_suppressed')

    def test_new_session_resets_baseline_not_prior_intraday_reading(self):
        ledger=self.ledger(); ledger.record(observation())
        nextday=observation(18,baseline=21)
        for k in ('session',): nextday[k]='2026-11-06'
        for k in ('observed','detected'): nextday[k]=nextday[k].replace('2026-11-05','2026-11-06')
        self.assertEqual(ledger.record(nextday,send=True)['policy'],'send_reserved')

    def test_completed_result_does_not_rewrite_provisional_event(self):
        ledger=self.ledger(); event=ledger.record(observation())
        self.assertEqual(ledger.pending_completions(),[('XOM','2026-11-05')])
        ledger.complete('XOM','2026-11-05',dict(k=24,d=25,remained_oversold_at_close=False,observed=CLOSE.isoformat()))
        retained=read_view(self.path)['events'][0]
        self.assertEqual(retained['current']['k'],19)
        self.assertFalse(retained['completed_result']['remained_oversold_at_close'])
        self.assertEqual(retained['id'],event['id'])
        self.assertEqual(ledger.pending_completions(),[])


class MonitorTests(Offline):
    def provider(self, obs=None, failures=None):
        provider=Mock()
        provider.sessions={str(OPEN.date()):dict(start='09:30',end='16:00')}
        result=copy.deepcopy(obs or observation())
        result.update(history_evidence=[],minute_evidence=payload(),calendar_evidence={})
        provider.poll.return_value=(dict(state='Regular session'),[result],failures or {})
        provider.completed.return_value=None
        return provider

    def test_intent_committed_before_transport_and_uncertain_send_not_retried(self):
        ledger=self.ledger(); provider=self.provider(); calls=[]
        def notify(event):
            calls.append(event)
            self.assertEqual(read_view(self.path)['events'][0]['delivery'],'intent_uncertain')
            raise TimeoutError('synthetic-secret')
        realtime.run_once(provider,ledger,send=True,notify=notify,clock=lambda:NOW)
        realtime.run_once(provider,ledger,send=True,notify=notify,clock=lambda:NOW)
        self.assertEqual(len(calls),1)
        self.assertEqual(read_view(self.path)['events'][0]['delivery'],'acceptance_unknown')
        self.assertEqual(ledger.db.execute('SELECT count(*) FROM evidence').fetchone()[0],1)

    def test_accepted_is_not_phone_receipt_and_preview_does_not_load_secrets(self):
        ledger=self.ledger(); provider=self.provider(); notify=Mock()
        realtime.run_once(provider,ledger,notify=notify,clock=lambda:NOW)
        notify.assert_not_called()
        self.assertEqual(read_view(self.path)['events'][0]['delivery'],'No send attempted')

    def test_after_close_stale_and_acquisition_failure_cannot_alert(self):
        for at in (CLOSE,NOW+timedelta(minutes=10)):
            ledger=self.ledger(); notify=Mock()
            realtime.run_once(self.provider(),ledger,send=True,notify=notify,clock=lambda:at)
            notify.assert_not_called()
            self.assertEqual(read_view(self.path)['events'],[])
        provider=self.provider(); provider.poll.side_effect=TimeoutError('secret')
        ledger=self.ledger()
        realtime.run_once(provider,ledger,send=True,notify=Mock(),clock=lambda:NOW)
        self.assertEqual(len(read_view(self.path)['latest']),19)

    def test_pushover_size_status_and_timestamp_qualification(self):
        for before in (None,observation(21,3)):
            event=core.transition(before,observation())
            body=realtime.alert_body(event)
            self.assertLessEqual(len(body),1024)
            for text in ('XOM','Previous K','Current K','Price','Detected','Provisional daily','Not yet confirmed','unknown'):
                self.assertIn(text,body)
        event=core.transition(None,observation())
        with patch.object(realtime,'load_credentials',return_value=('synthetic','synthetic')), patch.object(realtime,'_send_message') as send:
            realtime.send_alert(event)
            send.assert_called_once()
            self.assertEqual(send.call_args.kwargs['title'],realtime.TITLE)

    def test_provider_adapter_fixed_regular_hours_contract_and_history_coverage(self):
        provider=intraday_provider.Provider(clock=lambda:NOW)
        provider.checked=OPEN.date()
        provider.sessions={str(b.session):dict(start='09:30',end='16:00') for b in history()}
        provider.sessions[str(OPEN.date())]=dict(start='09:30',end='16:00')
        # Less than 100 completed sessions fails closed, no minute call.
        fake=Mock(bars=history())
        with patch.object(intraday_provider,'load_token',return_value='synthetic'), patch.object(intraday_provider,'fetch_history',return_value=fake), patch.object(intraday_provider,'_get_json') as get:
            status,results,failures=provider.poll()
        self.assertEqual(len(failures),19); self.assertEqual(results,[]); get.assert_not_called()

    def test_provider_auth_failure_stops_batch(self):
        provider=intraday_provider.Provider(clock=lambda:NOW)
        provider.checked=OPEN.date()
        provider.sessions={str(OPEN.date()):dict(start='09:30',end='16:00'),'2026-11-04':dict(start='09:30',end='16:00')}
        with patch.object(intraday_provider,'load_token',return_value='synthetic'), patch.object(intraday_provider,'fetch_history',side_effect=tradier.TradierError('safe',stop_batch=True)) as fetch:
            status,results,failures=provider.poll()
        self.assertEqual(fetch.call_count,1); self.assertEqual(len(failures),19)

    def test_all_nineteen_acquire_current_candle_and_reuse_history(self):
        provider=intraday_provider.Provider(clock=lambda:NOW)
        provider.checked=OPEN.date()
        for month in range(2,12):
            provider.sessions.update(normalize_calendar(month_payload(2026,month),2026,month))
        def fetch(token,**kwargs):
            bars=tuple(DailyOHLC(date.fromisoformat(d),60,110,10,35) for d,h in sorted(provider.sessions.items())
                       if h and str(kwargs['start'])<=d<=str(kwargs['completed_through']))
            return Mock(bars=bars)
        with patch.object(intraday_provider,'load_token',return_value='synthetic'), patch.object(intraday_provider,'fetch_history',side_effect=fetch) as history_fetch, patch.object(intraday_provider,'_get_json',return_value=payload()) as minute_fetch:
            status,results,failures=provider.poll()
            self.assertEqual(status['usable'],19); self.assertEqual(failures,{})
            self.assertEqual({r['symbol'] for r in results},set(SYMBOLS))
            self.assertTrue(all(r['k']<20 for r in results))
            self.assertEqual(history_fetch.call_count,19)
            for call in minute_fetch.call_args_list:
                self.assertEqual(call.args[2],'timesales')
                self.assertEqual(call.args[3]['session_filter'],'open')
                self.assertEqual(call.args[3]['interval'],'1min')
                self.assertEqual(call.args[3]['start'],'2026-11-05 09:30')
            provider.poll()
            self.assertEqual(history_fetch.call_count,19)
            self.assertEqual(minute_fetch.call_count,38)

    def test_notification_reserved_once_with_two_simultaneous_writers(self):
        self.ledger()
        barrier=threading.Barrier(2); policies=[]; errors=[]
        def writer():
            ledger=Ledger(self.path)
            try:
                barrier.wait(timeout=2)
                event=ledger.record(observation(),send=True)
                policies.append(event['policy'] if event else None)
            except Exception as error: errors.append(type(error).__name__)
            finally: ledger.close()
        threads=[threading.Thread(target=writer) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=4)
        self.assertEqual(errors,[])
        self.assertCountEqual(policies,['send_reserved',None])

    def test_completed_followup_waits_for_calendar_close_and_retains_separate_history(self):
        provider=intraday_provider.Provider(clock=lambda:NOW)
        provider.sessions={str(OPEN.date()):dict(start='09:30',end='16:00')}
        with patch.object(intraday_provider,'fetch_history') as fetch:
            self.assertIsNone(provider.completed('XOM','2026-11-05'))
            fetch.assert_not_called()

    def test_cli_realtime_symbol_routes_to_existing_server_and_browser(self):
        server=Mock(); server.server_port=8765; server.serve_forever.side_effect=KeyboardInterrupt
        context=Mock(); context.__enter__=Mock(return_value=server); context.__exit__=Mock(return_value=False)
        with patch.object(report_history,'make_server',return_value=context) as make, patch.object(report_history.threading,'Thread') as thread:
            self.assertEqual(report_history.main(['--realtime','XOM','--state',str(self.path)],open_browser=True),0)
            self.assertEqual(make.call_args.kwargs['live_state'],self.path)
            self.assertEqual(thread.call_args.kwargs['args'],('http://127.0.0.1:8765/realtime/XOM',))


class PresentationTests(Offline):
    def test_all_symbols_focus_freshness_and_completed_relationship(self):
        ledger=self.ledger(); ledger.record(observation())
        ledger.status(dict(state='Regular session',checked=NOW.isoformat(),usable=1,failures={'CLX':'Minute gaps'}))
        html=realtime_view.live_page(self.path,now=NOW)
        for symbol in SYMBOLS: self.assertIn('>'+symbol+'</a>',html)
        for phrase in ('Provisional K','Completed K','Fresh','Minute gaps','first_observation_since_completed_close'):
            self.assertIn(phrase,html)
        focused=realtime_view.live_page(self.path,'XOM',now=NOW)
        self.assertIn('Developing daily candle',focused)
        self.assertNotIn('>CVX</a>',focused)
        self.assertIn('Degraded / stale',realtime_view.live_page(self.path,now=CLOSE))

    def test_missing_state_read_only(self):
        self.assertIn('No intraday observations',realtime_view.live_page(self.path))
        self.assertFalse(self.path.exists())

    def test_http_routes_readonly_host_protection_and_refresh(self):
        server=report_history.make_server(Path(self.tmp.name),0,live_state=self.path)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
            conn.request('GET','/realtime/XOM'); response=conn.getresponse()
            self.assertEqual(response.status,200); self.assertEqual(response.getheader('Refresh'),'15')
            self.assertIn('Developing daily candle',response.read().decode()); conn.close()
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
            conn.request('POST','/realtime'); response=conn.getresponse(); self.assertEqual(response.status,405); response.read();conn.close()
        finally: server.shutdown();server.server_close();thread.join()


if __name__=='__main__': unittest.main()
