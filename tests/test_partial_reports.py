"""Offline symbol isolation, durable partial delivery and bounded recovery."""
import copy
import json
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from market_sentinel import scheduled_report as worker, tradier, daily_report
from market_sentinel.universe import SYMBOLS
from test_daily_report import screening, row_lines
import test_scheduled_report as support

ACQUIRE = worker.acquire_screening
NOW = support.NOW


class PartialReportTests(unittest.TestCase):
    setUp = support.WorkerTests.setUp
    saved = support.WorkerTests.saved

    def provider(self, token, **kw):
        error = self.failures.get(kw['symbol'])
        if isinstance(error, Exception): raise error
        rows, day = [], kw['start']
        while day <= kw['end']:
            if day.weekday() < 5:
                rows.append(dict(date=str(day), open=60, high=110, low=10, close=60, volume=100))
            day += timedelta(days=1)
        if error == 'invalid': rows[-5]['low'] = 'NaN'
        if error == 'missing': rows.pop(-4)
        if error == 'old': rows.insert(0, dict(date='2026-03-19', open='NaN', high='NaN', low='NaN', close=100))
        return tradier.normalize_history(dict(history=dict(day=rows)), **kw)

    def real_acquisition(self, failures):
        self.failures = failures
        patch.object(worker, 'acquire_screening', side_effect=ACQUIRE).start()
        self.fetch = patch.object(worker, 'fetch_history', side_effect=self.provider).start()

    def initial(self):
        return self.saved()['deliveries']['2026-11-02:opening']

    def test_xom_timeout_still_evaluates_all_peers_and_sends_one_partial(self):
        self.real_acquisition({'XOM': tradier.TradierError('Tradier network/TLS failure or timeout; history not verified.')})
        self.assertEqual(worker.run_once(self.root, NOW), 0)
        self.assertEqual(self.fetch.call_count, 19)
        self.assertEqual(self.send.call_count, 1)
        body = self.send.call_args.args[3]
        self.assertIn('18/19 available', body)
        self.assertIn('XOM  -- -- Unavailable', body)
        self.assertIn('Crossings: 0 known; 1 unavailable', body)
        self.assertEqual({line.split()[0] for line in row_lines(body)}, set(SYMBOLS))
        self.assertEqual(self.send.call_args.args[2], worker.TITLE)
        self.assertNotIn('failure_alert', self.initial())
        self.assertEqual(self.initial()['status'], 'accepted')
        self.assertEqual(self.initial()['recovery']['id'], '2026-11-02:opening:recovery')
        report = worker.read_progress(self.root, dict(id='2026-11-02:opening', session='2026-10-30'))
        self.assertEqual(report['summary']['usable_latest_symbols'], 18)
        self.assertNotIn('latest', next(row for row in report['results'] if row['symbol']=='XOM'))

    def test_invalid_or_missing_one_symbol_does_not_suppress_other_symbols(self):
        for problem in ('invalid', 'missing'):
            with self.subTest(problem=problem), patch.object(worker, 'fetch_history', side_effect=self.provider):
                self.failures = {'XOM': problem}
                report = ACQUIRE('synthetic', date(2026,10,30), support.sessions())
                self.assertEqual(report['summary']['usable_latest_symbols'], 18)
                bad = next(row for row in report['results'] if row['symbol']=='XOM')
                self.assertNotIn('latest', bad)
                self.assertIn('XOM  -- -- Unavailable', worker.notification_body(report, dict(kind='opening', observation='2026-11-02', session='2026-10-30')))

    def test_old_invalid_data_does_not_interfere(self):
        self.real_acquisition({'CLX': 'old'})
        worker.run_once(self.root, NOW)
        self.assertEqual(self.initial()['available_symbols'], 19)
        self.assertNotIn('recovery', self.initial())
        report = json.loads((self.root/self.initial()['evidence_file']).read_text())
        self.assertIn('2026-03-19', report['results'][0]['invalid_old_sessions'])

    def test_all_symbol_failure_is_one_unavailable_report_with_recovery_status(self):
        self.real_acquisition({symbol: tradier.TradierError('Tradier network/TLS failure or timeout; history not verified.') for symbol in SYMBOLS})
        worker.run_once(self.root, NOW)
        self.assertEqual(self.fetch.call_count, 19)
        self.assertEqual(self.send.call_count, 1)
        body = self.send.call_args.args[3]
        self.assertIn('0/19 available', body)
        self.assertIn('19 unavailable', body)
        self.assertIn('Reasons: network', body)
        self.assertIn('Recovery: retry missing in 15m', body)
        self.assertEqual(len(row_lines(body)), 19)
        self.assertNotIn('failure_alert', self.initial())
        self.assertLessEqual(len(body), 1024)

    def test_authentication_and_quota_stop_requests_and_disclose_unattempted(self):
        for message in ('Tradier authentication/entitlement rejected.', 'Tradier rate limit reached.'):
            with self.subTest(message=message), patch.object(worker, 'fetch_history', side_effect=self.provider) as fetch:
                self.failures = {'CVX': tradier.TradierError(message, stop_batch=True)}
                report = ACQUIRE('synthetic', date(2026,10,30), support.sessions())
                self.assertEqual(fetch.call_count, 3)
                self.assertEqual(report['summary']['usable_latest_symbols'], 2)
                self.assertEqual(sum(row.get('attempted') is False for row in report['results']), 16)
                body = worker.notification_body(report, dict(kind='opening', observation='2026-11-02', session='2026-10-30'))
                self.assertIn('Not requested: NUE,ADM', body)
                self.assertLessEqual(len(body), 1024)

    def test_retries_only_unresolved_and_one_recovery_update_across_restarts(self):
        self.real_acquisition({'XOM': tradier.TradierError('Tradier network/TLS failure.')})
        worker.run_once(self.root, NOW)
        initial = copy.deepcopy(self.initial())
        original_evidence = (self.root/initial['evidence_file']).read_bytes()
        progress = worker.read_progress(self.root, dict(id=initial['id'], session=initial['session']))
        retained = [row for row in progress['results'] if row['symbol'] != 'XOM']
        self.fetch.reset_mock()
        worker.run_once(self.root, NOW+timedelta(minutes=1))
        self.fetch.assert_not_called()
        worker.run_once(self.root, NOW+timedelta(minutes=15))
        self.assertEqual([call.kwargs['symbol'] for call in self.fetch.call_args_list], ['XOM'])
        self.assertEqual(self.send.call_count, 1)  # No repeated partials/alerts.
        self.failures.clear()
        worker.run_once(self.root, NOW+timedelta(minutes=30))
        self.assertEqual([call.kwargs['symbol'] for call in self.fetch.call_args_list], ['XOM', 'XOM'])
        self.assertEqual(self.send.call_count, 2)
        self.assertTrue(self.send.call_args.args[3].startswith('UPDATE Opening 2026-11-02 ET'))
        self.assertIn('19/19 available', self.send.call_args.args[3])
        state = self.initial()
        self.assertEqual(state['accepted'], initial['accepted'])
        self.assertEqual(state['recovery']['status'], 'accepted')
        self.assertEqual((self.root/state['evidence_file']).read_bytes(), original_evidence)
        recovered = json.loads((self.root/state['recovery']['evidence_file']).read_text())
        self.assertEqual([row for row in recovered['results'] if row['symbol']!='XOM'], retained)
        worker.run_once(self.root, NOW+timedelta(minutes=45))
        self.assertEqual(self.send.call_count, 2)
        self.assertEqual(self.fetch.call_count, 2)

    def test_incremental_recovery_retains_newly_successful_symbols(self):
        self.real_acquisition({s: tradier.TradierError('Tradier network/TLS failure.') for s in ('CLX','XOM')})
        worker.run_once(self.root,NOW)
        self.fetch.reset_mock()
        del self.failures['CLX']
        worker.run_once(self.root,NOW+timedelta(minutes=15))
        self.assertEqual([c.kwargs['symbol'] for c in self.fetch.call_args_list],['CLX','XOM'])
        self.assertEqual(self.initial()['recovery']['unresolved_symbols'],['XOM'])
        self.fetch.reset_mock(); self.failures.clear()
        worker.run_once(self.root,NOW+timedelta(minutes=30))
        self.assertEqual([c.kwargs['symbol'] for c in self.fetch.call_args_list],['XOM'])
        self.assertEqual(self.send.call_count,2)

    def test_ready_recovery_waits_for_credentials_without_refetching_or_alerting(self):
        self.real_acquisition({'XOM':tradier.TradierError('Tradier network/TLS failure.')})
        worker.run_once(self.root,NOW)
        self.failures.clear(); self.credentials.side_effect=RuntimeError('synthetic-secret')
        worker.run_once(self.root,NOW+timedelta(minutes=15))
        self.assertEqual(self.fetch.call_count,20)
        self.assertEqual(self.send.call_count,1)
        self.assertNotIn('failure_alert',self.initial()['recovery'])
        self.credentials.side_effect=None
        worker.run_once(self.root,NOW+timedelta(minutes=30))
        self.assertEqual(self.fetch.call_count,20)
        self.assertEqual(self.send.call_count,2)
        self.assertEqual(self.initial()['recovery']['status'],'accepted')

    def test_legacy_accepted_full_slot_is_not_replayed_or_given_recovery(self):
        state=self.saved()
        old=dict(id='2026-11-02:opening',status='accepted',accepted='2026-11-02T14:31:10+00:00')
        state['deliveries'][old['id']]=old
        worker.save_json(self.root/'state.json',state)
        worker.run_once(self.root,NOW)
        self.assertEqual(self.initial(),old)
        self.acquire.assert_not_called(); self.send.assert_not_called()

    def test_pending_legacy_failure_alert_does_not_suppress_partial_report(self):
        self.real_acquisition({'XOM':tradier.TradierError('Tradier network/TLS failure.')})
        state=self.saved()
        alert=dict(status='accepted',accepted='2026-11-02T14:31:20+00:00')
        state['deliveries']['2026-11-02:opening']=dict(status='waiting',failure_alert=alert)
        worker.save_json(self.root/'state.json',state)
        worker.run_once(self.root,NOW)
        self.assertEqual(self.initial()['failure_alert'],alert)
        self.assertEqual(self.initial()['status'],'accepted')
        self.assertEqual(self.send.call_count,1)
        self.assertEqual(self.send.call_args.args[2],worker.TITLE)

    def test_unknown_initial_send_does_not_trigger_replay_or_recovery(self):
        self.real_acquisition({'XOM': tradier.TradierError('Tradier network/TLS failure.')})
        self.send.side_effect = TimeoutError('synthetic-secret')
        worker.run_once(self.root, NOW)
        worker.run_once(self.root, NOW+timedelta(minutes=15))
        self.assertEqual(self.initial()['status'], 'unknown')
        self.assertNotIn('recovery', self.initial())
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.fetch.call_count, 19)

    def test_unknown_recovery_send_does_not_resend_and_keeps_initial_acceptance(self):
        self.real_acquisition({'XOM': tradier.TradierError('Tradier network/TLS failure.')})
        worker.run_once(self.root, NOW)
        self.failures.clear()
        self.send.side_effect = TimeoutError('synthetic-secret')
        worker.run_once(self.root, NOW+timedelta(minutes=15))
        worker.run_once(self.root, NOW+timedelta(minutes=30))
        self.assertEqual(self.initial()['status'], 'accepted')
        self.assertEqual(self.initial()['recovery']['status'], 'unknown')
        self.assertEqual(self.send.call_count, 2)
        self.assertEqual(self.fetch.call_count, 20)

    def test_expire_old_recovery_when_newer_same_type_due(self):
        self.real_acquisition({'XOM': tradier.TradierError('Tradier network/TLS failure.')})
        worker.run_once(self.root, NOW)
        with patch.object(worker, 'notification_body', return_value='synthetic closing report'):
            worker.run_once(self.root, NOW.replace(hour=17))
        self.assertEqual(self.initial()['recovery']['status'], 'waiting')  # Closing does not supersede opening.
        self.failures.clear()
        worker.run_once(self.root, NOW.replace(day=3, hour=9, minute=31))
        self.assertEqual(self.initial()['recovery']['status'], 'expired')
        self.assertIn('Newer opening', self.initial()['recovery']['reason'])
        self.assertEqual(self.saved()['deliveries']['2026-11-03:opening']['status'], 'accepted')
        self.assertFalse(any('UPDATE Opening 2026-11-02' in call.args[3] for call in self.send.call_args_list))

    def test_interrupted_recovery_intent_becomes_unknown_without_http(self):
        self.real_acquisition({'XOM': tradier.TradierError('Tradier network/TLS failure.')})
        worker.run_once(self.root, NOW)
        state = self.saved()
        state['deliveries']['2026-11-02:opening']['recovery']['status'] = 'attempting'
        worker.save_json(self.root/'state.json', state)
        worker.run_once(self.root, NOW+timedelta(minutes=15))
        self.assertEqual(self.initial()['recovery']['status'], 'unknown')
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.fetch.call_count, 19)

    def test_progress_slot_or_session_mismatch_never_mixes_or_sends_update(self):
        self.real_acquisition({'XOM': tradier.TradierError('Tradier network/TLS failure.')})
        worker.run_once(self.root, NOW)
        slot = dict(id='2026-11-02:opening', session='2026-10-30')
        report = worker.read_progress(self.root, slot)
        report['summary']['completed_session'] = '2026-10-29'
        worker.save_json(worker.progress_path(self.root, slot), report)
        worker.run_once(self.root, NOW+timedelta(minutes=15))
        self.assertEqual(self.send.call_count, 1)
        self.assertIn('does not match', self.initial()['recovery']['last_failure']['status'])

    def test_calculation_contract_failure_is_isolated(self):
        with patch.object(worker, 'fetch_history', side_effect=self.provider), patch.object(worker, 'history_report', wraps=worker.history_report) as calculate:
            self.failures = {}
            original = worker.history_report.__wrapped__ if hasattr(worker.history_report, '__wrapped__') else calculate._mock_wraps
            def result(history):
                row = original(history)
                if history.symbol=='XOM': row['latest']['k'] = float('nan')
                return row
            calculate.side_effect = result
            report = ACQUIRE('synthetic', date(2026,10,30), support.sessions())
        self.assertEqual(report['summary']['usable_latest_symbols'], 18)
        self.assertNotIn('latest', next(row for row in report['results'] if row['symbol']=='XOM'))

    def test_transport_sees_durable_separate_intents_and_full_evidence(self):
        self.real_acquisition({'XOM': tradier.TradierError('Tradier network/TLS failure.')})
        def send(*args, **kw):
            record = self.initial()
            entry = record['recovery'] if args[3].startswith('UPDATE') else record
            self.assertEqual(entry['status'], 'attempting')
            self.assertTrue((self.root/entry['evidence_file']).exists())
        self.send.side_effect = send
        worker.run_once(self.root, NOW)
        self.failures.clear()
        worker.run_once(self.root, NOW+timedelta(minutes=15))
        self.assertEqual(self.send.call_count, 2)

    def test_credentials_missing_produces_one_useful_unavailable_report(self):
        self.real_acquisition({})
        self.token.side_effect = tradier.TradierError('Market-data credentials unavailable.')
        # Calendar is already cached so no market-data authorization is needed to select the slot.
        state = self.saved()
        for month in (8,9,10,11):
            days = worker.normalize_calendar(support.month_payload(2026,month),2026,month)
            state['calendars'][f'2026-{month:02}'] = dict(checked='2026-11-02',days=days)
        worker.save_json(self.root/'state.json',state)
        worker.run_once(self.root,NOW)
        self.fetch.assert_not_called()
        self.assertEqual(self.send.call_count,1)
        self.assertIn('0/19 available',self.send.call_args.args[3])
        self.assertIn('Not requested:',self.send.call_args.args[3])


class MessageBudgetTests(unittest.TestCase):
    def test_every_coverage_and_worst_numeric_width_preserves_all_symbols(self):
        for missing in range(20):
            rows = screening()['results']
            for i, row in enumerate(rows):
                if i < missing:
                    rows[i] = dict(symbol=row['symbol'],status='failed',failure_kind=('history','network','calculation','access','quota')[i%5],attempted=i%2==0,error='Synthetic failure')
                else:
                    row['latest'].update(close=1.234e250,k=1.234e200,d=1.234e200)
            report = worker.screening_result(date(2026,10,30),rows)
            slot = dict(kind='closing',observation='2026-11-02',session='2026-10-30')
            body = worker.notification_body(report,slot)
            self.assertLessEqual(len(body),1024)
            self.assertEqual({line.split()[0] for line in row_lines(body)},set(SYMBOLS))
            if not missing:
                self.assertLessEqual(len(worker.notification_body(report,slot,recovery=True)),1024)

    def test_compact_demonstration_still_identifies_nonlive_data(self):
        body=daily_report.format_daily_report(screening(),compact=True,demonstration=True)
        self.assertTrue(body.startswith('DEMONSTRATION'))
        self.assertIn('Not a live scheduled result',body)
