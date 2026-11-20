"""Offline pre-close preview contracts; no network, Keychain or live pushes."""
import copy
from datetime import date, datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch, MagicMock

from market_sentinel import preclose as p, scheduled_report as w, tradier, pushover
from market_sentinel.universe import SYMBOLS
import test_scheduled_report as support

NOW=datetime(2026,11,2,15,30,tzinfo=w.ET)
SLOT=dict(id='2026-11-02:preclose',kind='preclose',observation='2026-11-02',session='2026-11-02',
          due='2026-11-02T15:30:00-05:00',expires='2026-11-02T16:00:00-05:00')


def minutes(now=NOW):
    at=now.replace(hour=9,minute=30,second=0,microsecond=0);rows=[]
    while at<=now:
        rows.append(dict(timestamp=int(at.timestamp()),time=at.replace(tzinfo=None).isoformat(),
                         open=35,high=110,low=10,close=11))
        at+=timedelta(minutes=1)
    return dict(series=dict(data=rows))


def history(token,**kw):
    at=kw['start'];rows=[]
    while at<=kw['end']:
        if at.weekday()<5:rows.append(dict(date=str(at),open=35,high=110,low=10,close=35))
        at+=timedelta(days=1)
    return tradier.normalize_history(dict(history=dict(day=rows)),**kw)


def snapshot():
    rows=[]
    for symbol in SYMBOLS:
        rows.append(dict(symbol=symbol,status='calculated',provisional_session=SLOT['session'],
            latest=dict(k=17.,d=22.,close=11.,crossing_available=True,crossed_below_20=True),
            crossed_above_20=False,previous_k=25.,data_timestamp=NOW.isoformat(),warnings=[],warning_count=0))
    r=w.screening_result(date(2026,10,30),rows)
    r.update(provisional=True);r['summary']['provisional_session']=SLOT['session']
    return r


class CalendarTests(unittest.TestCase):
    def test_normal_session_boundaries_and_completed_reports_unchanged(self):
        days=support.sessions()
        for time,expected in ((NOW-timedelta(seconds=1),0),(NOW,1),(NOW.replace(hour=16,minute=0),0)):
            self.assertEqual(len(w.due_previews(time,date(2026,11,2),days)),expected)
        slot=w.due_previews(NOW,date(2026,11,2),days)[0]
        self.assertEqual(slot,SLOT)
        opening=w.due_reports(NOW,date(2026,11,2),days)
        self.assertEqual([r['kind'] for r in opening],['opening'])
        closing=w.due_reports(NOW.replace(hour=16,minute=1),date(2026,11,2),days)
        self.assertEqual([r['kind'] for r in closing],['opening','closing'])

    def test_early_close_holiday_weekend_and_timezone(self):
        days=support.sessions();days['2026-11-27']['end']='13:00';days['2026-11-26']=None
        at=datetime(2026,11,27,12,30,tzinfo=w.ET)
        result=w.due_previews(at.astimezone(timezone.utc),date(2026,11,2),days)
        self.assertIn('12:30:00',result[0]['due']);self.assertIn('13:00:00',result[0]['expires'])
        for at in (at.replace(day=26),at.replace(day=28),at.replace(hour=13,minute=0)):
            self.assertEqual(w.due_previews(at,date(2026,11,2),days),[])
        # EDT close remains 15:30 local before the autumn transition.
        at=datetime(2026,10,30,15,30,tzinfo=w.ET)
        self.assertTrue(w.due_previews(at,date(2026,10,30),days)[0]['due'].endswith('-04:00'))


