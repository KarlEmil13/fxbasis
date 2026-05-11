# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**fxbasis** is a Python library for calculating FX swap basis spreads (CIP deviations). It computes the basis by comparing the implied base-currency OIS rate derived from FX swap market data with the actual OIS rate, yielding the CIP deviation in basis points.

## Commands

```bash
# Install in development mode
pip install -e .

# Install with Bloomberg support
pip install -e ".[bloomberg]"

# Install with dev tools
pip install -e ".[dev]"

# Run all tests
python -m pytest tests/ -v

# Run a single test module
python -m pytest tests/test_basis.py -v
python -m pytest tests/test_curve.py -v
python -m pytest tests/test_ois.py -v

# Run with coverage
python -m pytest tests/ --cov=fxbasis
```

## Architecture

The library uses dependency injection via the `DataProvider` protocol. `FXSwapBasis` accepts any provider implementation, making data sources interchangeable and testable.

### Core Calculation Flow

```
FXSwapBasis(base, quote, provider)
    ↓ _fetch_snapshot()
    ├── provider.get_spot() / get_swap_points() / get_pip_scale()
    └── _build_ois_curve() x2 (base + quote)
            └── OISCurve.from_par_rates()  ← log-linear on discount factors

    ↓ basis_bps(tenor)
    ├── implied_rate() — CIP no-arbitrage formula using forward outrights
    └── base_ois.rate() — actual OIS rate at that tenor
    → spread = (implied − actual) × 10,000 bps
```

### Key Modules

- **`fxbasis/basis.py`** — `FXSwapBasis`: main calculator. Holds an atomic market snapshot; call `.refresh()` to update. Entry points: `implied_rate()`, `basis_bps()`, `curve()`.
- **`fxbasis/ois.py`** — `OISCurve`: converts Bloomberg-convention par OIS rates to continuously compounded zeros and discount factors. Interpolates using log-linear on DFs (piecewise-constant instantaneous forwards). Supports meeting-dated knots that override standard tenors.
- **`fxbasis/curve.py`** — `BasisCurve`: basis spread curve across tenors using PCHIP interpolation (monotone-preserving, C¹ continuous, flat extrapolation). Methods: `at()`, `forward_basis()`, `to_series()`.
- **`fxbasis/utils.py`** — `tenor_to_years()`, `scale_swap_points()`, `forward_outright()`, `TENOR_DAYS` mapping.
- **`fxbasis/conventions/`** — `DayCount` enum (ACT/360, ACT/365, ACT/ACT ISDA) and `CURRENCY_CONVENTIONS` dict mapping ISO codes to day count + calendar.
- **`fxbasis/providers/base.py`** — `DataProvider` Protocol defining the interface all providers must implement.
- **`fxbasis/providers/static.py`** — `StaticProvider`: accepts all market data at construction; used in tests and for manual snapshots.
- **`fxbasis/providers/bloomberg.py`** — `BloombergProvider`: batch-fetches all market data in a single `ReferenceDataRequest` on `connect()`/`refresh()`. Supports context manager usage. OIS rates are converted from Bloomberg percentage to decimal on ingestion. Meeting-dated tickers use `%m/%d/%y` date substitution into the pattern from `config.yaml` — verify format on a live terminal.
- **`fxbasis/market.py`** — `BasisMarket`: registry of `FXSwapBasis` instances. Direct pairs looked up from the registry; non-USD crosses triangulated via USD on demand using an exact no-arbitrage formula (not first-order approximation). Two configurations: `X/USD + Y/USD → X/Y` and `X/USD + USD/Y → X/Y`. Methods: `add()`, `remove()`, `basis_bps()`, `curve()`, `refresh_all()`, `summary()`. Module-level helpers `_split_pair()` and `_cross_basis_bps()` keep the triangulation logic out of the class.

### Test Fixtures

`tests/conftest.py` provides EUR/USD fixtures (~May 2025): spot 1.0850, SOFR 5.20–5.30%, ESTR 3.65–3.90%, basis approximately −10 to −20 bps. Two providers: standard tenors only, and one augmented with meeting-dated OIS rates.

`tests/test_market.py` defines its own GBP/USD and USD/JPY `StaticProvider` instances inline. The USD/JPY swap points must be calibrated near CIP (≈ −200 pips at 3M for a 5% USD / 0.1% JPY rate differential) — using small values like −47 pips produces a −390 bps basis where first-order approximation tests will fail.

## Configuration

`config.yaml` defines Bloomberg ticker patterns for spot rates, FX swap points, pip scales, and OIS rates per currency/pair. Used by `BloombergProvider`; not relevant when using `StaticProvider`.
