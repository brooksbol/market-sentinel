"""Synthetic report history and loopback HTTP tests. No provider/Keychain access."""

import copy
import hashlib
import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from market_sentinel import report_history as viewer
from market_sentinel.universe import SYMBOLS
from test_daily_report import screening


def write(root, name, value):
    (root / name).write_text(json.dumps(value), encoding='utf-8')


def evidence():
    value = screening()
    value['evidence_timestamp'] = '2026-11-02T14:32:08+00:00'
    value['results'][0]['latest'].update(k=19.23456789, d=22.56789123, crossed_below_20=True)
    value['results'][0].update(warning_count=1, status='calculated_with_warnings',
        warnings=[dict(session='2026-10-30', code='close_below_low', value=9, low=10, high=110,
                       excluded_from_calculation=False)],
        historical_crossings=[dict(session='2026-10-29', close=101, previous_k=20, k=19.3, d=21)])
    value['summary'].update(new_downward_crossings=1, warning_count=1, status='complete_with_warnings')
    return value


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write(self.root, '2026-11-02-opening.json', evidence())
        self.state = dict(version=1, deliveries={'2026-11-02:opening': dict(
            status='accepted', session='2026-10-30', due='2026-11-02T09:31:00-05:00',
            attempted='2026-11-02T14:31:01+00:00', accepted='2026-11-02T14:32:09+00:00')})
        self.save_state()

    def save_state(self):
        write(self.root, 'state.json', self.state)

    def test_newest_first_and_distinct_opening_closing_same_data_session(self):
        for identity in ['2026-10-30-closing', '2026-11-02-closing', '2026-11-03-opening']:
            write(self.root, identity + '.json', evidence())
        html = viewer.list_page(self.root)
        identities = ['2026-11-03-opening', '2026-11-02-closing', '2026-11-02-opening', '2026-10-30-closing']
        self.assertEqual(sorted(identities, key=lambda x: html.index('/reports/' + x)), identities)
        self.assertIn('2026-11-02 Opening', html)
        self.assertIn('2026-11-02 Closing', html)
        self.assertIn('2026-10-30', html)
        self.assertIn('2026-11-02T14:32:08+00:00', html)

    def test_reader_returns_source_data_without_html_or_starting_a_server(self):
        with patch.object(viewer, 'make_server', side_effect=AssertionError('no server startup')):
            records, notices = viewer.read_history(self.root)
        self.assertEqual(notices, [])
        self.assertEqual(records[0]['report'], evidence())
        self.assertEqual(records[0]['delivery']['status'], 'accepted')
        self.assertEqual(records[0]['identity'], '2026-11-02-opening')

    def test_detail_displays_full_universe_indicators_crossings_and_warning_evidence(self):
        html = viewer.detail_page(self.root, '2026-11-02-opening')
        for symbol in SYMBOLS:
            self.assertIn('<td>' + symbol + '</td>', html)
        for value in ['19.23456789', '22.56789123', 'close_below_low', '2026-10-29',
                      'Previous K', 'Excluded from calculation', 'Retained sample crossings']:
            self.assertIn(value, html)
        self.assertIn('<td>Yes</td>', html)
        self.assertIn('2026-11-02T14:32:09+00:00', html)
        self.assertNotIn('DEMONSTRATION', html)

    def test_delivery_states_are_not_phone_receipts(self):
        for status, expected in viewer.DELIVERY.items():
            self.state['deliveries']['2026-11-02:opening']['status'] = status
            self.save_state()
            html = viewer.detail_page(self.root, '2026-11-02-opening')
            self.assertIn(expected, html)
            self.assertIn('Device receipt: not recorded.', html)
            self.assertNotIn('Phone delivered', html)
        self.state['deliveries'] = {}
        self.save_state()
        self.assertIn('No notification attempt recorded', viewer.detail_page(self.root, '2026-11-02-opening'))

    def test_report_present_before_intent_is_not_an_acceptance_claim(self):
        self.state['deliveries'] = {}
        self.save_state()
        html = viewer.list_page(self.root)
        self.assertIn('Retained', html)
        self.assertIn('No attempt recorded', html)
        self.assertNotIn('Pushover API accepted</td>', html)

    def test_missing_report_remains_visible_from_ledger(self):
        (self.root / '2026-11-02-opening.json').unlink()
        self.assertIn('/reports/2026-11-02-opening', viewer.list_page(self.root))
        html = viewer.detail_page(self.root, '2026-11-02-opening')
        self.assertIn('missing or not yet retained', html)
        self.assertIn('Pushover API accepted', html)

    def test_missing_directory_is_not_created(self):
        missing = self.root / 'does-not-exist'
        self.assertIn('No retained reports found', viewer.list_page(missing))
        self.assertFalse(missing.exists())

    def test_malformed_reports_and_ledger_do_not_hide_other_reports_or_echo_raw_errors(self):
        write(self.root, '2026-11-03-closing.json', evidence())
        for value in ['{private-marker', '[]', '{"summary": [], "results": {}}']:
            (self.root / '2026-11-02-opening.json').write_text(value)
            self.assertIn('malformed', viewer.detail_page(self.root, '2026-11-02-opening'))
            self.assertIn('/reports/2026-11-03-closing', viewer.list_page(self.root))
        for state in [[], {'version': 3, 'deliveries': {}}, {'version': 1, 'deliveries': []}]:
            write(self.root, 'state.json', state)
            html = viewer.list_page(self.root)
            self.assertIn('ledger', html)
            self.assertNotIn('private-marker', html)

    def test_malformed_delivery_status_and_rows_are_graceful(self):
        for item in [[], {'status': []}, {'status': 'unrecognized'}]:
            self.state['deliveries']['2026-11-02:opening'] = item
            self.save_state()
            self.assertIn('malformed', viewer.detail_page(self.root, '2026-11-02-opening'))
        value = evidence()
        value['results'] = [None, {'symbol': [], 'latest': []}, value['results'][0]]
        value['summary']['status'] = 'incomplete'
        write(self.root, '2026-11-02-opening.json', value)
        html = viewer.detail_page(self.root, '2026-11-02-opening')
        self.assertIn('A symbol result is malformed', html)
        self.assertIn('Incomplete or inconsistent symbol coverage', html)
        self.assertIn('Missing signals are unknown', html)
        self.assertIn('19.23456789', html)

    def test_missing_indicators_and_warning_details_are_not_zeroed(self):
        value = evidence()
        row = value['results'][0]
        row['latest'].update(k=None, d=None, crossing_available=False, crossed_below_20=None)
        row['warnings'] = None
        value['summary']['status'] = 'incomplete'
        write(self.root, '2026-11-02-opening.json', value)
        html = viewer.detail_page(self.root, '2026-11-02-opening')
        self.assertIn('<td>CLX</td><td>100</td><td>Unknown</td><td>Unknown</td><td>Unknown</td>', html)
        self.assertIn('Warning details unavailable', html)

    def test_html_escaping_covers_fields_and_nested_warning_content(self):
        value = evidence()
        value['evidence_timestamp'] = '<script>attack()</script>'
        value['results'][0]['warnings'][0]['code'] = '<img src=x onerror=attack()>'
        write(self.root, '2026-11-02-opening.json', value)
        for html in [viewer.list_page(self.root), viewer.detail_page(self.root, '2026-11-02-opening')]:
            self.assertNotIn('<script>', html)
            self.assertIn('&lt;script&gt;', html)
        self.assertIn('&lt;img', viewer.detail_page(self.root, '2026-11-02-opening'))

    def test_invalid_unicode_field_is_unavailable_instead_of_breaking_response(self):
        value = evidence()
        value['results'][0]['warnings'][0]['code'] = '\ud800'
        write(self.root, '2026-11-02-opening.json', value)
        html = viewer.detail_page(self.root, '2026-11-02-opening')
        self.assertIn('Unknown (invalid text)', html)
        html.encode('utf-8')

    def test_symlinks_nonregular_files_and_unrecognized_names_are_not_served(self):
        (self.root / '2026-11-03-opening.json').symlink_to(self.root / 'state.json')
        os.mkfifo(self.root / '2026-11-03-closing.json')
        for name in ['2026-11-03-opening', '2026-11-03-closing']:
            self.assertIn('unreadable' if name.endswith('opening') else 'not a regular file',
                          viewer.detail_page(self.root, name))
        write(self.root, 'private.json', {'secret': 'private-marker'})
        self.assertNotIn('private-marker', viewer.list_page(self.root))
        for name in ['../state', '2026-02-30-opening', '2026-11-02-opening?download=1']:
            self.assertFalse(viewer.valid_slot(name))
            with patch.object(viewer, 'read_json', side_effect=AssertionError('no invalid-path read')):
                self.assertEqual(viewer.report(self.root, name), (None, 'Invalid report identity.'))

    def test_bounded_reads(self):
        with patch.object(viewer, 'MAX_JSON_BYTES', 8):
            self.assertIn('read limit', viewer.detail_page(self.root, '2026-11-02-opening'))

    def test_concurrent_atomic_replacement_is_read_again_without_cache_or_repair(self):
        original = viewer.read_json
        def replace_after_read(path):
            result = original(path)
            if path.name.endswith('opening.json'):
                state = copy.deepcopy(self.state)
                state['deliveries']['2026-11-02:opening']['session'] = '2026-11-02'
                write(self.root, 'replacement.json', state)
                os.replace(self.root / 'replacement.json', self.root / 'state.json')
            return result
        with patch.object(viewer, 'read_json', side_effect=replace_after_read):
            self.assertIn('data sessions disagree', viewer.detail_page(self.root, '2026-11-02-opening'))
        self.assertEqual(json.loads((self.root / 'state.json').read_text())['deliveries']
                         ['2026-11-02:opening']['session'], '2026-11-02')
        (self.root / 'state.json').write_text('{')
        self.assertIn('ledger unavailable', viewer.detail_page(self.root, '2026-11-02-opening'))
        self.save_state()
        self.assertNotIn('ledger unavailable', viewer.detail_page(self.root, '2026-11-02-opening'))

    def test_reads_do_not_mutate_any_runtime_bytes_or_load_operational_modules(self):
        def snapshot():
            return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                    for p in self.root.iterdir()}
        before = snapshot()
        viewer.list_page(self.root)
        viewer.detail_page(self.root, '2026-11-02-opening')
        self.assertEqual(snapshot(), before)
        source = ('import sys; import market_sentinel.report_history; '
                  'assert not any("market_sentinel."+n in sys.modules for n in '
                  '["pushover","tradier","scheduled_report","stochastic"])')
        subprocess.run([sys.executable, '-c', source], check=True, capture_output=True)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write(self.root, '2026-11-02-opening.json', evidence())
        self.server = viewer.make_server(self.root, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path='/', method='GET', headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.headers), response.read().decode()
        finally:
            connection.close()

    def test_loopback_binding_two_routes_and_no_store_security_headers(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        for path in ['/', '/reports/2026-11-02-opening']:
            status, headers, html = self.request(path)
            self.assertEqual(status, 200)
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
            self.assertIn('Market Sentinel', html)

    def test_foreign_host_origin_and_filesystem_paths_rejected(self):
        for headers in [{'Host': 'evil.example'}, {'Origin': 'https://evil.example'}]:
            self.assertEqual(self.request(headers=headers)[0], 403)
        for path in ['/state.json', '/worker.log', '/reports/../state.json', '/reports/%2e%2e%2fstate', '/?file=state.json']:
            self.assertEqual(self.request(path)[0], 404)

    def test_non_get_methods_cannot_write_and_gets_preserve_files(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        for method in ['POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']:
            self.assertEqual(self.request(method=method)[0], 405)
        self.request()
        self.request('/reports/2026-11-02-opening')
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir()}, before)


if __name__ == '__main__':
    unittest.main()
