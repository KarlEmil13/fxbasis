"""FXSwapBasis — core single-pair FX swap basis calculator.

Computes the CIP deviation (basis spread) for a currency pair by comparing:
    - The implied base currency OIS rate derived from the FX swap market
    - The actual base currency OIS rate from the money market

For EUR/USD (base=EUR, quote=USD, spot quoted as USD per EUR):

    Forward outright:   F = S + swap_points / 10^pip_scale

    No-arbitrage (CIP):
        F / S = (1 + r_USD × T) / (1 + r_EUR_implied × T)

    Implied EUR rate:
        r_EUR_implied = [(1 + r_USD × T) × S/F − 1] / T

    Basis (bps):
        basis = (r_EUR_implied − r_EUR_actual) × 10,000

A negative basis means EUR is cheaper to borrow via the FX swap market
than in the money market — investors pay a premium to access USD.

Each instance represents an atomic market snapshot. All data (spot, swap
points, OIS rates) is fetched together via the DataProvider to avoid
timing noise. Call refresh() to update the snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import numpy as np

from .curve import BasisCurve
from .ois import OISCurve
from .providers.base import DataProvider
from .utils import forward_outright, tenor_to_years


@dataclass
class _Snapshot:
    """Immutable market data captured at a single point in time."""

    as_of: datetime
    spot: float
    swap_points: dict[str, float]   # tenor → raw pips
    pip_scale: int
    base_ois: OISCurve              # base currency (e.g. EUR)
    quote_ois: OISCurve             # quote currency (e.g. USD)


class FXSwapBasis:
    """
    FX swap basis calculator for a single currency pair.

    Parameters
    ----------
    base : str
        Base currency ISO code (e.g. "EUR").
    quote : str
        Quote currency ISO code (e.g. "USD").
    provider : DataProvider
        Market data source (StaticProvider or BloombergProvider).
    day_count_basis : int
        Denominator for ACT/x year fractions. Default 360.

    Examples
    --------
    >>> from fxbasis.providers import StaticProvider
    >>> provider = StaticProvider(...)
    >>> eurusd = FXSwapBasis("EUR", "USD", provider)
    >>> eurusd.basis_bps("3M")
    -14.7
    >>> eurusd.curve().to_series()
    ON     -3.1
    1W     -6.2
    ...
    """

    def __init__(
        self,
        base: str,
        quote: str,
        provider: DataProvider,
        day_count_basis: int = 360,
    ) -> None:
        self.base = base.upper()
        self.quote = quote.upper()
        self.pair = f"{self.base}{self.quote}"
        self._provider = provider
        self._day_count_basis = day_count_basis
        self._snapshot: _Snapshot = self._fetch_snapshot()

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_snapshot(self) -> _Snapshot:
        """Fetch all market data atomically from the provider."""
        as_of = self._provider.get_as_of()
        spot = self._provider.get_spot(self.pair)
        swap_points = self._provider.get_swap_points(self.pair)
        pip_scale = self._provider.get_pip_scale(self.pair)

        base_ois = self._build_ois_curve(self.base, as_of)
        quote_ois = self._build_ois_curve(self.quote, as_of)

        return _Snapshot(
            as_of=as_of,
            spot=spot,
            swap_points=swap_points,
            pip_scale=pip_scale,
            base_ois=base_ois,
            quote_ois=quote_ois,
        )

    def _build_ois_curve(self, currency: str, as_of: datetime) -> OISCurve:
        """
        Build an OISCurve for a currency by merging meeting-dated and
        standard tenor par rates into a unified knot grid.

        Meeting-dated knots take priority where they overlap with standard tenors.
        """
        standard = self._provider.get_ois_rates(currency)
        meeting = self._provider.get_meeting_ois_rates(currency)

        # Build unified knot grid: {year_fraction: par_rate}
        par_rates: dict[float, float] = {}

        # 1. Add standard tenor knots
        for tenor, rate in standard.items():
            t = tenor_to_years(tenor, self._day_count_basis)
            par_rates[t] = rate

        # 2. Add (or override with) meeting-dated knots
        # Keys from provider are ISO date strings "YYYY-MM-DD"
        as_of_date = as_of.date() if isinstance(as_of, datetime) else as_of
        for date_str, rate in meeting.items():
            meeting_date = date.fromisoformat(date_str)
            days = (meeting_date - as_of_date).days
            if days <= 0:
                continue  # Skip past meetings
            t = days / self._day_count_basis
            par_rates[t] = rate  # Overrides standard tenor if same t

        return OISCurve.from_par_rates(
            currency=currency,
            as_of=as_of_date,
            par_rates=par_rates,
        )

    # ------------------------------------------------------------------
    # Core calculations
    # ------------------------------------------------------------------

    def implied_rate(self, tenor: str) -> float:
        """
        Implied base currency OIS rate derived from the FX swap market.

        Uses no-arbitrage (CIP):
            r_base_implied = [(1 + r_quote × T) × S/F − 1] / T

        Parameters
        ----------
        tenor : str
            Tenor label, e.g. "3M".

        Returns
        -------
        float
            Implied base currency rate (decimal).
        """
        snap = self._snapshot
        t = tenor_to_years(tenor, self._day_count_basis)

        S = snap.spot
        raw_pips = snap.swap_points[tenor]
        F = forward_outright(S, raw_pips, snap.pip_scale)

        r_quote = snap.quote_ois.rate(t)
        return ((1.0 + r_quote * t) * (S / F) - 1.0) / t

    def basis_bps(self, tenor: str) -> float:
        """
        CIP deviation (basis spread) in basis points.

        basis = (r_base_implied − r_base_actual) × 10,000

        A negative value means the base currency is cheap to borrow
        via the FX swap market relative to the money market.

        Parameters
        ----------
        tenor : str
            Tenor label, e.g. "3M".

        Returns
        -------
        float
            Basis in bps.
        """
        t = tenor_to_years(tenor, self._day_count_basis)
        r_implied = self.implied_rate(tenor)
        r_actual = self._snapshot.base_ois.rate(t)
        return (r_implied - r_actual) * 10_000

    def curve(self) -> BasisCurve:
        """
        Full basis curve across all available swap point tenors.

        Returns
        -------
        BasisCurve
            Tenor-structured basis curve with PCHIP interpolation.
        """
        tenors_raw = list(self._snapshot.swap_points.keys())

        # Sort by year fraction
        tenors = sorted(tenors_raw, key=lambda t: tenor_to_years(t, self._day_count_basis))
        times = np.array([tenor_to_years(t, self._day_count_basis) for t in tenors])
        basis = np.array([self.basis_bps(t) for t in tenors])

        return BasisCurve(pair=self.pair, tenors=tenors, times=times, basis_bps=basis)

    # ------------------------------------------------------------------
    # Snapshot management
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-fetch all market data atomically and update the snapshot."""
        self._snapshot = self._fetch_snapshot()

    @property
    def as_of(self) -> datetime:
        """Timestamp of the current data snapshot."""
        return self._snapshot.as_of

    @property
    def spot(self) -> float:
        """Spot FX rate from the current snapshot."""
        return self._snapshot.spot

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"FXSwapBasis(pair={self.pair!r}, as_of={self.as_of!r})"
        )
