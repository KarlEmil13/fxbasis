"""Tests for BasisMarket — registry and cross triangulation via USD."""

from datetime import datetime

import pytest
from fxbasis import BasisMarket, FXSwapBasis
from fxbasis.curve import BasisCurve
from fxbasis.providers import StaticProvider
from fxbasis.utils import tenor_to_years

# ---------------------------------------------------------------------------
# Additional test fixtures (EUR/USD comes from conftest.py)
# ---------------------------------------------------------------------------

AS_OF = datetime(2025, 5, 9, 10, 0, 0)

# GBP/USD market data.  Swap points calibrated to ~−5 bps basis at 3M.
_GBP_USD_PROVIDER = StaticProvider(
    as_of=AS_OF,
    spot={"GBPUSD": 1.2700},
    swap_points={
        "GBPUSD": {
            "ON": 0.2,
            "1W": 1.5,
            "1M": 5.2,
            "3M": 12.8,
            "6M": 26.0,
            "9M": 39.5,
            "1Y": 52.0,
        }
    },
    pip_scale={"GBPUSD": 4},
    ois_rates={
        "GBP": {
            "ON": 0.0490,
            "1M": 0.0488,
            "3M": 0.0485,
            "6M": 0.0480,
            "9M": 0.0475,
            "1Y": 0.0470,
        },
        "USD": {
            "ON": 0.0530,
            "1M": 0.0528,
            "3M": 0.0520,
            "6M": 0.0505,
            "9M": 0.0490,
            "1Y": 0.0475,
        },
    },
    meeting_ois_rates={"GBP": {}, "USD": {}},
)

# USD/JPY market data.  Swap points calibrated near CIP (≈ -5 bps basis).
# pip_scale=2 (JPY quoted to 2 decimal places).
# With USD 5.2% and JPY 0.12%, the CIP 3M forward is ≈ 152.91, so
# swap points ≈ -209 pips (pip_scale=2).  Values here are slightly
# inside CIP to produce a modest negative basis (~-5 bps).
_USD_JPY_PROVIDER = StaticProvider(
    as_of=AS_OF,
    spot={"USDJPY": 155.0},
    swap_points={
        "USDJPY": {
            "ON":  -2.0,
            "1W":  -15.0,
            "1M":  -68.0,
            "3M":  -197.0,
            "6M":  -394.0,
            "9M":  -558.0,
            "1Y":  -695.0,
        }
    },
    pip_scale={"USDJPY": 2},
    ois_rates={
        "USD": {
            "ON": 0.0530,
            "1M": 0.0528,
            "3M": 0.0520,
            "6M": 0.0505,
            "9M": 0.0490,
            "1Y": 0.0475,
        },
        "JPY": {
            "ON": 0.0010,
            "1M": 0.0010,
            "3M": 0.0012,
            "6M": 0.0013,
            "9M": 0.0015,
            "1Y": 0.0018,
        },
    },
    meeting_ois_rates={"USD": {}, "JPY": {}},
)


@pytest.fixture
def eurusd(static_provider) -> FXSwapBasis:
    return FXSwapBasis("EUR", "USD", static_provider)


@pytest.fixture
def gbpusd() -> FXSwapBasis:
    return FXSwapBasis("GBP", "USD", _GBP_USD_PROVIDER)


@pytest.fixture
def usdjpy() -> FXSwapBasis:
    return FXSwapBasis("USD", "JPY", _USD_JPY_PROVIDER)


@pytest.fixture
def market(eurusd, gbpusd) -> BasisMarket:
    """BasisMarket with EUR/USD and GBP/USD registered."""
    return BasisMarket(eurusd, gbpusd)


# ---------------------------------------------------------------------------
# Registry management
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_construction_with_args(self, eurusd, gbpusd):
        m = BasisMarket(eurusd, gbpusd)
        assert len(m) == 2

    def test_empty_construction(self):
        m = BasisMarket()
        assert len(m) == 0

    def test_add_returns_self(self, eurusd):
        m = BasisMarket()
        result = m.add(eurusd)
        assert result is m

    def test_fluent_chaining(self, eurusd, gbpusd):
        m = BasisMarket().add(eurusd).add(gbpusd)
        assert len(m) == 2

    def test_pairs_listed(self, market):
        assert set(market.pairs()) == {"EURUSD", "GBPUSD"}

    def test_contains(self, market):
        assert "EURUSD" in market
        assert "GBPUSD" in market
        assert "EURGBP" not in market

    def test_getitem(self, market, eurusd):
        assert market["EURUSD"] is eurusd

    def test_getitem_case_insensitive(self, market, eurusd):
        assert market["eurusd"] is eurusd

    def test_getitem_missing_raises(self, market):
        with pytest.raises(KeyError):
            _ = market["EURGBP"]

    def test_remove(self, market):
        market.remove("GBPUSD")
        assert "GBPUSD" not in market
        assert len(market) == 1

    def test_remove_missing_raises(self, market):
        with pytest.raises(KeyError):
            market.remove("NOKUSD")


