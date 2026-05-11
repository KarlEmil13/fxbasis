"""BloombergProvider — live market data via blpapi."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

# blpapi is an optional dependency — guard the import so the rest of the
# library works without it when Bloomberg is not installed.
try:
    import blpapi  # type: ignore[import]
    _BBG_AVAILABLE = True
except ImportError:
    _BBG_AVAILABLE = False


_REF_DATA_SVC = "//blp/refdata"
_FIELD = "PX_LAST"
_TIMEOUT_MS = 5_000  # per nextEvent() call, milliseconds


class BloombergProvider:
    """
    DataProvider backed by a live Bloomberg terminal via blpapi.

    All market data is fetched in a single batch ReferenceDataRequest on
    connect(), giving a consistent point-in-time snapshot. Call refresh()
    to update to the latest prices without reconnecting.

    Tickers and field mappings are read from config.yaml. OIS par rates
    are assumed to be returned by Bloomberg in percentage terms (e.g. 5.20)
    and are converted to decimal on ingestion. Spot rates and swap points
    are returned as-is (no conversion).

    Parameters
    ----------
    config : dict
        Parsed contents of config.yaml (e.g. from fxbasis.config.load_config()).
    pairs : list[str]
        Currency pairs to fetch, e.g. ["EURUSD"]. Each must have an entry
        under config["pairs"].
    currencies : list[str]
        ISO currency codes for OIS curves, e.g. ["EUR", "USD"]. Each must
        have an entry under config["currencies"].
    meeting_dates : dict[str, list[date]] | None
        Optional mapping of currency → upcoming CB meeting effective dates.
        When provided, the date is formatted and substituted into the
        meeting_dated ticker pattern from config. Example::

            {"USD": [date(2025, 6, 11), date(2025, 7, 30)],
             "EUR": [date(2025, 6, 11), date(2025, 7, 23)]}

        The date format used is ``%m/%d/%y`` (e.g. ``06/11/25``). Verify
        the format against a live terminal — Bloomberg ticker formats vary.
    host : str
        Bloomberg server host. Default ``"localhost"``.
    port : int
        Bloomberg server port. Default ``8194``.

    Examples
    --------
    >>> import yaml
    >>> from datetime import date
    >>> with open("config.yaml") as f:
    ...     cfg = yaml.safe_load(f)
    >>> provider = BloombergProvider(
    ...     config=cfg,
    ...     pairs=["EURUSD"],
    ...     currencies=["EUR", "USD"],
    ...     meeting_dates={"USD": [date(2025, 6, 11)], "EUR": [date(2025, 6, 11)]},
    ... )
    >>> provider.connect()
    >>> from fxbasis import FXSwapBasis
    >>> eurusd = FXSwapBasis("EUR", "USD", provider)
    >>> print(eurusd.basis_bps("3M"))
    >>> provider.disconnect()
    """

    def __init__(
        self,
        config: dict,
        pairs: list[str],
        currencies: list[str],
        meeting_dates: dict[str, list[date]] | None = None,
        host: str = "localhost",
        port: int = 8194,
    ) -> None:
        if not _BBG_AVAILABLE:
            raise ImportError(
                "blpapi is not installed. Install it with: pip install blpapi"
            )
        self._config = config
        self._pairs = [p.upper() for p in pairs]
        self._currencies = [c.upper() for c in currencies]
        self._meeting_dates: dict[str, list[date]] = {
            k.upper(): v for k, v in (meeting_dates or {}).items()
        }
        self._host = host
        self._port = port

        self._session: "blpapi.Session | None" = None
        self._as_of: datetime | None = None

        # Cached snapshot data (populated on connect/refresh)
        self._spot: dict[str, float] = {}
        self._swap_points: dict[str, dict[str, float]] = {}
        self._ois_rates: dict[str, dict[str, float]] = {}
        self._meeting_ois_rates: dict[str, dict[str, float]] = {}

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open a Bloomberg session and fetch an initial data snapshot."""
        options = blpapi.SessionOptions()
        options.setServerHost(self._host)
        options.setServerPort(self._port)

        session = blpapi.Session(options)
        if not session.start():
            raise RuntimeError(
                f"Failed to start Bloomberg session on {self._host}:{self._port}."
            )
        if not session.openService(_REF_DATA_SVC):
            session.stop()
            raise RuntimeError(
                f"Failed to open Bloomberg service {_REF_DATA_SVC!r}."
            )

        self._session = session
        self._as_of = datetime.now()
        self._fetch_all()

    def disconnect(self) -> None:
        """Close the Bloomberg session."""
        if self._session is not None:
            self._session.stop()
            self._session = None

    def refresh(self) -> None:
        """Re-fetch all market data and update the snapshot timestamp."""
        self._require_connected()
        self._as_of = datetime.now()
        self._fetch_all()

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "BloombergProvider":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # DataProvider interface
    # ------------------------------------------------------------------

    def get_as_of(self) -> datetime:
        self._require_connected()
        return self._as_of  # type: ignore[return-value]

    def get_spot(self, pair: str) -> float:
        self._require_connected()
        pair = pair.upper()
        if pair not in self._spot:
            raise KeyError(f"No spot data for pair '{pair}'")
        return self._spot[pair]

    def get_swap_points(self, pair: str) -> dict[str, float]:
        self._require_connected()
        pair = pair.upper()
        if pair not in self._swap_points:
            raise KeyError(f"No swap point data for pair '{pair}'")
        return dict(self._swap_points[pair])

    def get_pip_scale(self, pair: str) -> int:
        pair = pair.upper()
        return self._config["pairs"][pair]["pip_scale"]

    def get_ois_rates(self, currency: str) -> dict[str, float]:
        self._require_connected()
        ccy = currency.upper()
        if ccy not in self._ois_rates:
            raise KeyError(f"No OIS rate data for currency '{ccy}'")
        return dict(self._ois_rates[ccy])

    def get_meeting_ois_rates(self, currency: str) -> dict[str, float]:
        self._require_connected()
        ccy = currency.upper()
        return dict(self._meeting_ois_rates.get(ccy, {}))

    # ------------------------------------------------------------------
    # Internal data fetching
    # ------------------------------------------------------------------

    def _build_ticker_map(self) -> dict[str, tuple]:
        """
        Build a mapping of Bloomberg ticker → (data_type, *keys) for all
        requested data. Used to route parsed response values back to the
        correct cache entry.
        """
        ticker_map: dict[str, tuple] = {}

        for pair in self._pairs:
            pair_cfg = self._config["pairs"][pair]

            # Spot
            ticker_map[pair_cfg["spot_ticker"]] = ("spot", pair)

            # Swap points
            for tenor, ticker in pair_cfg["swap_point_tickers"].items():
                ticker_map[ticker] = ("swap", pair, tenor)

        for ccy in self._currencies:
            ccy_cfg = self._config["currencies"][ccy]["ois_tickers"]

            # Standard tenor OIS
            for tenor, ticker in ccy_cfg["fallback"].items():
                # A ticker may serve multiple tenors if the config reuses it;
                # last write wins, which is fine — values will be identical.
                ticker_map[ticker] = ("ois", ccy, tenor)

            # Meeting-dated OIS
            pattern = ccy_cfg["meeting_dated"]["pattern"]
            for meeting_date in self._meeting_dates.get(ccy, []):
                date_str = meeting_date.strftime("%m/%d/%y")
                ticker = pattern.replace("{DATE}", date_str)
                iso_str = meeting_date.isoformat()
                ticker_map[ticker] = ("meeting_ois", ccy, iso_str)

        return ticker_map

    def _fetch_all(self) -> None:
        """Batch-fetch all tickers and populate the snapshot caches."""
        ticker_map = self._build_ticker_map()
        raw = self._bdp(list(ticker_map), _FIELD)

        # Reset caches
        self._spot = {}
        self._swap_points = {p: {} for p in self._pairs}
        self._ois_rates = {c: {} for c in self._currencies}
        self._meeting_ois_rates = {c: {} for c in self._currencies}

        for ticker, value in raw.items():
            if value is None:
                continue
            meta = ticker_map.get(ticker)
            if meta is None:
                continue

            dtype = meta[0]
            if dtype == "spot":
                _, pair = meta
                self._spot[pair] = float(value)

            elif dtype == "swap":
                _, pair, tenor = meta
                self._swap_points[pair][tenor] = float(value)

            elif dtype == "ois":
                _, ccy, tenor = meta
                # Bloomberg returns OIS par rates in percent — convert to decimal
                self._ois_rates[ccy][tenor] = float(value) / 100.0

            elif dtype == "meeting_ois":
                _, ccy, iso_str = meta
                self._meeting_ois_rates[ccy][iso_str] = float(value) / 100.0

    def _bdp(self, tickers: list[str], field: str) -> dict[str, Any]:
        """
        Send a single ReferenceDataRequest for multiple tickers and one field.

        Returns a dict mapping ticker → field value (or ``None`` on error/
        missing data).
        """
        svc = self._session.getService(_REF_DATA_SVC)  # type: ignore[union-attr]
        request = svc.createRequest("ReferenceDataRequest")

        for ticker in tickers:
            request.getElement("securities").appendValue(ticker)
        request.getElement("fields").appendValue(field)

        self._session.sendRequest(request)  # type: ignore[union-attr]

        result: dict[str, Any] = {t: None for t in tickers}

        while True:
            event = self._session.nextEvent(_TIMEOUT_MS)  # type: ignore[union-attr]

            if event.eventType() in (
                blpapi.Event.RESPONSE,
                blpapi.Event.PARTIAL_RESPONSE,
            ):
                for msg in event:
                    security_data_array = msg.getElement("securityData")
                    for i in range(security_data_array.numValues()):
                        sec_data = security_data_array.getValue(i)
                        ticker = sec_data.getElementAsString("security")
                        if sec_data.hasElement("securityError"):
                            continue  # leave result[ticker] as None
                        field_data = sec_data.getElement("fieldData")
                        if field_data.hasElement(field):
                            result[ticker] = field_data.getElement(field).getValue()

            if event.eventType() == blpapi.Event.RESPONSE:
                break

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_connected(self) -> None:
        if self._session is None:
            raise RuntimeError(
                "BloombergProvider is not connected. Call connect() first."
            )

    def __repr__(self) -> str:  # pragma: no cover
        status = "connected" if self._session is not None else "disconnected"
        return (
            f"BloombergProvider("
            f"pairs={self._pairs!r}, "
            f"currencies={self._currencies!r}, "
            f"status={status!r})"
        )
