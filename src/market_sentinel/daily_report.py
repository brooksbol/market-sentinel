"""Pure operator-friendly full-universe report and explicit one-message delivery.

Acquisition, TA-Lib calculations and crossing rules are unchanged. This module
only validates evaluated results, classifies usable K and formats a snapshot.
"""

from datetime import date
from math import isfinite

from market_sentinel.pushover import PushError, _send_message, validate_message
from market_sentinel.universe import SYMBOLS

TITLE = "Market Sentinel — Daily Report"


class ReportError(ValueError):
    """Sanitized report preflight failure. Never send a partial substitute."""


def _require(condition, message):
    if not condition:
        raise ReportError(message)


def _date(value):
    _require(isinstance(value, str), "A completed session date is required.")
    try:
        session = date.fromisoformat(value)
    except ValueError:
        raise ReportError("Invalid completed session date.") from None
    _require(session.isoformat() == value, "Session must use YYYY-MM-DD.")
    return session


def _number(value):
    try:
        valid = type(value) in (int, float) and isfinite(value)
    except OverflowError:
        valid = False
    _require(valid, "Missing, nonnumeric or nonfinite report value.")
    return value


def _count(value, expected):
    return type(value) is int and value == expected


def stochastic_state(k):
    """Classify unrounded finite K; None is Unavailable, never Neutral.

    Exact 20 and 80 are Neutral. These are technical screening states, not
    valuations, forecasts or investment recommendations.
    """
    if k is None:
        return "Unavailable"
    k = _number(k)
    return "Oversold" if k < 20 else "Overbought" if k > 80 else "Neutral"


