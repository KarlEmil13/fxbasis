"""BloombergProvider — live market data via blpapi. Skeleton for v1."""

from datetime import datetime

# blpapi is an optional dependency — guard the import so the rest of the
# library works without it when Bloomberg is not installed.
try:
    import blpapi  # type: ignore[import]
    _BBG_AVAILABLE = True
except ImportError:
    _BBG_AVAILABLE = False


class BloombergProvider:
    """
    DataProvider backed by a live Bloomberg terminal via blpapi.

    Status: skeleton — ticker patterns and field names must be verified
    against a live terminal before this class is functional.

    Tickers and field mappings are read from config.yaml so no Bloomberg
    specifics are hardcoded in library source.
    """

    def __init__(self, config: dict):
        """
        Parameters
        ----------
        config : dict
            Parsed contents of config.yaml (from fxbasis.config.load_config()).
        """
        if not _BBG_AVAILABLE:
            raise ImportError(
                "blpapi is not installed. Install it with: pip install blpapi"
            )
        self._config = config
        self._session: "blpapi.Session | None" = None
        self._as_of: datetime | None = None

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open a Bloomberg session and fetch a fresh snapshot atomically."""
        raise NotImplementedError(
            "BloombergProvider.connect() is not yet implemented. "
            "Verify Bloomberg tickers in config.yaml against a live terminal first."
        )

    def disconnect(self) -> None:
        """Close the Bloomberg session."""
        if self._session is not None:
            self._session.stop()
            self._session = None

    # ------------------------------------------------------------------
    # DataProvider interface (all raise until implemented)
    # ------------------------------------------------------------------

    def get_as_of(self) -> datetime:
        self._require_connected()
        return self._as_of  # type: ignore[return-value]

    def get_spot(self, pair: str) -> float:
        self._require_connected()
        raise NotImplementedError

    def get_swap_points(self, pair: str) -> dict[str, float]:
        self._require_connected()
        raise NotImplementedError

    def get_pip_scale(self, pair: str) -> int:
        pair = pair.upper()
        return self._config["pairs"][pair]["pip_scale"]

    def get_ois_rates(self, currency: str) -> dict[str, float]:
        self._require_connected()
        raise NotImplementedError

    def get_meeting_ois_rates(self, currency: str) -> dict[str, float]:
        self._require_connected()
        raise NotImplementedError

    def _require_connected(self) -> None:
        if self._session is None:
            raise RuntimeError(
                "BloombergProvider is not connected. Call connect() first."
            )
