"""BasisMarket — multi-pair FX swap basis registry with cross triangulation.

Cross-pair basis is derived via USD triangulation using the no-arbitrage
relationship between the two USD-leg forward curves.

Two triangulation configurations are supported:

    1. Both legs vs USD  (e.g. EUR/USD + GBP/USD → EUR/GBP):

        F_XY = F_XUSD / F_YUSD
        →  1 + r_X_impl_XY × T = (1 + r_X_impl_XUSD × T) × (1 + r_Y_actual × T)
                                / (1 + r_Y_impl_YUSD × T)

    2. Base vs USD, USD vs quote  (e.g. EUR/USD + USD/JPY → EUR/JPY):

        F_XY = F_XUSD × F_USDY
        →  1 + r_X_impl_XY × T = (1 + r_X_impl_XUSD × T) × (1 + r_USD_impl_USDY × T)
                                / (1 + r_USD_actual × T)

In both cases: basis_XY (bps) = (r_X_impl_XY − r_X_actual) × 10,000

First-order approximations (valid for T ≤ 1 yr, rates < 15%):
    Case 1:  basis_XY ≈ basis_XUSD − basis_YUSD
    Case 2:  basis_XY ≈ basis_XUSD + basis_USDY
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .basis import FXSwapBasis
from .curve import BasisCurve
from .utils import tenor_to_years


class BasisMarket:
    """
    Registry of FXSwapBasis instances with cross-pair triangulation via USD.

    Register direct pairs (where one currency is USD) explicitly. Any
    non-USD cross pair is synthesised on demand from the registered USD legs.
    The triangulated basis is exact, not a first-order approximation.

    Parameters
    ----------
    *bases : FXSwapBasis
        Optional direct-market pairs to register at construction time.

    Examples
    --------
    >>> market = BasisMarket(eurusd, gbpusd)
    >>> market.add(usdjpy)
    >>> market.basis_bps("EURGBP", "3M")   # triangulated via USD
    >>> market.basis_bps("EURJPY", "3M")   # triangulated via USD
    >>> market.curve("EURGBP")             # BasisCurve for cross
    >>> market.refresh_all()               # re-fetch all snapshots
    >>> market.summary()                   # DataFrame of all registered pairs
    """

    def __init__(self, *bases: FXSwapBasis) -> None:
        self._registry: dict[str, FXSwapBasis] = {}
        for b in bases:
            self.add(b)

    # ------------------------------------------------------------------
    # Registry management
    # ------------------------------------------------------------------

    def add(self, basis: FXSwapBasis) -> "BasisMarket":
        """Register a direct-market FXSwapBasis. Returns self for chaining."""
        self._registry[basis.pair] = basis
        return self

    def remove(self, pair: str) -> None:
        """Remove a registered pair. Raises KeyError if not found."""
        pair = pair.upper()
        if pair not in self._registry:
            raise KeyError(f"Pair {pair!r} is not registered")
        del self._registry[pair]

    def pairs(self) -> list[str]:
        """All registered direct-market pair strings."""
        return list(self._registry)

    def __contains__(self, pair: str) -> bool:
        return pair.upper() in self._registry

    def __getitem__(self, pair: str) -> FXSwapBasis:
        """Return a registered FXSwapBasis by pair string (direct pairs only)."""
        pair = pair.upper()
        if pair not in self._registry:
            raise KeyError(
                f"Pair {pair!r} is not registered. "
                "Use basis_bps() or curve() for cross pairs."
            )
        return self._registry[pair]

    def __len__(self) -> int:
        return len(self._registry)

    def __repr__(self) -> str:  # pragma: no cover
        return f"BasisMarket(pairs={self.pairs()!r})"

    # ------------------------------------------------------------------
    # Core queries
    # ------------------------------------------------------------------

    def basis_bps(self, pair: str, tenor: str) -> float:
        """
        CIP basis spread in bps for a pair at a given tenor.

        For registered direct pairs, delegates to FXSwapBasis.basis_bps().
        For non-USD crosses, triangulates via USD using the registered legs.

        Parameters
        ----------
        pair : str
            6-character pair string, e.g. "EURGBP" or "EURUSD".
        tenor : str
            Tenor label, e.g. "3M".

        Returns
        -------
        float
            Basis spread in bps.

        Raises
        ------
        KeyError
            If the pair cannot be triangulated from registered pairs.
        """
        pair = pair.upper()
        if pair in self._registry:
            return self._registry[pair].basis_bps(tenor)
        return self._triangulate_bps(pair, tenor)

    def curve(self, pair: str) -> BasisCurve:
        """
        Full basis curve for a pair (direct or triangulated via USD).

        For cross pairs, basis is computed at the intersection of tenors
        available in both USD legs.

        Parameters
        ----------
        pair : str
            6-character pair string.

        Returns
        -------
        BasisCurve
        """
        pair = pair.upper()
        if pair in self._registry:
            return self._registry[pair].curve()
        return self._triangulate_curve(pair)

    def refresh_all(self) -> None:
        """Re-fetch market data for all registered pairs."""
        for basis in self._registry.values():
            basis.refresh()

    def summary(
        self,
        tenors: list[str] | None = None,
        pairs: list[str] | None = None,
    ) -> pd.DataFrame:
        """
        Basis spread in bps across pairs and tenors as a DataFrame.

        Parameters
        ----------
        tenors : list[str] | None
            Tenor labels to include. If None, uses the tenors from the first
            registered pair's curve.
        pairs : list[str] | None
            Pair strings to include. May contain cross pairs — these are
            triangulated on demand. If None, uses all registered direct pairs.

        Returns
        -------
        pd.DataFrame
            Index: tenor labels, columns: pair strings, values: basis in bps.
            NaN where a pair/tenor combination is unavailable.
        """
        if not self._registry:
            return pd.DataFrame()

        if tenors is None:
            first = next(iter(self._registry.values()))
            tenors = list(first.curve().tenors)

        if pairs is None:
            pairs = list(self._registry)

        data: dict[str, dict[str, float]] = {}
        for pair in pairs:
            col: dict[str, float] = {}
            for tenor in tenors:
                try:
                    col[tenor] = self.basis_bps(pair, tenor)
                except (KeyError, ValueError):
                    col[tenor] = float("nan")
            data[pair] = col

        return pd.DataFrame(data, index=tenors)

    # ------------------------------------------------------------------
    # Cross triangulation internals
    # ------------------------------------------------------------------

    def _triangulate_bps(self, pair: str, tenor: str) -> float:
        base, quote = _split_pair(pair)
        base_leg, quote_leg, case = self._resolve_usd_legs(pair, base, quote)
        t = tenor_to_years(tenor)
        return _cross_basis_bps(base_leg, quote_leg, case, tenor, t)

    def _triangulate_curve(self, pair: str) -> BasisCurve:
        base, quote = _split_pair(pair)
        base_leg, quote_leg, case = self._resolve_usd_legs(pair, base, quote)

        # Use tenors common to both legs
        common = set(base_leg.curve().tenors) & set(quote_leg.curve().tenors)
        if not common:
            raise ValueError(
                f"No common tenors between {base_leg.pair} and {quote_leg.pair} "
                f"to build a cross curve for {pair}"
            )

        tenors = sorted(common, key=tenor_to_years)
        times = np.array([tenor_to_years(t) for t in tenors])
        basis = np.array([
            _cross_basis_bps(base_leg, quote_leg, case, tenor, tenor_to_years(tenor))
            for tenor in tenors
        ])
        return BasisCurve(pair=pair, tenors=tenors, times=times, basis_bps=basis)

    def _resolve_usd_legs(
        self, pair: str, base: str, quote: str
    ) -> tuple[FXSwapBasis, FXSwapBasis, str]:
        """
        Find the registered USD legs needed to triangulate base/quote.

        Checks in priority order:
        1. base/USD + quote/USD  → case "xusd_yusd"
        2. base/USD + USD/quote  → case "xusd_usdy"

        Raises
        ------
        KeyError
            If no valid triangulation path is found in the registry.
        """
        base_vs_usd = base + "USD"
        quote_vs_usd = quote + "USD"
        usd_vs_quote = "USD" + quote

        if base_vs_usd in self._registry:
            if quote_vs_usd in self._registry:
                return (
                    self._registry[base_vs_usd],
                    self._registry[quote_vs_usd],
                    "xusd_yusd",
                )
            if usd_vs_quote in self._registry:
                return (
                    self._registry[base_vs_usd],
                    self._registry[usd_vs_quote],
                    "xusd_usdy",
                )

        raise KeyError(
            f"Cannot triangulate {pair!r} via USD. "
            f"Need {base_vs_usd!r} and one of ({quote_vs_usd!r}, {usd_vs_quote!r}) "
            f"in the registry. Registered pairs: {self.pairs()}"
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _split_pair(pair: str) -> tuple[str, str]:
    """Split a 6-character pair string into (base, quote)."""
    if len(pair) != 6:
        raise ValueError(f"Expected a 6-character pair string, got {pair!r}")
    return pair[:3], pair[3:]


def _cross_basis_bps(
    base_leg: FXSwapBasis,
    quote_leg: FXSwapBasis,
    case: str,
    tenor: str,
    t: float,
) -> float:
    """
    Exact cross-pair CIP basis in bps via two-leg USD triangulation.

    In both cases r_X_actual and r_Q_actual are recovered from the
    public implied_rate() and basis_bps() of each leg — no private
    attribute access required.

    Parameters
    ----------
    base_leg : FXSwapBasis
        The registered pair whose base currency is the cross base (X).
        Must be X/USD for case "xusd_yusd" or X/USD for "xusd_usdy".
    quote_leg : FXSwapBasis
        The registered pair for the other USD leg.
        Y/USD for "xusd_yusd", USD/Y for "xusd_usdy".
    case : str
        "xusd_yusd" or "xusd_usdy".
    tenor : str
        Tenor label (must exist in both legs' swap points).
    t : float
        Year fraction for this tenor.

    Returns
    -------
    float
        Cross-pair basis in bps.
    """
    # Base-leg quantities (X/USD in both cases: base=X, quote=USD)
    r_x_impl = base_leg.implied_rate(tenor)          # implied X rate from USD swap
    r_x_actual = r_x_impl - base_leg.basis_bps(tenor) / 10_000

    # Quote-leg quantities differ by case
    r_q_impl = quote_leg.implied_rate(tenor)
    r_q_actual = r_q_impl - quote_leg.basis_bps(tenor) / 10_000

    if case == "xusd_yusd":
        # base_leg = X/USD, quote_leg = Y/USD
        # r_q_impl = implied Y rate, r_q_actual = actual Y rate
        # Formula: 1 + r_X_impl_XY × T
        #        = (1 + r_X_impl_XUSD × T) × (1 + r_Y_actual × T)
        #          / (1 + r_Y_impl_YUSD × T)
        numerator = (1.0 + r_x_impl * t) * (1.0 + r_q_actual * t)
        denominator = 1.0 + r_q_impl * t

    else:
        # case == "xusd_usdy"
        # base_leg = X/USD, quote_leg = USD/Y (base=USD)
        # r_q_impl = implied USD rate from Y swaps, r_q_actual = actual USD rate
        # Formula: 1 + r_X_impl_XY × T
        #        = (1 + r_X_impl_XUSD × T) × (1 + r_USD_impl_USDY × T)
        #          / (1 + r_USD_actual × T)
        numerator = (1.0 + r_x_impl * t) * (1.0 + r_q_impl * t)
        denominator = 1.0 + r_q_actual * t

    r_x_impl_cross = (numerator / denominator - 1.0) / t
    return (r_x_impl_cross - r_x_actual) * 10_000
