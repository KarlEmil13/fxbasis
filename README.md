# fxbasis

A Python library for calculating FX swap basis spreads (CIP deviations).

The basis measures the deviation from Covered Interest Rate Parity (CIP): it compares the implied base-currency OIS rate derived from the FX swap market against the actual OIS rate, yielding the spread in basis points. A persistently negative basis indicates a USD funding premium — market participants pay above CIP to borrow USD via FX swaps.

## Installation

```bash
pip install -e .

# With Bloomberg terminal support (requires blpapi)
pip install -e ".[bloomberg]"
```

**Requirements:** Python >= 3.11, numpy, scipy, pandas, python-dateutil, pyyaml

## Quick Start

```python
from datetime import datetime
from fxbasis import FXSwapBasis, OISCurve
from fxbasis.providers import StaticProvider

AS_OF = datetime(2025, 5, 9, 10, 0, 0)

provider = StaticProvider(
    as_of=AS_OF,
    spot={"EURUSD": 1.0850},
    swap_points={
        "EURUSD": {"ON": 0.4, "1W": 3.1, "1M": 14.0, "3M": 47.2, "6M": 101.0, "1Y": 210.6}
    },
    pip_scale={"EURUSD": 4},
    ois_rates={
        "USD": {"ON": 0.0530, "1M": 0.0528, "3M": 0.0520, "6M": 0.0505, "1Y": 0.0475},
        "EUR": {"ON": 0.0390, "1M": 0.0385, "3M": 0.0365, "6M": 0.0340, "1Y": 0.0305},
    },
    meeting_ois_rates={"USD": {}, "EUR": {}},
)

eurusd = FXSwapBasis("EUR", "USD", provider)

# Single-tenor basis
print(eurusd.basis_bps("3M"))    # e.g. -12.4 bps
print(eurusd.implied_rate("3M")) # implied EUR funding rate

# Full curve with PCHIP interpolation
curve = eurusd.curve()
print(curve.to_series())         # basis at all tenor knots
print(curve.at("2M"))            # interpolated at arbitrary tenor
print(curve.forward_basis("3M", "6M"))  # time-weighted forward basis

# Update to latest market data
eurusd.refresh()
```

## Calculation

For tenor $T$, the CIP basis is:

$$B(T) = \left(r^{\text{impl}}_{\text{base}}(T) - r^{\text{actual}}_{\text{base}}(T)\right) \times 10{,}000 \text{ bps}$$

where the implied base rate is derived from the forward outright:

$$F = S + \frac{\text{swap points}}{\text{pip scale}}, \qquad r^{\text{impl}}_{\text{base}} = \left[(1 + r_{\text{quote}} \cdot T) \cdot \frac{S}{F} - 1\right] / T$$

OIS rates use Bloomberg compounded convention. Discount factors are interpolated log-linearly (piecewise-constant instantaneous forwards). The basis curve uses PCHIP interpolation — monotone-preserving and C¹ continuous with flat extrapolation beyond the outer knots.

## Meeting-Dated OIS

For a more precise short-end curve, pass central bank meeting-effective dates as OIS knots. These override the corresponding standard tenor knots:

```python
provider = StaticProvider(
    ...
    meeting_ois_rates={
        "USD": {"2025-06-11": 0.0535, "2025-07-30": 0.0525},
        "EUR": {"2025-06-11": 0.0388, "2025-07-23": 0.0375},
    },
)
```

## Data Providers

The `DataProvider` protocol defines the interface for market data. Swap in any implementation:

| Provider | Use case |
|---|---|
| `StaticProvider` | Testing, manual snapshots, demo |
| `BloombergProvider` | Live Bloomberg terminal data |

### BloombergProvider

Fetches all market data in a single batch `ReferenceDataRequest` for a consistent snapshot. Requires `blpapi` and an active Bloomberg terminal connection.

```python
import yaml
from datetime import date
from fxbasis.providers import BloombergProvider
from fxbasis import FXSwapBasis

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

provider = BloombergProvider(
    config=cfg,
    pairs=["EURUSD"],
    currencies=["EUR", "USD"],
    # Optional: fetch meeting-dated OIS for a more precise short-end curve
    meeting_dates={
        "USD": [date(2025, 6, 11), date(2025, 7, 30)],
        "EUR": [date(2025, 6, 11), date(2025, 7, 23)],
    },
)

with provider:
    eurusd = FXSwapBasis("EUR", "USD", provider)
    print(eurusd.basis_bps("3M"))
    provider.refresh()  # re-fetch latest prices
```

Bloomberg tickers are configured in `config.yaml`. OIS par rates are expected in percentage terms from Bloomberg (e.g. `5.20` → stored as `0.0520`). Meeting-dated OIS tickers use the `%m/%d/%y` date format (e.g. `06/11/25`) substituted into the pattern — verify against a live terminal before use.

## Multi-Pair Registry

`BasisMarket` holds multiple `FXSwapBasis` instances and synthesises non-USD cross-pair basis on demand by triangulating through USD.

```python
from fxbasis import FXSwapBasis, BasisMarket

eurusd = FXSwapBasis("EUR", "USD", eur_provider)
gbpusd = FXSwapBasis("GBP", "USD", gbp_provider)
usdjpy = FXSwapBasis("USD", "JPY", jpy_provider)

market = BasisMarket(eurusd, gbpusd, usdjpy)

# Direct pairs
market.basis_bps("EURUSD", "3M")   # from registered FXSwapBasis
market.curve("GBPUSD")             # BasisCurve

# Cross pairs — triangulated via USD on demand
market.basis_bps("EURGBP", "3M")   # EUR/USD + GBP/USD → EUR/GBP
market.basis_bps("EURJPY", "3M")   # EUR/USD + USD/JPY → EUR/JPY
market.curve("EURGBP")             # BasisCurve at common tenors

# Summary DataFrame (pairs × tenors), cross pairs included
market.summary(pairs=["EURUSD", "GBPUSD", "EURGBP"])

market.refresh_all()               # re-fetch all registered pairs
```

Two triangulation configurations are supported:

| Registered legs | Cross derived | Approximation |
|---|---|---|
| X/USD + Y/USD | X/Y | `basis_XY ≈ basis_XUSD − basis_YUSD` |
| X/USD + USD/Y | X/Y | `basis_XY ≈ basis_XUSD + basis_USDY` |

The computed basis is exact (not the first-order approximation), using the no-arbitrage forward curve relationship between the two USD legs.

## Supported Currencies

USD (SOFR, ACT/360), EUR (€STR, ACT/360), GBP (SONIA, ACT/365), JPY (TONAR, ACT/360), NOK, SEK.

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
python -m pytest tests/ --cov=fxbasis
```

See `demo.ipynb` for a full end-to-end walkthrough including OIS curve inspection, basis curve plots, forward basis, and spot sensitivity analysis.