# ---------------------------------------------------------------------------
# Direct pair queries
# ---------------------------------------------------------------------------

class TestDirectPairQueries:
    def test_basis_bps_direct(self, market, eurusd):
        assert market.basis_bps("EURUSD", "3M") == eurusd.basis_bps("3M")

    def test_curve_direct(self, market, eurusd):
        mc = market.curve("EURUSD")
        direct = eurusd.curve()
        assert mc.pair == direct.pair
        assert list(mc.tenors) == list(direct.tenors)

    def test_basis_bps_case_insensitive(self, market, eurusd):
        assert market.basis_bps("eurusd", "3M") == eurusd.basis_bps("3M")


# ---------------------------------------------------------------------------
# Cross triangulation: xusd_yusd (EUR/USD + GBP/USD → EUR/GBP)
# ---------------------------------------------------------------------------

class TestCrossXusdYusd:
    def test_eurgbp_is_float(self, market):
        result = market.basis_bps("EURGBP", "3M")
        assert isinstance(result, float)

    def test_eurgbp_matches_exact_formula(self, market, eurusd, gbpusd):
        """
        Verify the triangulation formula directly.

        For EUR/GBP via EUR/USD + GBP/USD:
            1 + r_EUR_impl_cross × T = (1 + r_EUR_impl_EURUSD × T)
                                     × (1 + r_GBP_actual × T)
                                     / (1 + r_GBP_impl_GBPUSD × T)
        """
        tenor = "3M"
        t = tenor_to_years(tenor)

        r_eur_impl = eurusd.implied_rate(tenor)
        r_eur_actual = r_eur_impl - eurusd.basis_bps(tenor) / 10_000

        r_gbp_impl = gbpusd.implied_rate(tenor)
        r_gbp_actual = r_gbp_impl - gbpusd.basis_bps(tenor) / 10_000

        numerator = (1.0 + r_eur_impl * t) * (1.0 + r_gbp_actual * t)
        r_eur_impl_cross = (numerator / (1.0 + r_gbp_impl * t) - 1.0) / t
        expected = (r_eur_impl_cross - r_eur_actual) * 10_000

        assert abs(market.basis_bps("EURGBP", "3M") - expected) < 1e-10

    def test_eurgbp_approx_difference_of_legs(self, market, eurusd, gbpusd):
        """
        First-order approximation: basis_EURGBP ≈ basis_EURUSD − basis_GBPUSD.
        Exact and approximate should agree to within 0.5 bps at 3M.
        """
        approx = eurusd.basis_bps("3M") - gbpusd.basis_bps("3M")
        exact = market.basis_bps("EURGBP", "3M")
        assert abs(exact - approx) < 0.5

    def test_eurgbp_negative(self, market):
        """With EUR/USD deeply negative and GBP/USD mildly negative, cross is negative."""
        assert market.basis_bps("EURGBP", "3M") < 0

    def test_eurgbp_curve_is_basis_curve(self, market):
        c = market.curve("EURGBP")
        assert isinstance(c, BasisCurve)
        assert c.pair == "EURGBP"

    def test_eurgbp_curve_common_tenors(self, market, eurusd, gbpusd):
        expected_tenors = set(eurusd.curve().tenors) & set(gbpusd.curve().tenors)
        cross_curve = market.curve("EURGBP")
        assert set(cross_curve.tenors) == expected_tenors

    def test_eurgbp_curve_values_match_bps(self, market):
        """curve().at(tenor) should match basis_bps(tenor) at each knot."""
        c = market.curve("EURGBP")
        for tenor in c.tenors:
            assert abs(c.at(tenor) - market.basis_bps("EURGBP", tenor)) < 1e-6

    def test_eurgbp_curve_tenors_sorted(self, market):
        c = market.curve("EURGBP")
        assert list(c.times) == sorted(c.times)


# ---------------------------------------------------------------------------
# Cross triangulation: xusd_usdy (EUR/USD + USD/JPY → EUR/JPY)
# ---------------------------------------------------------------------------

