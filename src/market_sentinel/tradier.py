"""Bounded read-only daily history; no account/order endpoints or price adjustment."""

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from http.client import HTTPException
from math import isfinite
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from market_sentinel.stochastic import DailyOHLC, RangeWarning, _range_warnings, _validated

BASES = {"production": "https://api.tradier.com/v1/markets/history",
         "sandbox": "https://sandbox.tradier.com/v1/markets/history"}
MAX_RESPONSE_BYTES = 1_000_000
KEYCHAIN_SERVICE = "market-sentinel.tradier"


class TradierError(Exception):
    """Sanitized acquisition/setup failure, with no provider body or credential."""

    def __init__(self, message, *, stop_batch=False):
        super().__init__(message)
        self.stop_batch = stop_batch


@dataclass(frozen=True)
class History:
    symbol: str
    environment: str
    start: date
    end: date
    completed_through: date
    bars: tuple[DailyOHLC, ...]
    volumes: tuple[int | float | None, ...]
    excluded_sessions: tuple[date, ...]
    reordered: bool
    warnings: tuple[RangeWarning, ...] = ()


def _environment(environment):
    if environment not in BASES:
        raise TradierError("Choose production or sandbox explicitly.")


def _token(token):
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._~+/=-]{1,4096}", token):
        raise TradierError("Tradier token is missing or has an invalid format.")
    return token


def load_token(environment: str) -> str:
    """Environment handoff, otherwise one environment-specific macOS Keychain item."""
    _environment(environment)
    if "TRADIER_TOKEN" in os.environ:
        return _token(os.environ["TRADIER_TOKEN"])
    if sys.platform != "darwin":
        raise TradierError("Provision TRADIER_TOKEN securely at runtime.")
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
             "-a", environment + "-token", "-w"],
            capture_output=True, text=True, check=False, timeout=15)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise TradierError("Unable to read the Tradier Keychain item.") from None
    if result.returncode:
        raise TradierError("Tradier Keychain item unavailable; follow README setup.")
    return _token(result.stdout.strip())


def _dates(start, end, completed_through):
    if any(type(value) is not date for value in (start, end, completed_through)):
        raise TradierError("History dates must be date objects, not datetimes.")
    if start > end or (end - start).days > 366 or completed_through < start:
        raise TradierError("Use an ordered history range of at most 366 days and a valid cutoff.")


def _session(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise TradierError("Invalid historical session date.")
    try:
        session = date.fromisoformat(value)
    except ValueError:
        raise TradierError("Invalid historical session date.") from None
    if session.weekday() >= 5:
        raise TradierError("Unexpected weekend equity session; calendar coverage is unverified.")
    return session


def normalize_history(payload, *, symbol, environment, start, end, completed_through) -> History:
    """Validate all rows oldest first, exclude dates after caller-certified cutoff.

    No exchange calendar is inferred: weekday holidays and missing sessions remain
    unverified. Reject the entire response on invalid rows, including excluded rows.
    Optional/null volume remains None; supplied volume must be finite/nonnegative.
    """
    _environment(environment)
    _dates(start, end, completed_through)
    history = payload.get("history") if isinstance(payload, dict) else None
    if not isinstance(history, dict):
        raise TradierError("No usable daily history returned.")
    rows = history.get("day")
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list) or not rows or len(rows) > 367:
        raise TradierError("No usable daily history returned or response exceeds range bound.")
    parsed = []
    warnings = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise TradierError("Malformed daily history observation.")
        session = _session(row.get("date"))
        if session in seen:
            raise TradierError("Duplicate historical session; no indicator calculated.")
        if parsed and session <= parsed[-1][0].session:
            raise TradierError("Historical sessions must be strictly increasing; no sorting performed.")
        seen.add(session)
        if not start <= session <= end:
            raise TradierError("Historical session outside requested range.")
        try:
            bar = _validated([DailyOHLC(session, *(row[key] for key in
                                ("open", "high", "low", "close")))])[0]
        except (KeyError, ValueError, TypeError, OverflowError):
            raise TradierError("Structurally invalid OHLC: missing, malformed, nonfinite, nonpositive, inverted range or unsafe magnitude.") from None
        warnings.extend(_range_warnings(bar))
        volume = row.get("volume")
        if volume is not None:
            try:
                valid = type(volume) in (int, float) and isfinite(volume) and volume >= 0
            except OverflowError:
                valid = False
            if not valid:
                raise TradierError("Invalid historical volume.")
        parsed.append((bar, volume))
    completed = [(bar, volume) for bar, volume in parsed if bar.session <= completed_through]
    if not completed:
        raise TradierError("No observations at or before the completed-session cutoff.")
    return History(symbol, environment, start, end, completed_through,
                   tuple(bar for bar, _ in completed), tuple(volume for _, volume in completed),
                   tuple(bar.session for bar, _ in parsed if bar.session > completed_through),
                   False, tuple(warnings))


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_history(token: str, *, symbol: str, environment: str,
                  start: date, end: date, completed_through: date) -> History:
    """One fixed-endpoint GET with bounded read/timeout; no retries or raw error output.

    Caller certifies cutoff is a completed session. API presence alone is insufficient.
    """
    _environment(environment)
    _dates(start, end, completed_through)
    _token(token)
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z]{1,5}", symbol):
        raise TradierError("Use one uppercase equity symbol.")
    payload = _get_json(token, environment, "history", dict(
        symbol=symbol, interval="daily", start=start.isoformat(), end=end.isoformat()))
    return normalize_history(payload, symbol=symbol, environment=environment,
                             start=start, end=end, completed_through=completed_through)


def _get_json(token, environment, endpoint, parameters):
    """Shared bounded GET, restricted to history/calendar market-data endpoints."""
    _environment(environment)
    _token(token)
    if endpoint not in ("history", "calendar"):
        raise TradierError("Unsupported market-data endpoint.")
    url = BASES[environment].rsplit("/", 1)[0] + "/" + endpoint
    request = Request(url + "?" + urlencode(parameters), method="GET", headers={
        "Authorization": "Bearer " + token, "Accept": "application/json",
        "User-Agent": "Market-Sentinel-History-Proof/0.1"})
    opener = build_opener(ProxyHandler({}), _NoRedirects())
    try:
        with opener.open(request, timeout=15) as response:
            status = response.status
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        status = error.code
        try:
            raw = error.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, HTTPException):
            raw = b""
        finally:
            error.close()
        if status in (401, 403):
            raise TradierError("Tradier authentication/entitlement rejected; check environment and token.", stop_batch=True) from None
        if status == 429 or (status == 400 and b"Quota Violation" in raw):
            raise TradierError("Tradier rate limit reached; no automatic retry.", stop_batch=True) from None
        raise TradierError("Tradier HTTP failure; history not verified.") from None
    except (OSError, URLError, HTTPException):
        raise TradierError("Tradier network/TLS failure or timeout; history not verified.") from None
    if status != 200 or len(raw) > MAX_RESPONSE_BYTES:
        raise TradierError("Unexpected or oversized Tradier response.")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise TradierError("Malformed Tradier JSON response.") from None
    return payload
