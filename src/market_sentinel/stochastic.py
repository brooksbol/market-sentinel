"""Pure standard Stochastic(14,3,3) on caller-supplied completed sessions.

No calendar inference, price adjustment, missing-value substitution or I/O.
None means unavailable; zero_range identifies an undefined raw-K window.
Smoothing requires three consecutive available values, never skips a gap.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from math import fsum, isfinite


@dataclass(frozen=True)
class DailyOHLC:
    session: date
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class StochasticPoint:
    session: date
    raw_k: float | None
    k: float | None
    d: float | None
    crossed_below_20: bool
    zero_range: bool


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

    None cannot establish a crossing. Nonfinite/out-of-range values are errors,
    including when the other value is None. No raw-K or D value is consulted.
    """
    values = [None if value is None else _number(value) for value in (previous, current)]
    if any(value is not None and not 0 <= value <= 100 for value in values):
        raise ValueError("Stochastic values must be between 0 and 100.")
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
        if not 0 < low <= opening <= high or not low <= close <= high:
            raise ValueError("OHLC must be positive with low <= open/close <= high.")
        bars.append(DailyOHLC(bar.session, opening, high, low, close))
    return tuple(bars)


def _sma3(values: Sequence[float | None]) -> float | None:
    window = values[-3:]
    if len(window) != 3 or any(value is None for value in window):
        return None
    return fsum(window) / 3


def stochastic_14_3_3(observations: Iterable[DailyOHLC]) -> tuple[StochasticPoint, ...]:
    """Return one immutable point per supplied observation, including warm-up.

    Caller guarantees completed, contiguous trading-session coverage and a common
    OHLC adjustment basis for a single security. Date gaps are not interpreted:
    weekends/holidays cannot be distinguished from omitted sessions here.

    Validate the entire input before calculating. Empty input returns (). Missing
    records/field values, invalid OHLC or duplicate/out-of-order dates raise ValueError.
    A zero 14-bar range makes raw K unavailable; K/D require fresh consecutive
    valid smoothing windows afterward. Crossings never bridge unavailable K.
    Arithmetic uses Python floats without explicit rounding or price adjustment.
    """
    bars = _validated(observations)
    raw_values = []
    k_values = []
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
        raw_values.append(raw_k)
        k = _sma3(raw_values)
        previous_k = k_values[-1] if k_values else None
        k_values.append(k)
        points.append(StochasticPoint(
            session=bar.session, raw_k=raw_k, k=k, d=_sma3(k_values),
            crossed_below_20=crossed_below_20(previous_k, k), zero_range=zero_range,
        ))
    return tuple(points)
