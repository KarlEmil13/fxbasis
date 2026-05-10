"""DataProvider protocol — the interface all providers must satisfy."""

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class DataProvider(Protocol):
    """
    Abstract interface for market data sources.

    All methods return data for a consistent point-in-time snapshot.
    Implementations must fetch all data atomically (or as close as possible)
    to avoid timing noise in the basis calculation.
    """

    def get_as_of(self) -> datetime:
        """Timestamp of this data snapshot."""
        ...

    def get_spot(self, pair: str) -> float:
        """
        Spot FX rate for a currency pair.

        Parameters
        ----------
        pair : str
            Standardised pair string, e.g. "EURUSD".

        Returns
        -------
        float
            Mid spot rate.
        """
        ...

    def get_swap_points(self, pair: str) -> dict[str, float]:
        """
        FX swap points per tenor label, in raw Bloomberg pips.

        Parameters
        ----------
        pair : str
            E.g. "EURUSD".

        Returns
        -------
        dict[str, float]
            Mapping of tenor label → raw pips, e.g. {"1M": -15.3, "3M": -45.1}.
            The caller is responsible for scaling via pip_scale.
        """
        ...

    def get_pip_scale(self, pair: str) -> int:
        """
        Number of decimal places for swap points of this pair.

        E.g. 4 for EURUSD (divide pips by 10,000), 2 for USDJPY.
        """
        ...

    def get_ois_rates(self, currency: str) -> dict[str, float]:
        """
        Standard tenor OIS par rates for a currency.

        Bloomberg OIS rates are compounded rates — the fixed rate set equal
        to the compounded overnight floating leg at fair value:
            R × T = ∏(1 + rᵢ/360) − 1

        Parameters
        ----------
        currency : str
            ISO 4217 code, e.g. "USD", "EUR".

        Returns
        -------
        dict[str, float]
            Mapping of tenor label → par rate (decimal), e.g. {"3M": 0.0520}.
        """
        ...

    def get_meeting_ois_rates(self, currency: str) -> dict[str, float]:
        """
        Meeting-dated OIS par rates for a currency.

        These span from today to each central bank meeting's effective date,
        providing fine-grained short-end calibration.

        Parameters
        ----------
        currency : str
            ISO 4217 code.

        Returns
        -------
        dict[str, float]
            Mapping of ISO date string → par rate (decimal),
            e.g. {"2025-06-11": 0.0535, "2025-07-30": 0.0525}.
            Returns empty dict if no meeting swaps are available.
        """
        ...
