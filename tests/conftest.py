"""Shared test fixtures using StaticProvider with realistic EUR/USD data.

Market data approximates mid-2024 EUR/USD conditions:
  - EUR/USD spot ~1.0850
  - SOFR ~5.20-5.30% (USD)
  - ESTR ~3.65-3.90% (EUR)
  - EUR/USD basis approximately -10 to -20 bps across the curve
"""

from datetime import datetime
import pytest
from fxbasis.providers import StaticProvider


AS_OF = datetime(2025, 5, 9, 10, 0, 0)

# Spot: 1 EUR = 1.0850 USD
SPOT = {"EURUSD": 1.0850}

# Swap points in raw pips (4 decimal places for EURUSD).
# When USD rates > EUR rates, forward EUR trades at a premium (F > S),
# so swap points are POSITIVE. Negative basis arises when actual swap points
# exceed the CIP-implied forward (F > F_CIP → r_EUR_implied < r_EUR_actual).
# Values here are set slightly above CIP, giving a basis of approx -5 to -27 bps.
SWAP_POINTS = {
    "EURUSD": {
        "ON":  0.4,
        "1W":  3.1,
        "1M":  14.0,
        "3M":  47.2,
        "6M":  101.0,
        "9M":  156.6,
        "1Y":  210.6,
    }
}

PIP_SCALE = {"EURUSD": 4}

# OIS par rates (compounded Bloomberg convention, decimal)
OIS_RATES = {
    "USD": {
        "ON": 0.0530,
        "1M": 0.0528,
        "3M": 0.0520,
        "6M": 0.0505,
        "9M": 0.0490,
        "1Y": 0.0475,
    },
    "EUR": {
        "ON": 0.0390,
        "1M": 0.0385,
        "3M": 0.0365,
        "6M": 0.0340,
        "9M": 0.0320,
        "1Y": 0.0305,
    },
}


@pytest.fixture
def static_provider() -> StaticProvider:
    """StaticProvider with standard EUR/USD test data."""
    return StaticProvider(
        as_of=AS_OF,
        spot=SPOT,
        swap_points=SWAP_POINTS,
        pip_scale=PIP_SCALE,
        ois_rates=OIS_RATES,
        meeting_ois_rates={"USD": {}, "EUR": {}},
    )


@pytest.fixture
def static_provider_with_meetings() -> StaticProvider:
    """StaticProvider with meeting-dated OIS rates for the short end."""
    return StaticProvider(
        as_of=AS_OF,
        spot=SPOT,
        swap_points=SWAP_POINTS,
        pip_scale=PIP_SCALE,
        ois_rates=OIS_RATES,
        meeting_ois_rates={
            "USD": {
                "2025-06-11": 0.0535,  # Fed meeting effective date
                "2025-07-30": 0.0525,  # Fed meeting effective date
            },
            "EUR": {
                "2025-06-11": 0.0388,  # ECB meeting effective date
                "2025-07-23": 0.0375,  # ECB meeting effective date
            },
        },
    )
