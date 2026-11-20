"""Bounded scheduled preview: regular-session minute OHLC + completed history.

Reuses the verified minute aggregation precedent from the realtime candidate;
no realtime service, database, quote repair, or order capability is introduced.
"""
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from market_sentinel.stochastic import DailyOHLC, _validated, _range_warnings, stochastic_14_3_3
from market_sentinel.tradier import TradierError, _get_json, fetch_history
from market_sentinel.universe import SYMBOLS

ET = ZoneInfo('America/New_York')
MAX_AGE_SECONDS = 180
TITLE = 'Market Sentinel — Pre-close preview'


def minute_candle(payload, opening, closing, received):
    """Strict regular-session coverage; never fill an absent minute.

    The most recent bucket may still be forming. Its start is the conservative
    data timestamp, not a claimed last-trade time. Range warnings remain visible.
    """
    try:
        if not opening <= received < closing: raise ValueError
        rows = payload['series']['data']
        rows = [rows] if isinstance(rows, dict) else rows
        if not isinstance(rows, list) or not rows or len(rows) > 600: raise ValueError
        bars, previous, warnings = [], None, []
        for row in rows:
            if type(row['timestamp']) is not int: raise ValueError
            at = datetime.fromtimestamp(row['timestamp'], timezone.utc)
            if (at.second or at.microsecond or not opening <= at < closing or at > received or
                    datetime.fromisoformat(row['time']) != at.astimezone(ET).replace(tzinfo=None)):
                raise ValueError
            if previous is None and at != opening:
                raise TradierError('Regular-session opening minute missing; provisional daily open unverified.')
            if previous is not None and at != previous+timedelta(minutes=1):
                if at > previous:
                    missing = (previous+timedelta(minutes=1)).astimezone(ET).strftime('%H:%M')
                    raise TradierError('Missing regular-session minute '+missing+' ET; daily extrema unverified.')
                raise ValueError
            bar = _validated([DailyOHLC(opening.date(), *(row[k] for k in ('open','high','low','close')))])[0]
            warnings.extend(dict(minute=at.isoformat(), **{k:str(v) if k=='session' else v for k,v in asdict(w).items()})
                            for w in _range_warnings(bar))
            bars.append(bar); previous = at
        if not 0 <= (received-previous).total_seconds() <= MAX_AGE_SECONDS: raise ValueError
        candle = DailyOHLC(opening.date(), bars[0].open, max(b.high for b in bars),
                           min(b.low for b in bars), bars[-1].close)
        return candle, previous, warnings
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        raise TradierError('Incomplete, stale or malformed regular-session minute OHLC; no gap filling.') from None


def validate(report, slot):
    """Reject a wrong-session/corrupt retained preview before reuse or sending."""
    if (report.get('provisional') is not True or report.get('summary',{}).get('provisional_session') != slot['session'] or
            {r.get('symbol') for r in report.get('results',[])} != set(SYMBOLS) or len(report['results']) != len(SYMBOLS)):
        raise TradierError('Preview evidence identity/coverage mismatch.')
    for r in report['results']:
        if r.get('status') in ('calculated','calculated_with_warnings'):
            if r.get('provisional_session') != slot['session']: raise TradierError('Mixed preview sessions.')
            for key in ('k','d','close'):
                from market_sentinel.daily_report import _number
                _number(r['latest'][key])
            if not r['latest'].get('crossing_available'): raise TradierError('Unavailable preview comparison.')
            datetime.fromisoformat(r['data_timestamp'])
        elif 'latest' in r: raise TradierError('Unavailable preview must not contain substituted values.')


