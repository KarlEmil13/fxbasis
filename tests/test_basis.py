"""Tests for FXSwapBasis — hand-calculated verification of CIP basis."""

import math
import pytest
from fxbasis.basis import FXSwapBasis
from fxbasis.curve import BasisCurve


class TestFXSwapBasisConstruction:
    def test_pair_attributes(self, static_provider):
        b = FXSwapBasis("EUR", "USD", static_provider)
        assert b.base == "EUR"
        assert b.quote == "USD"
        assert b.pair == "EURUSD"

    def test_as_of(self, static_provider):
        b = FXSwapBasis("EUR", "USD", static_provider)
        assert b.as_of.year == 2025 and b.as_of.month == 5 and b.as_of.day == 9

    def test_spot(self, static_provider):
        b = FXSwapBasis("EUR", "USD", static_provider)
        assert abs(b.spot - 1.0850) < 1e-10


class TestImpliedRate:
    def test_implied_rate_3m_hand_calc(self, static_provider):
        """
        Hand-calculated implied EUR rate for 3M:

        S = 1.0850
        pips = +47.2  →  F = 1.0850 + 0.00472 = 1.08972
        T = 92/360 = 0.25556
        r_USD_3M = 0.0520

        r_EUR_implied = [(1 + 0.0520 × 0.25556) × (1.0850/1.08972) − 1] / 0.25556
        """
        S = 1.0850
        F = 1.0850 + 47.2 / 10_000
        T = 92 / 360
        r_usd = 0.0520
        expected = ((1 + r_usd * T) * (S / F) - 1) / T

        b = FXSwapBasis("EUR", "USD", static_provider)
        assert abs(b.implied_rate("3M") - expected) < 1e-10

    def test_implied_rate_1m_hand_calc(self, static_provider):
        S = 1.0850
        F = 1.0850 + 14.0 / 10_000
        T = 30 / 360
        r_usd = 0.0528
        expected = ((1 + r_usd * T) * (S / F) - 1) / T

        b = FXSwapBasis("EUR", "USD", static_provider)
        assert abs(b.implied_rate("1M") - expected) < 1e-10


class TestBasisBps:
    def test_basis_3m_hand_calc(self, static_provider):
        """
        basis_bps = (r_EUR_implied - r_EUR_actual) × 10,000
        S=1.0850, F=1.0850+0.00472=1.08972, T=92/360, r_USD=0.0520, r_EUR=0.0365
        """
        S = 1.0850
        F = 1.0850 + 47.2 / 10_000
        T = 92 / 360
        r_usd = 0.0520
        r_eur = 0.0365
        r_implied = ((1 + r_usd * T) * (S / F) - 1) / T
        expected_bps = (r_implied - r_eur) * 10_000

        b = FXSwapBasis("EUR", "USD", static_provider)
        assert abs(b.basis_bps("3M") - expected_bps) < 1e-6

    def test_basis_sign(self, static_provider):
        """EUR/USD basis should be negative (EUR cheap via FX swap)."""
        b = FXSwapBasis("EUR", "USD", static_provider)
        for tenor in ["1M", "3M", "6M", "1Y"]:
            assert b.basis_bps(tenor) < 0, f"Expected negative basis at {tenor}"

    def test_basis_monotone_negative(self, static_provider):
        """Basis should become more negative at longer tenors (typical EUR/USD shape)."""
        b = FXSwapBasis("EUR", "USD", static_provider)
        tenors = ["1M", "3M", "6M", "1Y"]
        values = [b.basis_bps(t) for t in tenors]
        assert all(values[i] > values[i + 1] for i in range(len(values) - 1))


class TestCurve:
    def test_curve_returns_basis_curve(self, static_provider):
        b = FXSwapBasis("EUR", "USD", static_provider)
        c = b.curve()
        assert isinstance(c, BasisCurve)

    def test_curve_pair(self, static_provider):
        b = FXSwapBasis("EUR", "USD", static_provider)
        assert b.curve().pair == "EURUSD"

    def test_curve_tenors_sorted(self, static_provider):
        b = FXSwapBasis("EUR", "USD", static_provider)
        c = b.curve()
        assert list(c.times) == sorted(c.times)

    def test_curve_values_match_basis_bps(self, static_provider):
        """curve().at(tenor) should match basis_bps(tenor) at each knot."""
        b = FXSwapBasis("EUR", "USD", static_provider)
        c = b.curve()
        for tenor in ["1M", "3M", "6M", "1Y"]:
            assert abs(c.at(tenor) - b.basis_bps(tenor)) < 1e-6


class TestRefresh:
    def test_refresh_runs_without_error(self, static_provider):
        b = FXSwapBasis("EUR", "USD", static_provider)
        b.refresh()
        assert b.spot == 1.0850

    def test_refresh_updates_snapshot(self, static_provider):
        """After modifying provider data, refresh should pick up the change."""
        b = FXSwapBasis("EUR", "USD", static_provider)
        original_spot = b.spot

        # Mutate the provider's spot data
        static_provider._spot["EURUSD"] = 1.1000
        b.refresh()
        assert b.spot == 1.1000

        # Restore
        static_provider._spot["EURUSD"] = original_spot


class TestMeetingDatedOIS:
    def test_meeting_knots_used(self, static_provider_with_meetings):
        """OIS curve with meeting knots should still produce valid basis."""
        b = FXSwapBasis("EUR", "USD", static_provider_with_meetings)
        val = b.basis_bps("3M")
        assert isinstance(val, float)
        assert not math.isnan(val)
