"""Portable one-sweep monitor and explicit foreground loop. No startup installation."""

import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from market_sentinel.intraday import session_bounds
from market_sentinel.intraday_provider import Provider
from market_sentinel.intraday_state import Ledger
from market_sentinel.pushover import _send_message, load_credentials, validate_message
from market_sentinel.universe import SYMBOLS

TITLE = 'Market Sentinel — Intraday Oversold'
CADENCE = 180  # Engineering provisional default, subject to operational acceptance.


def default_state():
    return Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'market-sentinel/intraday/state.sqlite3'


def alert_body(event):
    current, previous = event['current'], event['previous']
    label = ('First observed below K=20 since completed close; crossing time unknown'
             if event['qualification'] == 'first_observation_since_completed_close'
             else 'Crossed below K=20 between observations; exact time unknown')
    body = (f"{current['symbol']} — {label}\nPrevious K: {previous['k']:.4f}\n"
            f"Current K: {current['k']:.4f}\nPrice: ${current['price']:.2f}\n"
            f"Previous observation: {previous.get('observed', previous.get('session'))}\n"
            f"Observation (minute end): {current['observed']}\nDetected: {event['detected']}\n"
            'Provisional daily signal\nNot yet confirmed at close')
    validate_message(TITLE, body)
    return body


def send_alert(event):
    body = alert_body(event)
    token, user = load_credentials()
    _send_message(token, user, title=TITLE, message=body)


def run_once(provider, ledger, *, send=False, notify=send_alert, clock=lambda: datetime.now(timezone.utc)):
    """Persist evidence before any send. Never replay intents or old events."""
    started = time.monotonic()
    try:
        status, results, failures = provider.poll()
    except Exception:
        status, results = dict(state='Acquisition unavailable', checked=clock().isoformat()), []
        failures = {s: 'Provider/calendar/credential failure; details suppressed' for s in SYMBOLS}
    for symbol in failures:
        ledger.degraded(symbol)
    events = []
    for result in results:
        # Recheck market time AFTER the full sweep; never deliver delayed results
        # after close or treat acquisition duration as a fresh detection time.
        now = clock()
        bounds = session_bounds(now, provider.sessions)
        observed = datetime.fromisoformat(result['observed'])
        if bounds is None or not bounds[0] <= now < bounds[1] or (now - observed).total_seconds() > 180:
            ledger.degraded(result['symbol'])
            failures[result['symbol']] = 'Stale or market closed before evaluation'
            continue
        result = dict(result, detected=now.isoformat())
        evidence = {key: result.pop(key) for key in ('history_evidence', 'minute_evidence', 'calendar_evidence')}
        result['evidence_id'] = ledger.evidence(evidence)
        event = ledger.record(result, send=send)
        if event:
            events.append(event)
            if event['policy'] == 'send_reserved':
                try:
                    # Intent is committed. Any exception leaves acceptance unknown.
                    delivery_now = clock()
                    if delivery_now >= bounds[1] or (delivery_now - observed).total_seconds() > 180:
                        raise ValueError('Session ended before notification')
                    notify(event)
                except Exception:
                    ledger.outcome(event['id'], 'acceptance_unknown', clock().isoformat())
                else:
                    ledger.outcome(event['id'], 'api_accepted', clock().isoformat())
    status.update(failures=failures, sending_enabled=send, cadence_seconds=CADENCE)
    completion_failures = []
    for symbol, session in ledger.pending_completions():
        if time.monotonic() - started > 90:
            completion_failures.append('Sweep budget exhausted; follow-up deferred')
            break
        try:
            completed = provider.completed(symbol, session)
            if completed:
                ledger.complete(symbol, session, completed)
        except Exception:
            completion_failures.append(symbol + ':' + session)
    status['completed_result_unavailable'] = completion_failures
    status['usable'] = len(results) - sum(r['symbol'] in failures for r in results)
    if status['usable']:
        status['last_successful_update'] = clock().isoformat()
    ledger.status(status)
    return events


def main(argv=None):
    parser = argparse.ArgumentParser(description='Explicit intraday market-data sweep; preview only unless --send. No scheduler installation.')
    parser.add_argument('--state', type=Path, default=default_state())
    parser.add_argument('--loop', action='store_true', help='foreground loop, provisional three-minute cadence')
    parser.add_argument('--send', action='store_true', help='enable real event notifications; requires separate operator activation authorization')
    args = parser.parse_args(argv)
    provider = Provider()
    ledger = None
    try:
        ledger = Ledger(args.state)
        while True:
            run_once(provider, ledger, send=args.send)
            if not args.loop:
                break
            # No catch-up burst or retries. One sweep at most per cadence.
            time.sleep(CADENCE)
    except KeyboardInterrupt:
        return 0
    except Exception:
        print('Intraday monitor failed; details suppressed. Inspect state and configuration; no automatic retry.')
        return 1
    finally:
        if ledger:
            ledger.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