class AcquisitionTests(unittest.TestCase):
    def acquire(self,payload=None,side_effect=None):
        with patch.object(p,'fetch_history',side_effect=history) as fetch,patch.object(p,'_get_json',side_effect=side_effect,return_value=payload or minutes()) as get:
            report=p.acquire('synthetic',SLOT,support.sessions(),lambda:NOW)
        return report,fetch,get

    def test_verified_intraday_inputs_form_one_provisional_bar_and_crossing(self):
        report,fetch,get=self.acquire()
        self.assertEqual(fetch.call_count,19);self.assertEqual(get.call_count,19)
        self.assertEqual(report['summary']['usable_latest_symbols'],19)
        self.assertEqual(report['summary']['completed_session'],'2026-10-30')
        self.assertEqual(report['summary']['provisional_session'],'2026-11-02')
        row=report['results'][0]
        self.assertEqual(len(row['history_bars']),18)
        self.assertEqual(row['provisional_bar'],dict(session='2026-11-02',open=35.,high=110.,low=10.,close=11.))
        self.assertEqual(row['latest']['k'],17.)
        self.assertTrue(row['latest']['crossed_below_20']);self.assertEqual(row['previous_k'],25.)
        kw=get.call_args.args[3];self.assertEqual(kw['interval'],'1min');self.assertEqual(kw['session_filter'],'open')
        self.assertTrue(kw['start'].endswith('09:30'));self.assertTrue(kw['end'].endswith('15:30'))

    def test_partial_sparse_minute_history_and_timeout_do_not_hide_peers(self):
        for fault in ('gap','stale','timeout','wrong_epoch','missing_open'):
            def source(token,env,endpoint,kw):
                value=minutes()
                if kw['symbol']=='XOM':
                    if fault=='gap':value['series']['data'].pop(30)
                    if fault=='stale':value['series']['data']=value['series']['data'][:-5]
                    if fault=='timeout':raise tradier.TradierError('Tradier network/TLS failure or timeout.')
                    if fault=='wrong_epoch':value['series']['data'][-1]['timestamp']+=60
                    if fault=='missing_open':value['series']['data'].pop(0)
                return value
            with self.subTest(fault=fault):
                r,_,_=self.acquire(side_effect=source)
                self.assertEqual(r['summary']['usable_latest_symbols'],18)
                row=next(row for row in r['results'] if row['symbol']=='XOM')
                self.assertNotIn('latest',row)
                self.assertIn('Unavailable: XOM',p.message(r,SLOT))

    def test_invalid_old_history_remains_excluded_and_in_window_invalid_unavailable(self):
        def fetch(token,**kw):
            h=history(token,**kw)
            if kw['symbol']=='XOM':raise tradier.TradierError('Structurally invalid required OHLC.')
            return h
        with patch.object(p,'fetch_history',side_effect=fetch),patch.object(p,'_get_json',return_value=minutes()):
            r=p.acquire('synthetic',SLOT,support.sessions(),lambda:NOW)
        self.assertEqual(r['summary']['usable_latest_symbols'],18)
        # Existing recent-history tests continue to exercise invalid March exclusion.
        self.assertEqual(r['calculation_policy']['completed_bars'],18)

    def test_finite_range_warnings_are_not_repaired_or_suppressed(self):
        value=minutes();value['series']['data'][-1]['close']=9
        r,_,_=self.acquire(value)
        self.assertEqual(r['summary']['usable_latest_symbols'],19)
        self.assertGreater(r['summary']['warning_count'],0)
        self.assertEqual(r['results'][0]['provisional_bar']['close'],9.)

    def test_quota_stops_remaining_provider_requests(self):
        def source(*args):raise tradier.TradierError('Tradier rate limit reached.',stop_batch=True)
        r,fetch,get=self.acquire(side_effect=source)
        self.assertEqual(fetch.call_count,1);self.assertEqual(get.call_count,1)
        self.assertEqual(r['summary']['usable_latest_symbols'],0)
        self.assertEqual(sum(row.get('attempted') is False for row in r['results']),18)

    def test_older_symbol_evidence_ages_out_while_newer_peers_remain_visible(self):
        clock=[NOW]
        def source(token,env,endpoint,kw):
            if kw['symbol']=='PEP':clock[0]+=timedelta(minutes=4)
            return minutes(clock[0])
        with patch.object(p,'fetch_history',side_effect=history),patch.object(p,'_get_json',side_effect=source):
            r=p.acquire('synthetic',SLOT,support.sessions(),lambda:clock[0])
        self.assertEqual(r['summary']['usable_latest_symbols'],1)
        self.assertEqual([row['symbol'] for row in r['results'] if 'latest' in row],['PEP'])
        self.assertIn('aged out',r['results'][0]['error'])

    def test_all_oversold_large_finite_scores_fit_and_preserve_names(self):
        r=snapshot()
        for row in r['results']:row['latest']['k']=-1.234e250
        body=p.message(r,SLOT)
        self.assertLessEqual(len(body),1024)
        self.assertTrue(all(symbol+' K ' in body for symbol in SYMBOLS))

    def test_message_order_full_precision_label_coverage_and_all_missing(self):
        r=snapshot()
        for row in r['results']:row['latest'].update(k=50,crossed_below_20=False)
        r['results'][0]['latest'].update(k=3.004,crossed_below_20=True)
        r['results'][1]['latest'].update(k=3.001,crossed_below_20=True)
        body=p.message(r,SLOT)
        self.assertLess(body.index('O K'),body.index('CLX K'))
        for text in ('Pre-close preview','PROVISIONAL','19/19 available','Data:','minute buckets','Below 20 vs prior close','intraday path unobserved'):
            self.assertIn(text,body)
        self.assertLessEqual(len(body),1024)
        r=w.screening_result(date(2026,10,30),[w.failed_symbol(s,tradier.TradierError('No minute data.')) for s in SYMBOLS])
        r.update(provisional=True);r['summary']['provisional_session']=SLOT['session']
        body=p.message(r,SLOT)
        self.assertIn('0/19 available',body);self.assertIn('0 known',body)
        self.assertTrue(all(s in body for s in SYMBOLS));self.assertLessEqual(len(body),1024)


