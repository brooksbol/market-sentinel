"""TA-Lib Stochastic(14,3,3) on caller-supplied completed sessions.

No calendar inference, price adjustment, missing-value substitution or I/O.
None means unavailable; zero_range identifies an undefined raw-K window.
Raw K is separately calculated informational context, not a STOCH output.
K/D mathematics belong to TA-Lib; validity masking belongs to Market Sentinel.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from math import isfinite

import numpy as np
import talib


@dataclass(frozen=True)
class DailyOHLC:
    session: date
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class RangeWarning:
    session: date
    code: str
    value: float
    low: float
    high: float


def _range_warnings(bar: DailyOHLC) -> tuple[RangeWarning, ...]:
    """Classify already validated prices without changing them."""
    warnings = []
    if bar.close < bar.low:
        warnings.append(RangeWarning(bar.session, "close_below_low", bar.close, bar.low, bar.high))
    elif bar.close > bar.high:
        warnings.append(RangeWarning(bar.session, "close_above_high", bar.close, bar.low, bar.high))
    if not bar.low <= bar.open <= bar.high:
        warnings.append(RangeWarning(bar.session, "open_outside_range", bar.open, bar.low, bar.high))
    return tuple(warnings)


@dataclass(frozen=True)
class StochasticPoint:
    session: date
    raw_k: float | None
    k: float | None
    d: float | None
    crossed_below_20: bool
    zero_range: bool
    warnings: tuple[RangeWarning, ...] = ()


def _number(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("Prices and indicator values must be finite int/float numbers.")
    try:
        number = float(value)
    except OverflowError:
        raise ValueError("Number is outside the supported floating-point range.") from None
    if not isfinite(number):
        raise ValueError("Prices and indicator values must be finite.")
    return number


def crossed_below_20(previous: float | None, current: float | None) -> bool:
    """Compare adjacent session K values without rounding or durable state.

    None cannot establish a crossing. Nonfinite values are errors, including
    when the other value is None. Finite values outside [0,100] can arise from
    warned source prices and are compared unchanged. No rounding, clamping,
    threshold tolerance, raw-K or D participation.
    """
    values = [None if value is None else _number(value) for value in (previous, current)]
    previous, current = values
    return previous is not None and current is not None and previous >= 20 and current < 20


def _validated(observations: Iterable[DailyOHLC]) -> tuple[DailyOHLC, ...]:
    bars = []
    for bar in observations:
        if not isinstance(bar, DailyOHLC) or type(bar.session) is not date:
            raise ValueError("Each observation must be DailyOHLC with a date session (not datetime).")
        if bars and bar.session <= bars[-1].session:
            raise ValueError("Sessions must be unique and strictly increasing, oldest first.")
        opening, high, low, close = map(_number, (bar.open, bar.high, bar.low, bar.close))
        if min(opening, high, low, close) <= 0 or high < low:
            raise ValueError("OHLC must be positive with low <= high.")
        if not isfinite(high + low):
            # TA-Lib's scaled-zero guard uses |high|+|low|. Overflow there can
            # silently produce zero for a nonflat range instead of a usable K.
            raise ValueError("OHLC magnitude exceeds the safe TA-Lib calculation range.")
        bars.append(DailyOHLC(bar.session, opening, high, low, close))
    return tuple(bars)


def stochastic_14_3_3(observations: Iterable[DailyOHLC]) -> tuple[StochasticPoint, ...]:
    """Return one immutable point per supplied observation, including warm-up.

    Caller guarantees completed, contiguous trading-session coverage and a common
    source basis for a single security. Date gaps are not interpreted:
    weekends/holidays cannot be distinguished from omitted sessions here.

    Validate the entire input before calculating. Empty input returns (). Missing
    records/field values, structurally invalid OHLC or duplicate/out-of-order dates
    raise ValueError. Positive finite open/close outside [low,high] are warnings
    on the corresponding point, not failures. Prices and finite outputs are not
    repaired or clamped; warned series may still cross below 20.
    STOCH aligns K/D to the same lookback: both first appear at bar 18. Raw K
    remains informational from bar 14. Exact zero-range windows make raw K None;
    mask K for three affected raw windows and D for five. This preserves the
    no-undefined-crossing rule without maintaining custom smoothing mathematics.
    Other finite outputs follow TA-Lib conventions, including near-flat tolerance.
    Nonfinite library outputs become None, never a crossing. No explicit rounding.
    """
    bars = _validated(observations)
    if not bars:
        return ()
    slow_k, slow_d = talib.STOCH(
        np.array([bar.high for bar in bars], dtype=np.float64),
        np.array([bar.low for bar in bars], dtype=np.float64),
        np.array([bar.close for bar in bars], dtype=np.float64),
        fastk_period=14, slowk_period=3, slowk_matype=0,
        slowd_period=3, slowd_matype=0,
    )
    range_available = []
    points = []
    for index, bar in enumerate(bars):
        raw_k = None
        zero_range = False
        if index >= 13:
            window = bars[index - 13:index + 1]
            lowest = min(item.low for item in window)
            highest = max(item.high for item in window)
            zero_range = highest == lowest
            if not zero_range:
                raw_k = ((bar.close - lowest) / (highest - lowest)) * 100
                if not isfinite(raw_k):
                    raw_k = None
        # Only warm-up/exact-flat windows mask library outputs. An overflow in
        # separately calculated informational raw K must not replace finite K/D.
        range_available.append(index >= 13 and not zero_range)
        # Three raw values support K; five support D (SMA3 of SMA3). Do not
        # expose TA-Lib's numeric zero substitute as an exact-flat signal.
        k = float(slow_k[index]) if isfinite(slow_k[index]) and all(range_available[-3:]) else None
        d = float(slow_d[index]) if isfinite(slow_d[index]) and all(range_available[-5:]) else None
        previous_k = points[-1].k if points else None
        points.append(StochasticPoint(
            session=bar.session, raw_k=raw_k, k=k, d=d,
            crossed_below_20=crossed_below_20(previous_k, k), zero_range=zero_range,
            warnings=_range_warnings(bar),
        ))
    return tuple(points)
