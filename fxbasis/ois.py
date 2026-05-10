"""OISCurve — OIS discount factor curve for a single currency.

Construction pipeline (per the implementation plan):
    1. Bloomberg compounded OIS par rate R
       (fixed rate = compounded overnight floating leg: R × T = ∏(1 + rᵢ/360) − 1)
    2. Convert to discount factor:  DF = 1 / (1 + R × T)
    3. Convert to continuously compounded zero rate:  r = −ln(DF) / T
       Equivalence proof:  exp(−r×T) = exp(−[ln(1+R×T)/T]×T) = 1/(1+R×T)  ∎
    4. Build unified knot grid (meeting-dated + standard tenors), sorted by T
    5. Linearly interpolate r between knots  →  piecewise constant forward rates
    6. Query:  DF(t) = exp(−r(t)×t),  R(t) = (1/DF(t) − 1) / t
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np


@dataclass
class OISCurve:
    """
    OIS discount factor curve for a single currency.

    Attributes
    ----------
    currency : str
        ISO 4217 currency code (e.g. "USD", "EUR").
    as_of : date
        Valuation / snapshot date.
    knots : np.ndarray
        Year fractions at each knot point (sorted ascending).
    cc_rates : np.ndarray
        Continuously compounded zero rates at each knot.
    """

    currency: str
    as_of: date
    knots: np.ndarray
    cc_rates: np.ndarray

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_par_rates(
        cls,
        currency: str,
        as_of: date,
        par_rates: dict[float, float],
    ) -> "OISCurve":
        """
        Build an OISCurve from a mapping of year fraction → OIS par rate.

        The par rate is the Bloomberg compounded OIS rate R such that:
            R × T = ∏(1 + rᵢ/360) − 1

        Conversion pipeline:
            DF = 1 / (1 + R × T)
            log_df = ln(DF) = −ln(1 + R × T)

        Interpolation is log-linear on DF, i.e. linear interpolation on
        log(DF) in T-space. This gives piecewise constant instantaneous
        forward rates between knots.

        Note: linear-in-cc-rate ≠ log-linear-on-DF. The former makes
        log(DF) = r(T)×T quadratic in T; the latter keeps it linear.

        Parameters
        ----------
        currency : str
        as_of : date
        par_rates : dict[float, float]
            {year_fraction: compounded_ois_par_rate}
            Keys must be positive (T > 0).

        Returns
        -------
        OISCurve
        """
        if not par_rates:
            raise ValueError("par_rates must not be empty")

        for t in par_rates:
            if t <= 0:
                raise ValueError(f"Year fraction must be positive, got {t}")

        times = sorted(par_rates.keys())
        knots = np.array(times, dtype=float)
        # log_dfs[i] = ln(DF(T_i)) = -ln(1 + R_i × T_i)
        log_dfs = np.array(
            [-math.log1p(par_rates[t] * t) for t in times], dtype=float
        )
        # cc_rates stored for inspection only; NOT used for interpolation
        cc_rates = -log_dfs / knots
        return cls(currency=currency.upper(), as_of=as_of, knots=knots, cc_rates=cc_rates,
                   _log_dfs=log_dfs)

    # Internal log(DF) array used for interpolation
    _log_dfs: np.ndarray = None  # set by from_par_rates

    def __post_init__(self):
        # If constructed directly (not via from_par_rates), derive _log_dfs
        if self._log_dfs is None:
            object.__setattr__(self, '_log_dfs', -self.cc_rates * self.knots)

    # ------------------------------------------------------------------
    # Interpolation
    # ------------------------------------------------------------------

    def _interp_log_df(self, t: float) -> float:
        """
        Log-linear interpolation: linearly interpolate log(DF) in T.

        This gives piecewise constant instantaneous forward rates:
            f_inst = -d/dT[log(DF(T))] = constant between knots.

        Flat extrapolation outside knot range.
        """
        if t <= self.knots[0]:
            return float(self._log_dfs[0])
        if t >= self.knots[-1]:
            return float(self._log_dfs[-1])
        return float(np.interp(t, self.knots, self._log_dfs))

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    def discount_factor(self, t: float) -> float:
        """
        Discount factor at year fraction t.  DF(t) = exp(log_df(t)).
        """
        if t < 0:
            raise ValueError(f"Year fraction must be non-negative, got {t}")
        if t == 0.0:
            return 1.0
        log_df = self._interp_log_df(t)
        return math.exp(log_df)

    def rate(self, t: float) -> float:
        """
        Compounded OIS par rate at year fraction t.

        Inverts the discount factor:  R(t) = (1 / DF(t) − 1) / t

        Parameters
        ----------
        t : float
            Year fraction (must be > 0).

        Returns
        -------
        float
            Compounded OIS par rate (decimal, same convention as Bloomberg input).
        """
        if t <= 0:
            raise ValueError(f"Year fraction must be positive, got {t}")
        df = self.discount_factor(t)
        return (1.0 / df - 1.0) / t

    def forward_rate(self, t1: float, t2: float) -> float:
        """
        Implied forward OIS rate for the period [t1, t2].

        Derived from the ratio of discount factors:
            (1 + R_fwd × (t2 − t1)) = DF(t1) / DF(t2)

        Parameters
        ----------
        t1 : float
            Start year fraction.
        t2 : float
            End year fraction (must be > t1).

        Returns
        -------
        float
            Compounded forward rate (decimal).
        """
        if t2 <= t1:
            raise ValueError(f"t2 ({t2}) must be greater than t1 ({t1})")
        df1 = self.discount_factor(t1)
        df2 = self.discount_factor(t2)
        return (df1 / df2 - 1.0) / (t2 - t1)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"OISCurve(currency={self.currency!r}, as_of={self.as_of}, "
            f"knots={len(self.knots)})"
        )
