"""Read-only live investigation projection; no acquisition or signal evaluation."""

import os
from datetime import datetime, timezone
from pathlib import Path

from market_sentinel.intraday_state import read_view
from market_sentinel.report_history import fields, indicator_order, page, table, text
from market_sentinel.universe import SYMBOLS


def default_state():
    return Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'market-sentinel/intraday/state.sqlite3'


def live_page(path, focus=None, *, now=None, sort_by='k'):
    now = now or datetime.now(timezone.utc)
    try:
        view = read_view(path)
    except Exception:
        return page('Realtime unavailable', '<p class="notice">Intraday ledger unavailable or malformed. No data substituted.</p>')
    status = view['status']
    latest = {r['symbol']: r for r in view['latest']}
    events = [e for e in view['events'] if focus is None or e['current']['symbol'] == focus]
    symbols = [focus] if focus else sorted(SYMBOLS, key=lambda s: indicator_order(s,
                   (latest.get(s, {}).get('observation') or {}).get(sort_by)))
    content = '<style>body{max-width:1500px}table{font-size:14px;font-variant-numeric:tabular-nums}th,td{padding:.45rem}th{white-space:normal}</style>'
    content += '<p class="notice">Provisional daily Stochastic(14,3,3). Not confirmed at close. Viewing does not start monitoring or send alerts.</p>'
    route = '/realtime' + ('/' + focus if focus else '')
    content += f'<p><a href="/realtime?sort={sort_by}">All 19 symbols</a> · Sort ascending: <a href="{route}?sort=k">K</a> · <a href="{route}?sort=d">D</a>. Current: {sort_by.upper()}.</p>'
    content += fields([('Monitor', status.get('state')), ('Last check', status.get('checked')),
                       ('Last successful update', status.get('last_successful_update')),
                       ('Usable coverage at last sweep', status.get('usable')),
                       ('Provisional cadence (seconds)', status.get('cadence_seconds')),
                       ('Sending enabled at last sweep', status.get('sending_enabled'))])
    rows = []
    for symbol in symbols:
        item = latest.get(symbol, {})
        obs = item.get('observation') or {}
        baseline = obs.get('completed', {})
        k, d = obs.get('k'), obs.get('d')
        try:
            age = (now - datetime.fromisoformat(obs['observed'])).total_seconds()
            fresh = 0 <= age <= 180 and not item.get('degraded')
            age_text = f'{age:.0f}s since minute end'
        except (KeyError, ValueError, TypeError):
            fresh, age_text = False, 'Unavailable'
        state = ('Oversold' if k < 20 else 'Overbought' if k > 80 else 'Neutral') if k is not None else 'Unavailable'
        delta = lambda key: (obs[key] - baseline[key]) if obs.get(key) is not None and baseline.get(key) is not None else None
        number = lambda v: f'{v:.2f}' if type(v) in (int, float) else '—'
        rows.append([f'<a href="/realtime/{symbol}?sort={sort_by}">{symbol}</a>', number(obs.get('price')), number(k), number(d),
                     text(state), text(baseline.get('session')), number(baseline.get('k')) + ' / ' + number(baseline.get('d')),
                     number(delta('k')) + ' / ' + number(delta('d')), text(age_text), 'Fresh' if fresh else 'Degraded / stale / unavailable'])
    content += table(['Symbol', 'Price at minute end', 'Provisional K', 'Provisional D', 'Technical state',
                      'Completed session', 'Completed K / D', 'Δ K / D', 'Data age', 'Freshness'], rows)
    if focus:
        obs = (latest.get(focus, {}).get('observation') or {})
        candle = obs.get('candle', {})
        content += '<h2>Developing daily candle</h2>' + fields([(k, candle.get(k)) for k in ('session', 'open', 'high', 'low', 'close')])
        content += fields([('Observed interval end', obs.get('observed')), ('Data convention', obs.get('provenance')),
                           ('Last successful observation', obs.get('detected')),
                           ('Full precision provisional K', obs.get('k')), ('Full precision provisional D', obs.get('d')),
                           ('Historical price warnings', obs.get('historical_warnings')),
                           ('Evidence identity', obs.get('evidence_id')),
                           ('Last confirmed daily crossing session', (obs.get('last_confirmed_crossing') or {}).get('session'))])
    content += '<h2>Recent intraday transitions</h2>'
    content += table(['Symbol', 'Event', 'Qualification', 'Previous K', 'Provisional K / D', 'Observed', 'Detected', 'Attention policy', 'Delivery', 'Completed-session follow-up'],
                     [[text(e['current']['symbol']), text(e['type']), text(e['qualification']), text(e['previous']['k']),
                       text(str(e['current']['k']) + ' / ' + str(e['current']['d'])), text(e['current']['observed']),
                       text(e['detected']), text(e['policy']), text(e['delivery']),
                       text(('K=' + str(e['completed_result']['k']) + ', D=' + str(e['completed_result']['d']) +
                             '; remained oversold=' + str(e['completed_result']['remained_oversold_at_close']) +
                             '; observed=' + e['completed_result']['observed']) if e.get('completed_result') else None)] for e in events])
    failures = status.get('failures', {})
    if failures:
        content += '<h2>Degraded coverage</h2>' + fields(list(failures.items()))
    content += '<p>Refreshes every 15 seconds. Exact crossing ticks and phone receipt are unknown. '
    content += '<a href="/">Completed opening/closing reports</a> retain separate completed-session evidence.</p>'
    return page('Realtime' + (' · ' + focus if focus else ' · 19 symbols'), content)
