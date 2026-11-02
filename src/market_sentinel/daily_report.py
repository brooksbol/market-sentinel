"""Pure full-universe formatting and explicit one-message transport integration.

Accept existing evaluated screening dictionaries; never acquire prices, calculate
indicators, repair input, deduplicate events or schedule notifications here.
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


def format_daily_report(screening, *, demonstration=False):
    """Return one complete, preflighted body; all 19 rows or ReportError.

    Full-precision K controls sort and below-20 count; symbol breaks ties. Display
    formatting never participates in signal detection. Input crossing flags come
    from the screening layer. Range warnings are allowed, with separate sample
    and report-session counts. Incomplete/undefined/mixed-session data fail closed.
    There is no I/O, credential retrieval or input mutation.
    """
    _require(isinstance(screening, dict), "A screening report is required.")
    summary, results = screening.get("summary"), screening.get("results")
    _require(isinstance(summary, dict) and isinstance(results, (list, tuple)), "Missing screening summary or rows.")
    _require(len(results) == len(SYMBOLS), "Incomplete universe: all 19 symbol rows are required.")
    session = _date(summary.get("completed_session"))
    for key in ("configured_symbols", "acquired_symbols", "evaluated_symbols", "usable_latest_symbols"):
        _require(_count(summary.get(key), len(SYMBOLS)), "Incomplete evaluation: 19/19 usable symbols required.")
    _require(summary.get("status") in ("complete", "complete_with_warnings"), "Screening evaluation is incomplete.")
    seen = set()
    rows, warning_count, session_warnings, crossings = [], 0, 0, 0
    for result in results:
        _require(isinstance(result, dict), "Invalid screening row.")
        symbol = result.get("symbol")
        _require(isinstance(symbol, str) and symbol in SYMBOLS and symbol not in seen,
                 "Universe contains an unknown or duplicate symbol.")
        seen.add(symbol)
        _require(result.get("status") in ("calculated", "calculated_with_warnings"), "A symbol failed or has unavailable indicators.")
        _require(result.get("stale_relative_to_cutoff") is False, "Stale symbol cannot enter a complete report.")
        _require(_date(result.get("last_session")) == session and
                 _date(result.get("completed_through")) == session, "Mixed completed-session dates are not permitted.")
        latest = result.get("latest")
        _require(isinstance(latest, dict), "Missing latest indicator observation.")
        close, k, d = (_number(latest.get(key)) for key in ("close", "k", "d"))
        _require(close > 0, "Closing price must be positive.")
        _require(latest.get("crossing_available") is True and type(latest.get("crossed_below_20")) is bool,
                 "Latest crossing evaluation is unavailable.")
        crossed = latest["crossed_below_20"]
        _require(not crossed or k < 20, "Crossing flag contradicts the current K value.")
        crossings += crossed
        warnings = result.get("warnings")
        _require(isinstance(warnings, list) and _count(result.get("warning_count"), len(warnings)),
                 "Missing or inconsistent data-quality warning details.")
        _require(result["status"] == ("calculated_with_warnings" if warnings else "calculated"),
                 "Symbol warning status is inconsistent.")
        for warning in warnings:
            _require(isinstance(warning, dict), "Malformed data-quality warning.")
            warning_session = _date(warning.get("session"))
            excluded = warning.get("excluded_from_calculation")
            _require(type(excluded) is bool and excluded == (warning_session > session), "Inconsistent warning session scope.")
            session_warnings += warning_session == session and not excluded
        warning_count += len(warnings)
        rows.append((symbol, close, k, d))
    _require(seen == set(SYMBOLS), "Incomplete configured universe.")
    _require(_count(summary.get("new_downward_crossings"), crossings), "Crossing summary disagrees with symbol results.")
    _require(_count(summary.get("warning_count"), warning_count), "Warning summary disagrees with symbol results.")
    _require(summary["status"] == ("complete_with_warnings" if warning_count else "complete"), "Summary warning status is inconsistent.")
    rows.sort(key=lambda row: (row[2], row[0]))
    displayed = [(symbol, f"{close:.2f}", f"{k:.1f}", f"{d:.1f}") for symbol, close, k, d in rows]
    headers = ("SYM", "CLOSE", "K", "D")
    widths = [max(len(headers[i]), *(len(row[i]) for row in displayed)) for i in range(4)]
    def line(row):
        return f"{row[0]:<{widths[0]}} " + " ".join(f"{row[i]:>{widths[i]}}" for i in range(1, 4))
    lines = [f"{session} | 19/19 | Stoch 14,3,3", line(headers)]
    lines.extend(line(row) for row in displayed)
    lines.extend((f"Crossings: {crossings} | Below 20: {sum(row[2] < 20 for row in rows)}",
                  f"Warnings: {warning_count} sample; {session_warnings} on session"))
    if demonstration:
        lines.insert(0, "DEMONSTRATION - previously verified data")
        lines.append("Not a live scheduled result. Manual review.")
    else:
        lines.append("Informational screening. Manual review.")
    body = "\n".join(lines)
    try:
        validate_message(TITLE + (" TEST" if demonstration else ""), body)
    except PushError:
        raise ReportError("Complete report exceeds Pushover limits or contains invalid text; nothing sent.") from None
    return body


def send_daily_report(token, user_key, screening, *, demonstration=False):
    """One explicitly authorized send after full preflight. No retries or fallback.

    Return only on API acceptance; phone receipt requires operator confirmation.
    Credential access belongs to the caller, not the formatter.
    """
    body = format_daily_report(screening, demonstration=demonstration)
    try:
        _send_message(token, user_key, TITLE + (" TEST" if demonstration else ""), body, monospace=True)
    except PushError:
        raise
    except Exception:
        raise PushError("Unexpected daily-report request failure; acceptance is unknown. Details suppressed. No retry.") from None
