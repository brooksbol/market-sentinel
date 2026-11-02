"""Explicit three-symbol history proof. No notifications, storage or scheduler."""

import json
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from market_sentinel.__main__ import _SafeParser
from market_sentinel.stochastic import stochastic_14_3_3
from market_sentinel.tradier import TradierError, fetch_history, load_token

SYMBOLS = ("CLX", "CVX", "MCD")
LABEL = "Informational market-data and indicator verification — not a trading recommendation."


def history_report(history):
    """Pure JSON-compatible report; continuity is never claimed without a calendar."""
    points = stochastic_14_3_3(history.bars)
    latest = points[-1]
    stale = history.bars[-1].session != history.completed_through
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
        adjustment="Provider-documented split-adjusted, dividend-unadjusted; not independently verified",
        latest=dict(close=history.bars[-1].close, k=latest.k, d=latest.d,
                    crossed_below_20=latest.crossed_below_20),
        historical_crossings=[dict(session=str(point.session), close=bar.close,
                                   previous_k=points[index - 1].k, k=point.k, d=point.d)
                              for index, (bar, point) in enumerate(zip(history.bars, points))
                              if point.crossed_below_20],
        status="degraded" if stale or latest.k is None or latest.d is None else "calculated; continuity unverified")


def main(argv=None):
    parser = _SafeParser(description=LABEL)
    parser.add_argument("--fetch", action="store_true", help="explicitly authorize three real read-only requests")
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
    # Conservative proof-only guard: no same-day finality assertion, including after close.
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
    failed = False
    for symbol in SYMBOLS:
        try:
            result = history_report(fetch_history(token, symbol=symbol, environment=args.environment,
                                    start=args.start, end=args.end, completed_through=args.completed_through))
            failed |= result["status"] == "degraded"
            results.append(result)
        except TradierError as error:
            results.append(dict(symbol=symbol, status="failed", error=str(error)))
            failed = True
            # Stop on acquisition failure rather than repeat invalid credentials/quota requests.
            break
        except Exception:
            results.append(dict(symbol=symbol, status="failed", error="Unexpected calculation/report failure; details suppressed."))
            failed = True
            break
    attempted = {result["symbol"] for result in results}
    results.extend(dict(symbol=symbol, status="not attempted after prior failure")
                   for symbol in SYMBOLS if symbol not in attempted)
    print(json.dumps(dict(label=LABEL, evidence_timestamp=datetime.now(timezone.utc).isoformat(),
                          results=results), indent=2, allow_nan=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
