"""Shared utilities: tenor parsing, year fractions, pip scaling."""

from datetime import date

# ---------------------------------------------------------------------------
# Tenor label → approximate calendar days
# Used when actual settlement dates are not available (e.g. StaticProvider).
# For precision, compute year fractions from actual dates instead.
# ---------------------------------------------------------------------------
TENOR_DAYS: dict[str, int] = {
    "ON": 1,
    "TN": 1,
    "SW": 7,
    "1W": 7,
    "2W": 14,
    "1M": 30,
    "2M": 61,
    "3M": 92,
    "4M": 122,
    "5M": 153,
    "6M": 183,
    "9M": 274,
    "1Y": 365,
    "2Y": 730,
}


def tenor_to_years(tenor: str, day_count_basis: int = 360) -> float:
    """
    Convert a standard tenor label to a year fraction.

    Uses approximate calendar day counts (see TENOR_DAYS).
    For production accuracy, derive from actual settlement dates.

    Parameters
    ----------
    tenor : str
        E.g. "ON", "1W", "3M", "1Y".
    day_count_basis : int
        360 for ACT/360 currencies, 365 for ACT/365.

    Returns
    -------
    float
        Year fraction.
    """
    tenor = tenor.upper()
    if tenor not in TENOR_DAYS:
        raise ValueError(
            f"Unknown tenor '{tenor}'. Known tenors: {list(TENOR_DAYS)}"
        )
    return TENOR_DAYS[tenor] / day_count_basis


def date_to_years(target: date, as_of: date, day_count_basis: int = 360) -> float:
    """
    Convert an actual date to a year fraction relative to as_of.

    Used for meeting-dated OIS knots where we have exact dates.

    Parameters
    ----------
    target : date
        The target date (e.g. a CB meeting effective date).
    as_of : date
        The snapshot/valuation date.
    day_count_basis : int
        360 or 365.

    Returns
    -------
    float
        Year fraction. Always >= 0.
    """
    days = (target - as_of).days
    if days < 0:
        raise ValueError(f"Target date {target} is before as_of {as_of}")
    return days / day_count_basis


def scale_swap_points(raw_pips: float, pip_scale: int) -> float:
    """
    Convert raw Bloomberg swap point pips to an FX rate adjustment.

    Parameters
    ----------
    raw_pips : float
        Raw swap points as quoted by Bloomberg.
    pip_scale : int
        Number of decimal places (e.g. 4 for EURUSD → divide by 10,000).

    Returns
    -------
    float
        Swap point adjustment to add to spot to get the forward outright.
    """
    return raw_pips / (10 ** pip_scale)


def forward_outright(spot: float, raw_pips: float, pip_scale: int) -> float:
    """
    Compute the forward outright from spot and swap points.

    Parameters
    ----------
    spot : float
        Spot FX rate.
    raw_pips : float
        Raw Bloomberg swap points.
    pip_scale : int
        Decimal places for this pair.

    Returns
    -------
    float
        Forward outright rate.
    """
    return spot + scale_swap_points(raw_pips, pip_scale)