def format_daily_report(screening, *, demonstration=False):
    """Return all 19 rows or ReportError; never mutate or repair source results.

    Rows with available K sort by full-precision K then symbol. Explicit upstream
    failures or unavailable K remain visible at the end, sorted by symbol. Any
    unavailable diagnostics make the report incomplete and aggregate crossings
    unknown. A known K still determines its state even if D is unavailable. D is
    validated internally but omitted from the default notification. No I/O.
    """
    _require(isinstance(screening, dict), "A screening report is required.")
    summary, results = screening.get("summary"), screening.get("results")
    _require(isinstance(summary, dict) and isinstance(results, (list, tuple)), "Missing screening summary or rows.")
    _require(len(results) == len(SYMBOLS), "Incomplete universe: all 19 symbol rows are required.")
    session = _date(summary.get("completed_session"))
    _require(_count(summary.get("configured_symbols"), len(SYMBOLS)), "The configured universe must contain 19 symbols.")
    seen = set()
    rows, warning_count, session_warnings, crossings, evaluated = [], 0, 0, 0, 0
    for result in results:
        _require(isinstance(result, dict), "Invalid screening row.")
        symbol = result.get("symbol")
        _require(isinstance(symbol, str) and symbol in SYMBOLS and symbol not in seen,
                 "Universe contains an unknown or duplicate symbol.")
        seen.add(symbol)
        status = result.get("status")
        failed = status in ("failed", "not attempted after access/quota failure")
        if failed:
            _require("latest" not in result, "Failed rows must not substitute prior observations.")
            rows.append((symbol, None, None, False))
            continue
        _require(status in ("calculated", "calculated_with_warnings", "degraded"), "Invalid symbol evaluation status.")
        _require(result.get("stale_relative_to_cutoff") is False, "Stale symbol cannot substitute an earlier session.")
        _require(_date(result.get("last_session")) == session and
                 _date(result.get("completed_through")) == session, "Mixed completed-session dates are not permitted.")
        latest = result.get("latest")
        _require(isinstance(latest, dict), "Missing latest indicator observation.")
        close = _number(latest.get("close"))
        _require(close > 0, "Closing price must be positive.")
        _require("k" in latest and "d" in latest, "Missing indicator fields; unavailable values must be explicit nulls.")
        k, d = (None if latest[key] is None else _number(latest[key]) for key in ("k", "d"))
        crossing_available, crossed = latest.get("crossing_available"), latest.get("crossed_below_20")
        _require(type(crossing_available) is bool, "Crossing availability must be explicit.")
        _require((crossing_available and type(crossed) is bool and k is not None) or
                 (not crossing_available and crossed is None), "Inconsistent or missing crossing evaluation.")
        _require(not crossed or k < 20, "Crossing flag contradicts the current K value.")
        crossings += crossed is True
        evaluated += 1
        usable = k is not None and d is not None and crossing_available
        warnings = result.get("warnings")
        _require(isinstance(warnings, list) and _count(result.get("warning_count"), len(warnings)),
                 "Missing or inconsistent data-quality warning details.")
        _require(status == ("degraded" if not usable else "calculated_with_warnings" if warnings else "calculated"),
                 "Symbol availability/warning status is inconsistent.")
        for warning in warnings:
            _require(isinstance(warning, dict), "Malformed data-quality warning.")
            warning_session = _date(warning.get("session"))
            excluded = warning.get("excluded_from_calculation")
            _require(type(excluded) is bool and excluded == (warning_session > session), "Inconsistent warning session scope.")
            session_warnings += warning_session == session and not excluded
        warning_count += len(warnings)
        # State always follows K alone. Missing D/adjacent comparison reduces the
        # successful evaluation count, but cannot turn a known K into Neutral or
        # hide its screening state. The source diagnostics remain untouched.
        rows.append((symbol, close, k, usable))
    usable_count = sum(row[3] for row in rows)
    _require(seen == set(SYMBOLS), "Incomplete configured universe.")
    _require(_count(summary.get("evaluated_symbols"), evaluated) and
             _count(summary.get("usable_latest_symbols"), usable_count), "Evaluation summary disagrees with symbol results.")
    acquired = summary.get("acquired_symbols")
    _require(type(acquired) is int and evaluated <= acquired <= len(SYMBOLS), "Invalid acquisition count.")
    _require(_count(summary.get("new_downward_crossings"), crossings), "Crossing summary disagrees with symbol results.")
    _require(_count(summary.get("warning_count"), warning_count), "Warning summary disagrees with symbol results.")
    incomplete = usable_count != len(SYMBOLS)
    _require(summary.get("status") == ("incomplete" if incomplete else "complete_with_warnings" if warning_count else "complete"),
             "Summary completion/warning status is inconsistent.")
    rows.sort(key=lambda row: (row[2] is None, row[2] if row[2] is not None else 0, row[0]))
    displayed = [(symbol, f"{close:.2f}" if close is not None else "--",
                  f"{k:.0f}" if k is not None else "--", stochastic_state(k))
                 for symbol, close, k, _ in rows]
    headers = ("SYM", "CLOSE", "STOCH", "STATE")
    widths = [max(len(headers[i]), *(len(row[i]) for row in displayed)) for i in range(4)]
    def line(row):
        return f"{row[0]:<{widths[0]}} {row[1]:>{widths[1]}} {row[2]:>{widths[2]}} {row[3]:<{widths[3]}}".rstrip()
    lines = [f"{session} | {usable_count}/19 evaluated", line(headers)]
    if incomplete:
        lines.insert(1, f"INCOMPLETE: {len(SYMBOLS)-usable_count} unavailable/failed")
    lines.extend(line(row) for row in displayed)
    oversold = sum(row[2] is not None and row[2] < 20 for row in rows)
    overbought = sum(row[2] is not None and row[2] > 80 for row in rows)
    lines.extend((f"Crossings: incomplete ({crossings} known)" if incomplete else f"Crossings: {crossings} | Oversold: {oversold}",
                  f"Oversold: {oversold} | Overbought: {overbought}" if incomplete else f"Overbought: {overbought}",
                  f"Warnings: {warning_count} sample; {session_warnings} on session"))
    if incomplete:
        diagnostics = [row[0] for row in rows if row[2] is not None and not row[3]]
        if diagnostics:
            lines.append("Diagnostics unavailable: " + ",".join(diagnostics))
        lines.append("State counts use available scores only.")
    if demonstration:
        lines.insert(0, "DEMONSTRATION - previously verified data")
        lines.append("Not a live scheduled result. Manual review.")
    else:
        lines.append("Informational screening. Manual review.")
    body = "\n".join(lines)
    try:
        validate_message(TITLE + (" TEST" if demonstration else ""), body)
    except PushError:
        raise ReportError("Complete universe report exceeds Pushover limits or contains invalid text; nothing sent.") from None
    return body


def send_daily_report(token, user_key, screening, *, demonstration=False):
    """One explicitly authorized send after full preflight. No retries or fallback.

    Return only on API acceptance; phone receipt requires operator confirmation.
    """
    body = format_daily_report(screening, demonstration=demonstration)
    try:
        _send_message(token, user_key, TITLE + (" TEST" if demonstration else ""), body, monospace=True)
    except PushError:
        raise
    except Exception:
        raise PushError("Unexpected daily-report request failure; acceptance is unknown. Details suppressed. No retry.") from None