class TestCrossXusdUsdy:
    @pytest.fixture
    def market_with_jpy(self, eurusd, usdjpy) -> BasisMarket:
        return BasisMarket(eurusd, usdjpy)

    def test_eurjpy_is_float(self, market_with_jpy):
        result = market_with_jpy.basis_bps("EURJPY", "3M")
        assert isinstance(result, float)

    def test_eurjpy_matches_exact_formula(self, market_with_jpy, eurusd, usdjpy):
        """
        Verify the xusd_usdy triangulation formula:

            1 + r_EUR_impl_cross × T = (1 + r_EUR_impl_EURUSD × T)
                                     × (1 + r_USD_impl_USDJPY × T)
                                     / (1 + r_USD_actual × T)
        """
        tenor = "3M"
        t = tenor_to_years(tenor)

        r_eur_impl = eurusd.implied_rate(tenor)
        r_eur_actual = r_eur_impl - eurusd.basis_bps(tenor) / 10_000

        r_usd_impl = usdjpy.implied_rate(tenor)
        r_usd_actual = r_usd_impl - usdjpy.basis_bps(tenor) / 10_000

        numerator = (1.0 + r_eur_impl * t) * (1.0 + r_usd_impl * t)
        r_eur_impl_cross = (numerator / (1.0 + r_usd_actual * t) - 1.0) / t
        expected = (r_eur_impl_cross - r_eur_actual) * 10_000

        assert abs(market_with_jpy.basis_bps("EURJPY", "3M") - expected) < 1e-10

    def test_eurjpy_approx_sum_of_legs(self, market_with_jpy, eurusd, usdjpy):
        """
        First-order approximation: basis_EURJPY ≈ basis_EURUSD + basis_USDJPY.
        """
        approx = eurusd.basis_bps("3M") + usdjpy.basis_bps("3M")
        exact = market_with_jpy.basis_bps("EURJPY", "3M")
        assert abs(exact - approx) < 0.5

    def test_eurjpy_curve_pair(self, market_with_jpy):
        c = market_with_jpy.curve("EURJPY")
        assert c.pair == "EURJPY"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestErrors:
    def test_untriangulatable_pair_raises(self, market):
        """NOKUSD is not registered, so EURNOK can't be triangulated."""
        with pytest.raises(KeyError, match="Cannot triangulate"):
            market.basis_bps("EURNOK", "3M")

    def test_unknown_short_pair_raises(self, market):
        with pytest.raises(ValueError, match="6-character"):
            market.basis_bps("EUR", "3M")

    def test_cross_curve_untriangulatable_raises(self, market):
        with pytest.raises(KeyError):
            market.curve("EURNOK")


# ---------------------------------------------------------------------------
# refresh_all
# ---------------------------------------------------------------------------

class TestRefreshAll:
    def test_refresh_all_runs(self, market):
        """refresh_all() should complete without error."""
        market.refresh_all()

    def test_refresh_all_updates_data(self, market):
        """After mutating the provider, refresh_all() picks up the change."""
        original = market["EURUSD"].spot
        market["EURUSD"]._provider._spot["EURUSD"] = 1.1000
        market.refresh_all()
        assert market["EURUSD"].spot == 1.1000
        # Restore
        market["EURUSD"]._provider._spot["EURUSD"] = original
        market.refresh_all()


# ---------------------------------------------------------------------------
# summary()
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_shape(self, market, eurusd):
        df = market.summary()
        expected_tenors = list(eurusd.curve().tenors)
        assert list(df.index) == expected_tenors
        assert set(df.columns) == {"EURUSD", "GBPUSD"}

    def test_summary_values_match_basis_bps(self, market):
        df = market.summary()
        for tenor in df.index:
            for pair in df.columns:
                assert abs(df.loc[tenor, pair] - market.basis_bps(pair, tenor)) < 1e-10

    def test_summary_custom_tenors(self, market):
        df = market.summary(tenors=["1M", "3M", "1Y"])
        assert list(df.index) == ["1M", "3M", "1Y"]

    def test_summary_with_cross_pair(self, market):
        """Cross pairs can be included in the summary."""
        df = market.summary(pairs=["EURUSD", "GBPUSD", "EURGBP"])
        assert "EURGBP" in df.columns
        assert not df["EURGBP"].isna().any()

    def test_summary_empty_registry(self):
        df = BasisMarket().summary()
        assert df.empty
