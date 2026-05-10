"""BasisCurve — tenor-structured FX swap basis with PCHIP interpolation.

Holds basis spreads in bps at a set of tenor knots and provides:
- Smooth interpolation to any tenor via PCHIP (C¹ monotone-preserving spline)
- Forward basis between any two tenors
- Pandas Series output

PCHIP (Piecewise Cubic Hermite Interpolating Polynomial) was chosen because:
- C¹ continuous → smooth forward basis (no kinks)
- Monotone-preserving → no spurious oscillations between sparse knots
- Extrapolation is flat (hold terminal value) — polynomial extrapolation not used
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator

from .utils import tenor_to_years


@dataclass
class BasisCurve:
    """
    FX swap basis spread curve.

    Attributes
    ----------
    pair : str
        Currency pair, e.g. "EURUSD".
    tenors : list[str]
        Tenor labels at each knot, sorted by time (e.g. ["ON", "1W", "1M", ...]).
    times : np.ndarray
        Year fractions corresponding to each tenor knot.
    basis_bps : np.ndarray
        Basis spread in basis points at each tenor knot.
    """

    pair: str
    tenors: list[str]
    times: np.ndarray
    basis_bps: np.ndarray

    def __post_init__(self) -> None:
        if len(self.tenors) != len(self.times) != len(self.basis_bps):
            raise ValueError("tenors, times, and basis_bps must have the same length")
        if len(self.times) < 2:
            raise ValueError("At least 2 knot points are required for interpolation")
        self._interp = PchipInterpolator(self.times, self.basis_bps, extrapolate=False)

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def at(self, tenor: str | float) -> float:
        """
        Basis in bps at a given tenor (PCHIP interpolation).

        Outside the knot range, flat extrapolation is applied.

        Parameters
        ----------
        tenor : str | float
            Tenor label (e.g. "3M") or year fraction (e.g. 0.25).

        Returns
        -------
        float
            Basis spread in bps.
        """
        t = tenor_to_years(tenor) if isinstance(tenor, str) else float(tenor)
        val = self._interp(t)
        if np.isnan(val):
            # Outside knot range — flat extrapolation
            return float(self.basis_bps[0] if t < self.times[0] else self.basis_bps[-1])
        return float(val)

    def forward_basis(self, t1: str | float, t2: str | float) -> float:
        """
        Implied forward basis (in bps) for the period [t1, t2].

        Computed as the time-weighted difference of spot basis values:
            B_fwd(t1, t2) = (B(t2) × t2 − B(t1) × t1) / (t2 − t1)

        Parameters
        ----------
        t1 : str | float
            Start tenor label or year fraction.
        t2 : str | float
            End tenor label or year fraction.

        Returns
        -------
        float
            Forward basis in bps.
        """
        _t1 = tenor_to_years(t1) if isinstance(t1, str) else float(t1)
        _t2 = tenor_to_years(t2) if isinstance(t2, str) else float(t2)
        if _t2 <= _t1:
            raise ValueError(f"t2 ({t2}) must be greater than t1 ({t1})")
        b1 = self.at(_t1)
        b2 = self.at(_t2)
        return (b2 * _t2 - b1 * _t1) / (_t2 - _t1)

    def to_series(self) -> pd.Series:
        """Return basis as a pandas Series indexed by tenor label."""
        return pd.Series(self.basis_bps, index=self.tenors, name=f"{self.pair}_basis_bps")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"BasisCurve(pair={self.pair!r}, tenors={self.tenors}, "
            f"basis_bps={self.basis_bps.tolist()})"
        )
