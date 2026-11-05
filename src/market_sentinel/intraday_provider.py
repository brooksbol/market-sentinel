"""Bounded Tradier production polling adapter. No brokerage endpoints."""

import calendar
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

from market_sentinel.intraday import developing_candle, evaluate, session_bounds
from market_sentinel.sessions import ET, normalize_calendar
from market_sentinel.tradier import TradierError, _get_json, fetch_history, load_token
from market_sentinel.stochastic import stochastic_14_3_3
from market_sentinel.universe import SYMBOLS


def budget(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        raise ValueError('Acquisition budget exhausted')


class Provider:
    def __init__(self, *, clock=lambda: datetime.now(timezone.utc)):
        self.clock = clock
        self.sessions = {}
        self.checked = None
        self.calendar_acquired = None
        self.histories = {}
        self.history_acquired = {}
        self.stopped = False

    def completed(self, symbol, session, *, deadline=None):
        """First usable completed daily result, separate from provisional events.

        No finality guarantee: provider corrections may occur later. Never alter
        completed daily reports or original event evidence.
        """
        now = self.clock()
        cutoff = date.fromisoformat(session)
        if cutoff > now.astimezone(ET).date():
            return None
        token = None
        if session not in self.sessions:
            budget(deadline)
            token = load_token('production')
            budget(deadline)
            self.sessions.update(normalize_calendar(_get_json(token, 'production', 'calendar',
                dict(year=cutoff.year, month=cutoff.month)), cutoff.year, cutoff.month))
        hours = self.sessions.get(session)
        if not hours:
            return None
        close = datetime.fromisoformat(session + 'T' + hours['end']).replace(tzinfo=ET)
        if now < close + timedelta(minutes=1):
            return None
        start = cutoff - timedelta(days=270)
        month = start.replace(day=1)
        while month <= cutoff:
            # Recover full months for this cutoff, even after a long downtime.
            dates = [str(date(month.year, month.month, d)) for d in range(1, calendar.monthrange(month.year, month.month)[1]+1)]
            if any(d not in self.sessions for d in dates):
                budget(deadline)
                token = token or load_token('production')
                budget(deadline)
                self.sessions.update(normalize_calendar(_get_json(token, 'production', 'calendar',
                    dict(year=month.year, month=month.month)), month.year, month.month))
            month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
        expected = tuple(date.fromisoformat(d) for d, h in sorted(self.sessions.items()) if h and str(start) <= d <= session)
        budget(deadline)
        token = token or load_token('production')
        budget(deadline)
        history = fetch_history(token, symbol=symbol, environment='production',
                                start=start, end=cutoff, completed_through=cutoff)
        if tuple(b.session for b in history.bars) != expected or len(expected) < 100:
            raise ValueError('Completed history coverage unavailable')
        point = stochastic_14_3_3(history.bars)[-1]
        if point.k is None or point.d is None:
            raise ValueError('Completed Stochastic unavailable')
        return dict(session=session, observed=now.isoformat(), k=point.k, d=point.d,
                    remained_oversold_at_close=point.k < 20, completed_daily_crossing=point.crossed_below_20,
                    history=[{k: str(v) if k == 'session' else v for k, v in asdict(b).items()} for b in history.bars],
                    provenance='Tradier production completed daily history; later revisions possible')

    def calendar(self, token, now, *, deadline=None):
        today = now.astimezone(ET).date()
        if self.checked == today:
            return
        start = today - timedelta(days=275)
        month = start.replace(day=1)
        sessions = {}
        while month <= today:
            budget(deadline)
            sessions.update(normalize_calendar(_get_json(token, 'production', 'calendar',
                                                         dict(year=month.year, month=month.month)), month.year, month.month))
            month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
        self.sessions = sessions
        self.checked = today
        self.calendar_acquired = self.clock().isoformat()
        self.histories.clear()
        self.history_acquired.clear()

    def poll(self):
        """One bounded sweep; auth/quota stops remaining symbols. No retries.

        At most ten calendar, 19 history and 19 minute requests on cold start;
        19 minute requests thereafter. Stop starting requests after 90 seconds.
        """
        began = time.monotonic()
        self.stopped = False
        token = load_token('production')
        now = self.clock()
        self.calendar(token, now, deadline=began + 90)
        bounds = session_bounds(now, self.sessions)
        if bounds is None or not bounds[0] <= now < bounds[1]:
            return dict(state='Market closed', checked=now.isoformat()), [], {}
        opening, closing = bounds
        day = opening.date()
        cutoff = max(date.fromisoformat(d) for d, hours in self.sessions.items() if hours and d < str(day))
        start = cutoff - timedelta(days=270)
        expected = tuple(date.fromisoformat(d) for d, h in sorted(self.sessions.items()) if h and str(start) <= d <= str(cutoff))
        results, failures, stop = [], {}, False
        for symbol in SYMBOLS:
            if stop or time.monotonic() - began > 90:
                failures[symbol] = 'Acquisition stopped; budget, authentication or rate limit'
                continue
            try:
                if symbol not in self.histories:
                    budget(began + 90)
                    history = fetch_history(token, symbol=symbol, environment='production', start=start,
                                            end=cutoff, completed_through=cutoff)
                    if len(expected) < 100 or tuple(b.session for b in history.bars) != expected:
                        raise ValueError('Historical exchange-session coverage incomplete')
                    self.histories[symbol] = history
                    self.history_acquired[symbol] = self.clock().isoformat()
                # Explicit ET request convention, cross-checked against epoch/time fields.
                at = self.clock()
                if at >= closing:
                    raise ValueError('Market closed during acquisition')
                budget(began + 90)
                payload = _get_json(token, 'production', 'timesales', dict(symbol=symbol, interval='1min',
                    start=opening.strftime('%Y-%m-%d %H:%M'), end=at.astimezone(ET).strftime('%Y-%m-%d %H:%M'), session_filter='open'))
                received = self.clock()
                candle, observed = developing_candle(payload, opening, closing, received)
                history = self.histories[symbol]
                result = evaluate(symbol, history.bars, candle, observed, received, previous_session=cutoff)
                result['history_evidence'] = [{k: str(v) if k == 'session' else v for k, v in asdict(b).items()} for b in history.bars]
                result['minute_evidence'] = payload
                result['calendar_evidence'] = dict(provider='Tradier production markets/calendar',
                    acquired=self.calendar_acquired, previous_session=str(cutoff),
                    sessions={d: h for d, h in self.sessions.items() if str(start) <= d <= str(day)})
                result['history_acquired'] = self.history_acquired[symbol]
                results.append(result)
            except (ValueError, TradierError) as error:
                failures[symbol] = 'Unavailable: incomplete, stale, malformed or failed provider data'
                stop = isinstance(error, TradierError) and error.stop_batch
        self.stopped = stop
        return dict(state='Regular session', session=str(day), close=closing.isoformat(),
                    checked=self.clock().isoformat(), usable=len(results), configured=len(SYMBOLS)), results, failures
