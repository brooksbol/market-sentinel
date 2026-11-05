"""Pure provisional daily evaluation. No acquisition, persistence or transport."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from market_sentinel.sessions import ET
from market_sentinel.stochastic import DailyOHLC, _validated, stochastic_14_3_3

CONVENTION = ("Tradier production regular-session completed 1min OHLC; "
              "aggregate first open, maximum high, minimum low, final close. "
              "Current minute excluded. Historical prices supplied unchanged; "
              "split-adjusted/dividend-unadjusted documentation has known mixed-close anomalies.")


def aware(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("An aware timestamp is required.")
    return value


def session_bounds(now, sessions):
    local = aware(now).astimezone(ET)
    key = str(local.date())
    if key not in sessions:
        raise ValueError("Current exchange calendar unavailable.")
    hours = sessions[key]
    if hours is None:
        return None
    opening, closing = (datetime.fromisoformat(key + 'T' + hours[k]).replace(tzinfo=ET)
                        for k in ('start', 'end'))
    return opening, closing


def developing_candle(payload, opening, closing, received, *, max_age=180):
    """Strict minute continuity: sparse or late series is unavailable, never filled.

    Epoch seconds are authoritative; naive provider time must agree in Eastern.
    Observation time is the END of the last included minute, not its last tick.
    Freshness measures publication age from that boundary, not quote trade age.
    """
    aware(opening); aware(closing); aware(received)
    if not opening <= received < closing:
        raise ValueError("Outside regular session; no intraday evaluation.")
    try:
        rows = payload['series']['data']
        rows = [rows] if isinstance(rows, dict) else rows
        if not isinstance(rows, list) or not rows or len(rows) > 600:
            raise ValueError
        complete, prior = [], None
        for row in rows:
            stamp = row['timestamp']
            if type(stamp) is not int:
                raise ValueError
            at = datetime.fromtimestamp(stamp, timezone.utc)
            if at.second or at.microsecond or not opening <= at < closing or at > received:
                raise ValueError
            if datetime.fromisoformat(row['time']) != at.astimezone(ET).replace(tzinfo=None):
                raise ValueError
            if prior is not None and at != prior + timedelta(minutes=1):
                raise ValueError
            prior = at
            bar = _validated([DailyOHLC(opening.date(), *(row[k] for k in ('open', 'high', 'low', 'close')))])[0]
            if not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high:
                raise ValueError
            if at + timedelta(minutes=1) <= received:
                complete.append((at, bar))
        if not complete or complete[0][0] != opening:
            raise ValueError
        observed = complete[-1][0] + timedelta(minutes=1)
        if not 0 <= (received - observed).total_seconds() <= max_age:
            raise ValueError
        bars = [b for _, b in complete]
        return DailyOHLC(opening.date(), bars[0].open, max(b.high for b in bars),
                         min(b.low for b in bars), bars[-1].close), observed
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        raise ValueError("Incomplete, stale or malformed current-session minute OHLC.") from None


def evaluate(symbol, history, candle, observed, detected, *, previous_session):
    """Append exactly ONE current candle to an unchanged completed series."""
    aware(observed); aware(detected)
    bars = _validated(history)
    if not bars or bars[-1].session != previous_session or bars[-1].session >= candle.session:
        raise ValueError("Completed history cutoff invalid; developing candle must occur exactly once.")
    if candle.session != observed.astimezone(ET).date() or observed > detected:
        raise ValueError("Observation session/time mismatch.")
    completed = stochastic_14_3_3(bars)
    point = stochastic_14_3_3((*bars, candle))[-1]
    if any(v is None for v in (completed[-1].k, completed[-1].d, point.k, point.d)):
        raise ValueError("Stochastic warm-up or range unavailable.")
    confirmed = next((asdict(p) for p in reversed(completed) if p.crossed_below_20), None)
    # JSON-ready evidence; timestamps identify interval boundaries and detection.
    return dict(symbol=symbol, session=str(candle.session), observed=observed.isoformat(),
                detected=detected.isoformat(), price=candle.close, k=point.k, d=point.d,
                candle={k: str(v) if k == 'session' else v for k, v in asdict(candle).items()},
                completed=dict(session=str(completed[-1].session), k=completed[-1].k, d=completed[-1].d),
                last_confirmed_crossing=(dict(session=str(confirmed['session']), k=confirmed['k'], d=confirmed['d'])
                                         if confirmed else None),
                historical_warnings=sum(len(p.warnings) for p in completed), provenance=CONVENTION)


def transition(previous, current, *, gap=False, max_interval=360):
    """Classify first sightings and gaps without claiming an exact crossing tick."""
    if previous is None:
        before = current['completed']['k']
        qualification = 'first_observation_since_completed_close'
    else:
        if previous['session'] != current['session']:
            raise ValueError("Previous observation must be from this session.")
        elapsed = (datetime.fromisoformat(current['observed']) -
                   datetime.fromisoformat(previous['observed'])).total_seconds()
        if elapsed <= 0:
            return None
        before = previous['k']
        qualification = 'observation_gap' if gap or elapsed > max_interval else 'between_observations'
    after = current['k']
    if before >= 20 and after < 20:
        kind = 'entered_oversold'
    elif before < 20 and after >= 20:
        kind = 'recovered'
    elif previous is None and before < 20 and after < 20:
        kind = 'already_oversold'
    else:
        return None
    return dict(type=kind, qualification=qualification, previous=previous or current['completed'],
                current=current, detected=current['detected'])