def acquire(token, slot, sessions, clock):
    from market_sentinel.scheduled_report import failed_symbol, screening_result
    day = date.fromisoformat(slot['session'])
    hours = sessions[str(day)]
    opening = datetime.fromisoformat(str(day)+'T'+hours['start']).replace(tzinfo=ET)
    closing = datetime.fromisoformat(slot['expires'])
    expected = tuple(date.fromisoformat(d) for d,h in sorted(sessions.items()) if h and d <= str(day))[-19:]
    context = None
    if len(expected)!=19 or expected[-1]!=day:
        context = TradierError('Insufficient verified preview history calendar.')
    elif any(str(expected[0]+timedelta(days=n)) not in sessions for n in range((day-expected[0]).days+1)):
        context = TradierError('Incomplete preview history calendar.')
    results, stopped = [], None
    for symbol in SYMBOLS:
        if stopped:
            results.append(failed_symbol(symbol, stopped, attempted=False)); continue
        try:
            if clock() >= closing: raise TradierError('Preview expired during acquisition.')
            if context: raise context
            if isinstance(token, Exception): raise token
            history = fetch_history(token, symbol=symbol, environment='production', start=expected[0],
                                    end=expected[-2], completed_through=expected[-2], exclude_older=True)
            if tuple(b.session for b in history.bars) != expected[:-1]:
                raise TradierError('Missing, stale or unexpected completed preview history.')
            at = clock()
            if at >= closing: raise TradierError('Preview expired during acquisition.')
            payload = _get_json(token,'production','timesales',dict(symbol=symbol, interval='1min',
                start=opening.strftime('%Y-%m-%d %H:%M'),end=at.astimezone(ET).strftime('%Y-%m-%d %H:%M'),session_filter='open'))
            candle, observed, minute_warnings = minute_candle(payload,opening,closing,clock())
            points = stochastic_14_3_3((*history.bars,candle)); previous, current = points[-2:]
            if any(v is None for v in (previous.k,previous.d,current.k,current.d)):
                raise TradierError('Preview Stochastic or adjacent comparison unavailable.')
            warnings = [dict(session=str(w.session),code=w.code,value=w.value,low=w.low,high=w.high) for w in history.warnings]
            warnings += [dict(session=str(w.session),code=w.code,value=w.value,low=w.low,high=w.high) for w in current.warnings]
            warning_count = len(warnings)+len(minute_warnings)
            results.append(dict(symbol=symbol,status='calculated_with_warnings' if warning_count else 'calculated',
                provisional_session=str(day),completed_history_through=str(expected[-2]),
                data_timestamp=observed.isoformat(),evidence_timestamp=clock().isoformat(),
                latest=dict(close=candle.close,k=current.k,d=current.d,crossing_available=True,
                            crossed_below_20=current.crossed_below_20), previous_k=previous.k,
                crossed_above_20=previous.k<20 and current.k>=20,
                warnings=warnings,minute_warnings=minute_warnings,warning_count=warning_count,
                provisional_bar={k:str(v) if k=='session' else v for k,v in asdict(candle).items()},
                history_bars=[{k:str(v) if k=='session' else v for k,v in asdict(b).items()} for b in history.bars],
                excluded_old_sessions=[str(d) for d in history.excluded_old_sessions],
                invalid_old_sessions=[str(d) for d in history.invalid_old_sessions]))
        except Exception as error:
            results.append(failed_symbol(symbol,error,attempted=not isinstance(token,Exception)))
            if isinstance(error,TradierError) and error.stop_batch or isinstance(token,Exception): stopped=error
    # Results have differing observation times. Remove aged observations at sweep end.
    received = clock()
    results = [failed_symbol(r['symbol'],TradierError('Minute evidence aged out during preview acquisition.'))
               if 'data_timestamp' in r and (received-datetime.fromisoformat(r['data_timestamp'])).total_seconds()>MAX_AGE_SECONDS
               else r for r in results]
    report = screening_result(expected[-2] if len(expected)>1 else day,results)
    report.update(provisional=True,evidence_timestamp=received.isoformat(),
                  provenance='Tradier production regular-session 1min OHLC; latest bucket may be unfinished; no gap filling.')
    report['summary']['provisional_session']=str(day)
    report['calculation_policy']=dict(total_exchange_sessions=19,completed_bars=18,provisional_bars=1,
                                     indicator='TA-Lib STOCH(14,3,3), SMA/SMA')
    validate(report,slot)
    return report


def message(report, slot):
    from market_sentinel.pushover import validate_message
    validate(report,slot)
    valid=[r for r in report['results'] if r['status'] in ('calculated','calculated_with_warnings')]
    missing=sorted(r['symbol'] for r in report['results'] if r not in valid)
    oversold=sorted((r for r in valid if r['latest']['k']<20),key=lambda r:(r['latest']['k'],r['symbol']))
    times=[datetime.fromisoformat(r['data_timestamp']).astimezone(ET) for r in valid]
    stamp=(min(times).strftime('%H:%M:%S')+'–'+max(times).strftime('%H:%M:%S')+' ET') if times else 'unavailable'
    lines=[f"Pre-close preview {slot['observation']}",f"PROVISIONAL | {len(valid)}/19 available",f'Data: {stamp} (minute buckets)',
           f"Oversold (K<20): {len(oversold)} known"]
    def number(value):
        text=f'{value:.2f}'
        return text if len(text)<=10 else f'{value:.2e}'
    lines += [f"{r['symbol']} K {number(r['latest']['k'])}" for r in oversold]
    down=','.join(sorted(r['symbol'] for r in valid if r['latest']['crossed_below_20'])) or 'none known'
    up=','.join(sorted(r['symbol'] for r in valid if r['crossed_above_20'])) or 'none known'
    lines += [f'Below 20 vs prior close: {down}',f'Back >=20 vs prior close: {up}',
              'Unavailable: '+(','.join(missing) or 'none'),
              f"Warnings: {report['summary']['warning_count']} | missing signals unknown",
              'Crossings provisional; intraday path unobserved.',
              'Informational. Review option chains independently.']
    body='\n'.join(lines);validate_message(TITLE,body);return body
