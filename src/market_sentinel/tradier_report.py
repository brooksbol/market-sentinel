"""Explicit fixed-universe screening report. No notifications, state or scheduler."""

import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from market_sentinel.__main__ import _SafeParser
from market_sentinel.stochastic import stochastic_14_3_3
from market_sentinel.tradier import TradierError, fetch_history, load_token

from market_sentinel.universe import SYMBOLS
LABEL = "Market Sentinel — Informational Screening Results"
NOTICE = "Attention signals for independent manual review; not a trading recommendation. Prices are not corrected or independently verified."


def history_report(history):
    """Pure report. Warnings permit calculation; failures/unavailability stay distinct."""
    points = stochastic_14_3_3(history.bars)
    latest = points[-1]
    stale = history.bars[-1].session != history.completed_through
    crossing_available = len(points) >= 2 and points[-2].k is not None and latest.k is not None
    warnings = [dict(session=str(w.session), code=w.code, value=w.value, low=w.low, high=w.high,
                     excluded_from_calculation=w.session > history.completed_through)
                for w in history.warnings]
    degraded = stale or latest.k is None or latest.d is None or not crossing_available
    return dict(
        symbol=history.symbol, provider="Tradier", environment=history.environment,
        requested_start=str(history.start), requested_end=str(history.end),
        completed_through=str(history.completed_through),
        first_session=str(history.bars[0].session), last_session=str(latest.session),
        first_returned_session=str(min(tuple(bar.session for bar in history.bars) + history.excluded_sessions)),
        last_returned_session=str(max(tuple(bar.session for bar in history.bars) + history.excluded_sessions)),
        returned_bars=len(history.bars) + len(history.excluded_sessions),
        valid_bars=len(history.bars), stale_relative_to_cutoff=stale,
        continuity="UNVERIFIED: no exchange calendar; missing sessions cannot be enumerated",
        duplicates=0, rejected=0, reordered=history.reordered,
        excluded_sessions=[str(day) for day in history.excluded_sessions],
        missing_volume_sessions=[str(bar.session) for bar, volume in zip(history.bars, history.volumes)
                                 if volume is None],
        adjustment="Tradier prices as supplied. Documented split-adjusted; mixed dividend-related historical close conventions accepted for screening without repair.",
        warning_count=len(warnings), warning_counts=dict(Counter(w["code"] for w in warnings)),
        warnings=warnings,
        latest=dict(close=history.bars[-1].close, k=latest.k, d=latest.d,
                    crossing_available=crossing_available,
                    crossed_below_20=latest.crossed_below_20 if crossing_available else None),
        warmup_sessions=min(17, len(points)),
        unavailable_after_warmup=[dict(session=str(p.session), k=p.k, d=p.d)
                                  for p in points[17:] if p.k is None or p.d is None],
        historical_crossings=[dict(session=str(point.session), close=bar.close,
                                   previous_k=points[index - 1].k, k=point.k, d=point.d)
                              for index, (bar, point) in enumerate(zip(history.bars, points))
                              if point.crossed_below_20],
        status="degraded" if degraded else "calculated_with_warnings" if warnings else "calculated")


def main(argv=None):
    parser = _SafeParser(description=LABEL)
    parser.add_argument("--fetch", action="store_true", help="explicitly fetch the fixed 19-symbol universe once")
    parser.add_argument("--environment", choices=("production", "sandbox"), required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--completed-through", type=date.fromisoformat, required=True,
                        help="operator-certified completed trading session; must predate today in New York")
    args = parser.parse_args(argv)
    if not args.fetch:
        print("No data fetched or credentials read. Use --fetch only for authorized verification.")
        return 2
    today = datetime.now(ZoneInfo("America/New_York")).date()
    if not args.start <= args.completed_through <= args.end < today or (args.end - args.start).days > 366:
        print("Use an ordered <=366-day range ending before today in New York; cutoff must lie inside it.", file=sys.stderr)
        return 2
    if args.completed_through.weekday() >= 5:
        print("The certified completed-session cutoff must be a trading-session date.", file=sys.stderr)
        return 2
    try:
        token = load_token(args.environment)
    except TradierError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print("Unable to retrieve Tradier credentials; details suppressed.", file=sys.stderr)
        return 1
    results = []
    acquired = 0
    for symbol in SYMBOLS:
        try:
            history = fetch_history(token, symbol=symbol, environment=args.environment,
                                    start=args.start, end=args.end, completed_through=args.completed_through)
            acquired += 1
            results.append(history_report(history))
        except TradierError as error:
            results.append(dict(symbol=symbol, status="failed", error=str(error)))
            if error.stop_batch:  # Do not repeat rejected credentials or exceed a quota.
                break
        except Exception:
            results.append(dict(symbol=symbol, status="failed", error="Unexpected calculation/report failure; details suppressed."))
    attempted = {result["symbol"] for result in results}
    results.extend(dict(symbol=symbol, status="not attempted after access/quota failure")
                   for symbol in SYMBOLS if symbol not in attempted)
    evaluated = [r for r in results if "latest" in r]
    incomplete = any(r["status"] not in ("calculated", "calculated_with_warnings") for r in results)
    warning_count = sum(r["warning_count"] for r in evaluated)
    summary = dict(provider="Tradier", environment=args.environment, completed_session=str(args.completed_through),
                   configured_symbols=len(SYMBOLS), acquired_symbols=acquired, evaluated_symbols=len(evaluated),
                   usable_latest_symbols=sum(r["status"] in ("calculated", "calculated_with_warnings") for r in evaluated),
                   new_downward_crossings=sum(r["latest"]["crossed_below_20"] is True for r in evaluated),
                   warning_count=warning_count,
                   status="incomplete" if incomplete else "complete_with_warnings" if warning_count else "complete")
    print(json.dumps(dict(label=LABEL, notice=NOTICE, evidence_timestamp=datetime.now(timezone.utc).isoformat(),
                          summary=summary, results=results), indent=2, allow_nan=False))
    return 1 if incomplete else 0


if __name__ == "__main__":
    raise SystemExit(main())