class WorkerTests(unittest.TestCase):
    saved=support.WorkerTests.saved
    def setUp(self):
        support.WorkerTests.setUp(self)
        state=self.saved();state['deliveries']['2026-11-02:opening']=dict(status='accepted')
        w.save_json(self.root/'state.json',state)
        self.preview=patch.object(p,'acquire',return_value=snapshot()).start()

    def entry(self):return self.saved()['deliveries']['2026-11-02:preclose']

    def test_partial_preview_one_push_no_recovery_and_restart_no_duplicate(self):
        r=snapshot();r['results'][0]=w.failed_symbol('CLX',tradier.TradierError('Network unavailable.'))
        r['summary']['usable_latest_symbols']=18
        self.preview.return_value=r
        w.run_once(self.root,NOW)
        self.assertEqual(self.entry()['status'],'accepted');self.assertNotIn('recovery',self.entry())
        self.assertIn('18/19 available',self.send.call_args.args[3])
        self.assertEqual(self.send.call_args.args[2],p.TITLE)
        w.run_once(self.root,NOW+timedelta(minutes=15))
        self.assertEqual(self.send.call_count,1);self.assertEqual(self.preview.call_count,1)

    def test_preclose_priority_over_opening_recovery_backlog(self):
        state=self.saved();state['deliveries']={};w.save_json(self.root/'state.json',state)
        w.run_once(self.root,NOW)
        self.assertEqual(self.send.call_args.args[2],p.TITLE)
        self.acquire.assert_not_called()

    def test_close_expiry_on_wake_or_retry_and_accepted_daily_slots_unchanged(self):
        self.preview.side_effect=RuntimeError('synthetic-secret')
        w.run_once(self.root,NOW)
        self.assertEqual(self.entry()['status'],'waiting');self.send.assert_not_called()
        w.run_once(self.root,NOW.replace(hour=16,minute=0))
        self.assertEqual(self.entry()['status'],'expired');self.send.assert_not_called()
        self.assertEqual(self.saved()['deliveries']['2026-11-02:opening']['status'],'accepted')

    def test_no_missed_preview_created_after_close(self):
        w.run_once(self.root,NOW.replace(hour=16,minute=0))
        self.assertNotIn('2026-11-02:preclose',self.saved()['deliveries'])
        self.send.assert_not_called();self.preview.assert_not_called()

    def test_close_during_acquisition_or_credentials_prevents_send(self):
        for stage in ('acquisition','credentials'):
            with self.subTest(stage=stage):
                state=self.saved();state['deliveries'].pop('2026-11-02:preclose',None);w.save_json(self.root/'state.json',state)
                clock=[NOW.replace(hour=15,minute=59,second=59)]
                def delay(*args):clock[0]+=timedelta(seconds=2);return snapshot() if stage=='acquisition' else ('A'*30,'U'*30)
                self.preview.side_effect=delay if stage=='acquisition' else None
                self.credentials.side_effect=delay if stage=='credentials' else None
                w.run_once(self.root,clock[0],clock=lambda:clock[0])
                self.assertEqual(self.entry()['status'],'expired');self.send.assert_not_called()

    def test_final_transport_guard_after_request_preparation_prevents_late_http(self):
        clock=[NOW.replace(hour=15,minute=59,second=59)]
        real_send=pushover._send_message
        http=MagicMock()
        def build(*args):clock[0]+=timedelta(seconds=2);return http
        with patch.object(w,'_send_message',side_effect=real_send),patch.object(pushover,'build_opener',side_effect=build) as opener:
            w.run_once(self.root,clock[0],clock=lambda:clock[0])
        self.assertEqual(self.entry()['status'],'expired')
        http.open.assert_not_called()

    def test_expired_preview_does_not_delay_the_existing_closing_report(self):
        self.preview.side_effect=RuntimeError('synthetic-secret')
        w.run_once(self.root,NOW)
        result=self.acquire.return_value
        result['summary']['completed_session']='2026-11-02'
        for row in result['results']:row.update(last_session='2026-11-02',completed_through='2026-11-02')
        w.run_once(self.root,NOW.replace(hour=16,minute=1))
        self.assertEqual(self.entry()['status'],'expired')
        self.assertEqual(self.saved()['deliveries']['2026-11-02:closing']['status'],'accepted')
        self.assertEqual(self.send.call_count,1)
        self.assertTrue(self.send.call_args.args[3].startswith('Closing'))

    def test_uncertain_and_interrupted_preview_are_not_resent(self):
        self.send.side_effect=TimeoutError('synthetic-secret')
        w.run_once(self.root,NOW);self.assertEqual(self.entry()['status'],'unknown')
        w.run_once(self.root,NOW+timedelta(minutes=1));self.assertEqual(self.send.call_count,1)
        state=self.saved();state['deliveries']['2026-11-02:preclose']['status']='attempting';w.save_json(self.root/'state.json',state)
        w.run_once(self.root,NOW+timedelta(minutes=2));self.assertEqual(self.entry()['status'],'unknown')
        self.assertEqual(self.send.call_count,1)
