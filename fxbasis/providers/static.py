"""StaticProvider — manual / test data provider."""

from datetime import datetime
from .base import DataProvider


class StaticProvider:
    """
    A DataProvider backed by manually supplied data.

    Useful for unit testing and for working without a live Bloomberg connection.
    All data is supplied at construction time and treated as a single snapshot.

    Example
    -------
    >>> provider = StaticProvider(
    ...     as_of=datetime(2025, 5, 9, 10, 0),
    ...     spot={"EURUSD": 1.0850},
    ...     swap_points={"EURUSD": {"ON": -0.5, "1W": -3.5, "1M": -15.0,
    ...                             "3M": -45.0, "6M": -90.0, "9M": -130.0, "1Y": -175.0}},
    ...     pip_scale={"EURUSD": 4},
    ...     ois_rates={
    ...         "USD": {"ON": 0.0530, "1M": 0.0528, "3M": 0.0520,
    ...                 "6M": 0.0505, "9M": 0.0490, "1Y": 0.0475},
    ...         "EUR": {"ON": 0.0390, "1M": 0.0385, "3M": 0.0365,
    ...                 "6M": 0.0340, "9M": 0.0320, "1Y": 0.0305},
    ...     },
    ...     meeting_ois_rates={"USD": {}, "EUR": {}},
    ... )
    """

    def __init__(
        self,
        as_of: datetime,
        spot: dict[str, float],
        swap_points: dict[str, dict[str, float]],
        pip_scale: dict[str, int],
        ois_rates: dict[str, dict[str, float]],
        meeting_ois_rates: dict[str, dict[str, float]] | None = None,
    ):
        self._as_of = as_of
        self._spot = spot
        self._swap_points = swap_points
        self._pip_scale = pip_scale
        self._ois_rates = ois_rates
        self._meeting_ois_rates = meeting_ois_rates or {}

    # ------------------------------------------------------------------
    # DataProvider interface
    # ------------------------------------------------------------------

    def get_as_of(self) -> datetime:
        return self._as_of

    def get_spot(self, pair: str) -> float:
        pair = pair.upper()
        if pair not in self._spot:
            raise KeyError(f"No spot data for pair '{pair}'")
        return self._spot[pair]

    def get_swap_points(self, pair: str) -> dict[str, float]:
        pair = pair.upper()
        if pair not in self._swap_points:
            raise KeyError(f"No swap point data for pair '{pair}'")
        return dict(self._swap_points[pair])

    def get_pip_scale(self, pair: str) -> int:
        pair = pair.upper()
        if pair not in self._pip_scale:
            raise KeyError(f"No pip scale defined for pair '{pair}'")
        return self._pip_scale[pair]

    def get_ois_rates(self, currency: str) -> dict[str, float]:
        ccy = currency.upper()
        if ccy not in self._ois_rates:
            raise KeyError(f"No OIS rate data for currency '{ccy}'")
        return dict(self._ois_rates[ccy])

    def get_meeting_ois_rates(self, currency: str) -> dict[str, float]:
        ccy = currency.upper()
        return dict(self._meeting_ois_rates.get(ccy, {}))
