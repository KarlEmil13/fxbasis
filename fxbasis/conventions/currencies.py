"""Per-currency day count and calendar defaults."""

from .day_count import DayCount

# Default conventions per currency (ISO 4217 codes)
CURRENCY_CONVENTIONS: dict[str, dict] = {
    "USD": {"day_count": DayCount.ACT_360, "calendar": "USNY"},
    "EUR": {"day_count": DayCount.ACT_360, "calendar": "TGTG"},
    "GBP": {"day_count": DayCount.ACT_365, "calendar": "GBLO"},
    "JPY": {"day_count": DayCount.ACT_360, "calendar": "JPTO"},
    "NOK": {"day_count": DayCount.ACT_360, "calendar": "OSLB"},
    "SEK": {"day_count": DayCount.ACT_360, "calendar": "STOC"},
}


def get_day_count(currency: str) -> DayCount:
    """Return the standard day count convention for a currency."""
    ccy = currency.upper()
    if ccy not in CURRENCY_CONVENTIONS:
        raise ValueError(f"No convention registered for currency '{ccy}'")
    return CURRENCY_CONVENTIONS[ccy]["day_count"]
