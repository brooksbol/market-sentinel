"""On-demand, loopback-only reader of existing scheduled reports. Standard library only."""

import argparse
import json
import math
import os
import re
import stat
import sys
from datetime import date
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from market_sentinel.universe import SYMBOLS

RUNTIME = Path.home() / "Library/Application Support/Market Sentinel/automatic-reports"
SLOT = re.compile(r"(\d{4}-\d{2}-\d{2})-(opening|closing)")
MAX_JSON_BYTES = 16 * 1024 * 1024
DELIVERY = {
    "accepted": "Pushover API accepted",
    "attempting": "Attempt recorded; outcome not yet recorded",
    "unknown": "Acceptance unknown or push rejected; no automatic retry",
    "waiting": "Waiting; no acceptance recorded",
}


def valid_slot(value):
    match = SLOT.fullmatch(value)
    if not match:
        return False
    try:
        return date.fromisoformat(match[1]).isoformat() == match[1]
    except ValueError:
        return False


def read_json(path):
    """No creation, locks, symlink following, repair or retries on changing files."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return None, "Record is not a regular file."
            raw = stream.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            return None, "Record exceeds the viewer's read limit."
        value = json.loads(raw, parse_constant=lambda _: None)
        if not isinstance(value, dict):
            return None, "Record is malformed."
        return value, None
    except FileNotFoundError:
        return None, "Record is missing or not yet retained."
    except (OSError, ValueError, RecursionError):
        return None, "Record is unreadable, malformed or changing. Refresh to retry."


def ledger(root):
    state, error = read_json(root / "state.json")
    if error:
        return {}, "Delivery ledger unavailable. " + error
    if state.get("version") != 1 or not isinstance(state.get("deliveries"), dict):
        return {}, "Delivery ledger is malformed; delivery status is unavailable."
    return state["deliveries"], None


def report(root, identity):
    if not isinstance(identity, str) or not valid_slot(identity):
        return None, "Invalid report identity."
    value, error = read_json(root / (identity + ".json"))
    if error:
        return None, error
    if not isinstance(value.get("summary"), dict) or not isinstance(value.get("results"), list):
        return None, "Report summary or results are malformed."
    return value, None


def delivery_info(deliveries, identity):
    item = deliveries.get(identity.replace("-opening", ":opening").replace("-closing", ":closing"))
    if item is None:
        return {}, "No notification attempt recorded in this ledger snapshot"
    if (not isinstance(item, dict) or not isinstance(item.get("status"), str) or
            item["status"] not in DELIVERY):
        return {}, "Delivery record malformed; status unavailable"
    return item, DELIVERY[item["status"]]


def text(value):
    if value is None or isinstance(value, (dict, list)):
        return "Unknown"
    if type(value) is bool:
        return "Yes" if value else "No"
    if isinstance(value, float) and not math.isfinite(value):
        return "Unknown"
    try:
        rendered = str(value)
        rendered.encode('utf-8')
        return escape(rendered)
    except UnicodeError:
        return 'Unknown (invalid text)'


def table(headers, rows):
    return ('<div class="scroll"><table><thead><tr>' +
            ''.join('<th scope="col">' + escape(h) + '</th>' for h in headers) +
            '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + c + '</td>' for c in row) +
                                             '</tr>' for row in rows) + '</tbody></table></div>')


def fields(items):
    return '<dl>' + ''.join('<dt>' + escape(k) + '</dt><dd>' + text(v) + '</dd>' for k, v in items) + '</dl>'


def page(title, content):
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>' + escape(title) + ' — Market Sentinel</title><style>'
            'body{font:16px system-ui,sans-serif;max-width:1200px;margin:2rem auto;padding:0 1rem;'
            'color:#182638;background:#f6f8fb}a{color:#154ea2}h1{margin-bottom:.4rem}'
            'table{border-collapse:collapse;background:white;width:100%}th,td{text-align:left;'
            'padding:.65rem;border-bottom:1px solid #dce2e9;vertical-align:top}'
            'th{background:#e8eef5;white-space:nowrap}td:first-child,td:nth-child(2){white-space:nowrap}'
            'dl{display:grid;grid-template-columns:minmax(10rem,1fr) 3fr;gap:.4rem}'
            'dd{margin:0;overflow-wrap:anywhere}dt{font-weight:600}.scroll{overflow-x:auto}'
            '.notice{padding:.8rem;background:#fff0cb;border-left:4px solid #b17800}'
            'summary{cursor:pointer}small{color:#4b5b70}footer{margin:2rem 0}</style><body>'
            '<header><a href="/">Market Sentinel · Report history</a><h1>' + escape(title) + '</h1></header>' +
            content + '<footer><small>Retained informational screening evidence. '
            'Pushover API acceptance is not device receipt; device receipt is not recorded. '
            'Refresh this page to read current files.</small></footer></body></html>')


def read_history(root):
    """Read report/ledger snapshots without presentation or other runtime dependencies.

    This is a Python reader seam, not a published external API. A future consumer
    can wrap it explicitly without importing HTML or starting either application.
    """
    deliveries, ledger_error = ledger(root)
    identities = {key.replace(":", "-") for key in deliveries if isinstance(key, str) and
                  valid_slot(key.replace(":", "-"))}
    notices = [ledger_error] if ledger_error else []
    try:
        identities.update(p.stem for p in root.iterdir() if p.suffix == '.json' and valid_slot(p.stem))
    except OSError:
        notices.append("Report directory unavailable. No files were created; refresh after reports are retained.")
    records = []
    for identity in sorted(identities, key=lambda s: (s[:10], s.endswith('closing')), reverse=True):
        value, error = report(root, identity)
        delivery, status = delivery_info(deliveries, identity)
        if ledger_error:
            status = "Unavailable — ledger could not be read"
        records.append(dict(identity=identity, report=value, report_error=error,
                            delivery=delivery, delivery_status=status))
    return records, notices


def list_page(root):
    records, notices = read_history(root)
    rows = []
    for record in records:
        identity, value, error = record['identity'], record['report'], record['report_error']
        summary = value['summary'] if value else {}
        status_label = {'accepted': 'API accepted', 'unknown': 'Unknown / rejected',
                        'attempting': 'Attempt recorded', 'waiting': 'Waiting'}.get(record['delivery'].get('status'))
        if not status_label:
            status_label = 'No attempt recorded' if record['delivery_status'].startswith('No notification') else 'Unavailable'
        rows.append([f'<a href="/reports/{identity}">{identity[:10]} {identity[11:].capitalize()}</a>',
                     text(summary.get('completed_session')), text(summary.get('status')).replace('_', ' '),
                     text(summary.get('new_downward_crossings')), text(summary.get('warning_count')),
                     text(value.get('evidence_timestamp') if value else None), escape(status_label),
                     escape(error) if error else 'Retained'])
    content = ''.join('<p class="notice">' + escape(n) + '</p>' for n in notices)
    content += '<p>Opening and closing reports are separate observations. Dates identify the scheduled report; '
    content += 'the data-session column identifies the completed market session.</p>'
    content += table(['Report (ET)', 'Data session', 'Retained status', 'Crossings', 'Warnings',
                      'Evidence timestamp', 'Notification status', 'Report evidence'], rows) if rows else '<p>No retained reports found.</p>'
    return page('Report history', content)


def result_detail(row):
    """Present source fields, without recalculating indicators or crossing signals."""
    symbol = text(row.get('symbol'))
    latest = row.get('latest') if isinstance(row.get('latest'), dict) else {}
    crossing = latest.get('crossed_below_20') if latest.get('crossing_available') is True else None
    warning_rows = row.get('warnings')
    if isinstance(warning_rows, list):
        warnings = table(['Session', 'Warning', 'Value', 'Low', 'High', 'Excluded from calculation'],
                         [[text(w.get(k)) for k in ('session', 'code', 'value', 'low', 'high', 'excluded_from_calculation')]
                          for w in warning_rows if isinstance(w, dict)]) if warning_rows else '<p>No retained warnings.</p>'
        if any(not isinstance(w, dict) for w in warning_rows):
            warnings += '<p class="notice">Some warning records are malformed.</p>'
    else:
        warnings = '<p>Warning details unavailable.</p>'
    # These are retained sample observations, not separately delivered alerts.
    crossings = row.get('historical_crossings')
    history = ''
    if isinstance(crossings, list) and crossings:
        history = '<h3>Retained sample crossings</h3><p>These are observations in this report, not an alert-delivery history.</p>'
        history += table(['Session', 'Close', 'Previous K', 'K', 'D'],
                         [[text(c.get(k)) for k in ('session', 'close', 'previous_k', 'k', 'd')]
                          for c in crossings if isinstance(c, dict)])
    details = ('<details><summary>' + symbol + ' · source details and warnings</summary>' +
               fields([(k.replace('_', ' ').capitalize(), row.get(k)) for k in
                       ('provider', 'environment', 'completed_through', 'first_session', 'last_session',
                        'stale_relative_to_cutoff', 'continuity', 'adjustment', 'error') if k in row]) + warnings + history + '</details>')
    cells = [symbol, text(latest.get('close')), text(latest.get('k')), text(latest.get('d')),
             text(crossing), text(row.get('status')), text(row.get('warning_count'))]
    return cells, details


def detail_page(root, identity):
    value, error = report(root, identity)
    deliveries, ledger_error = ledger(root)
    item, status = delivery_info(deliveries, identity)
    delivery_content = '<p>Device receipt: not recorded.</p>'
    if ledger_error:
        delivery_content += '<p class="notice">' + escape(ledger_error) + '</p>'
        status = 'Unavailable — ledger could not be read'
    delivery_content += fields([('Notification status', status), ('Scheduled time', item.get('due')),
                       ('Recorded attempt marker', item.get('attempted')), ('Pushover API accepted at', item.get('accepted'))])
    delivery_content = '<details><summary>Notification · ' + escape(status) + '</summary>' + delivery_content + '</details>'
    if error:
        return page(identity + ' report', '<p class="notice">' + escape(error) + '</p>' + delivery_content)
    summary, results = value['summary'], value['results']
    content = fields([('Completed data session', summary.get('completed_session')),
                       ('Evidence timestamp', value.get('evidence_timestamp')), ('Retained report status', summary.get('status')),
                       ('Usable evaluations (reported)', summary.get('usable_latest_symbols')), ('Crossings (reported)', summary.get('new_downward_crossings')),
                       ('Warnings (reported)', summary.get('warning_count'))])
    if item.get('session') is not None and item['session'] != summary.get('completed_session'):
        content += '<p class="notice">Report and ledger data sessions disagree. Records may be changing; no combined delivery claim is established.</p>'
    rows, details, observed = [], [], []
    for row in results:
        if not isinstance(row, dict):
            content += '<p class="notice">A symbol result is malformed.</p>'
            continue
        cells, extra = result_detail(row)
        rows.append(cells)
        details.append(extra)
        observed.append(row.get('symbol'))
    if len(observed) != len(SYMBOLS) or set(s for s in observed if isinstance(s, str)) != set(SYMBOLS):
        content += '<p class="notice">Incomplete or inconsistent symbol coverage: expected all 19 configured symbols exactly once. Missing results are unknown.</p>'
    if summary.get('status') not in ('complete', 'complete_with_warnings'):
        content += '<p class="notice">Report is incomplete or its completion status is unavailable. Missing signals are unknown, not zero.</p>'
    content += '<h2>Stochastic 14-3-3 results</h2><p>Retained K and D values; no recalculation. Unknown means unavailable or unrecorded.</p>'
    content += table(['Symbol', 'Close', 'K', 'D', 'Crossed below 20', 'Source status', 'Warnings'], rows)
    content += '<h2>Notification record</h2>' + delivery_content
    content += '<h2>Source details</h2>' + ''.join(details)
    return page(identity[:10] + ' ' + identity[11:].capitalize(), content)


def make_server(root=RUNTIME, port=8765):
    """Only a fixed IPv4 loopback binding; no filesystem-serving superclass."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            port = self.server.server_port
            allowed = {f'127.0.0.1:{port}', f'localhost:{port}'}
            if self.headers.get('Host') not in allowed or self.headers.get('Origin') not in (
                    None, f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
                self.respond(403, page('Forbidden', '<p>Local browser access only.</p>'))
                return
            if self.path == '/':
                self.respond(200, list_page(Path(root)))
            elif self.path.startswith('/reports/') and valid_slot(self.path[9:]):
                self.respond(200, detail_page(Path(root), self.path[9:]))
            else:
                self.respond(404, page('Not found', '<p>Report route not found.</p>'))

        def respond(self, status, body):
            raw = body.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(raw)

        def reject_write(self):
            self.respond(405, page('Read only', '<p>Only report viewing is supported.</p>'))

        do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = reject_write

        def log_message(self, *args):
            pass  # No paths, source data or browser headers written to logs.

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description='View existing Market Sentinel reports locally; no acquisition or notifications.')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--reports-dir', type=Path, default=RUNTIME, help='existing report directory (default: automatic-reports)')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    try:
        with make_server(args.reports_dir, args.port) as server:
            print(f'Report history: http://127.0.0.1:{server.server_port}/ (Ctrl-C to stop)', flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except OSError:
        print('Unable to start the local report viewer. Check the selected port.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
