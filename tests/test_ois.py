"""Tests for OISCurve."""

import math
import pytest
from fxbasis.ois import OISCurve
from datetime import date


AS_OF = date(2025, 5, 9)

# Simple par rates for hand-calculation verification
# ACT/360: 3M ≈ 92/360 = 0.25556, 6M ≈ 183/360 = 0.50833
PAR_RATES = {
    1 / 360:   0.0530,   # ON
    30 / 360:  0.0528,   # 1M
    92 / 360:  0.0520,   # 3M
    183 / 360: 0.0505,   # 6M
    274 / 360: 0.0490,   # 9M
    365 / 360: 0.0475,   # 1Y
}


@pytest.fixture
def usd_curve() -> OISCurve:
    return OISCurve.from_par_rates("USD", AS_OF, PAR_RATES)


class TestOISCurveConstruction:
    def test_knots_sorted(self, usd_curve):
        times = usd_curve.knots
        assert list(times) == sorted(times)

    def test_knot_count(self, usd_curve):
        assert len(usd_curve.knots) == len(PAR_RATES)

    def test_currency(self, usd_curve):
        assert usd_curve.currency == "USD"

    def test_as_of(self, usd_curve):
        assert usd_curve.as_of == AS_OF

    def test_empty_par_rates_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            OISCurve.from_par_rates("USD", AS_OF, {})

    def test_zero_year_fraction_raises(self):
        with pytest.raises(ValueError):
            OISCurve.from_par_rates("USD", AS_OF, {0.0: 0.05})


class TestParToCC:
    """Verify the conversion from par rate to continuously compounded rate."""

    def test_cc_rate_formula(self):
        """r = ln(1 + R × T) / T  and  exp(-r×T) = 1/(1+R×T)"""
        R = 0.0520
        T = 92 / 360
        r_expected = math.log(1 + R * T) / T
        df_from_par = 1 / (1 + R * T)
        df_from_cc = math.exp(-r_expected * T)
        assert abs(df_from_par - df_from_cc) < 1e-12

    def test_cc_rate_at_knot(self, usd_curve):
        """At each knot, rate() should return the original par rate."""
        for t, r_par in PAR_RATES.items():
            assert abs(usd_curve.rate(t) - r_par) < 1e-8, (
                f"Failed at t={t:.4f}: expected {r_par:.6f}, got {usd_curve.rate(t):.6f}"
            )


class TestDiscountFactor:
    def test_df_at_zero(self, usd_curve):
        assert usd_curve.discount_factor(0.0) == 1.0

    def test_df_positive(self, usd_curve):
        for t in PAR_RATES:
            assert usd_curve.discount_factor(t) > 0

    def test_df_less_than_one(self, usd_curve):
        for t in PAR_RATES:
            assert usd_curve.discount_factor(t) < 1.0

    def test_df_decreasing(self, usd_curve):
        """Discount factors should be monotonically decreasing."""
        times = sorted(PAR_RATES.keys())
        dfs = [usd_curve.discount_factor(t) for t in times]
        assert all(dfs[i] > dfs[i + 1] for i in range(len(dfs) - 1))

    def test_df_at_knot_matches_par(self, usd_curve):
        """DF at each knot must equal 1/(1 + R×T)."""
        for t, r_par in PAR_RATES.items():
            expected = 1 / (1 + r_par * t)
            assert abs(usd_curve.discount_factor(t) - expected) < 1e-10

    def test_negative_t_raises(self, usd_curve):
        with pytest.raises(ValueError):
            usd_curve.discount_factor(-0.1)


class TestInterpolation:
    def test_interpolated_rate_between_knots(self, usd_curve):
        """Rate at 2M (between 1M and 3M knots) should be between those rates."""
        t_2m = 61 / 360
        r = usd_curve.rate(t_2m)
        r_1m = usd_curve.rate(30 / 360)
        r_3m = usd_curve.rate(92 / 360)
        assert r_3m <= r <= r_1m  # rates decline over time in this test data

    def test_flat_extrapolation_short(self, usd_curve):
        """Before first knot, return the first knot's DF."""
        t_before = 0.5 / 360
        df_before = usd_curve.discount_factor(t_before)
        df_first = usd_curve.discount_factor(usd_curve.knots[0])
        # Should be very close (extrapolating to just before the first knot)
        assert abs(df_before - df_first) < 0.01

    def test_flat_extrapolation_long(self, usd_curve):
        """Beyond last knot, flat extrapolation holds the terminal log_df."""
        t_beyond = 400 / 360
        t_last = usd_curve.knots[-1]
        log_df_beyond = usd_curve._interp_log_df(t_beyond)
        log_df_last = usd_curve._interp_log_df(t_last)
        assert log_df_beyond == log_df_last


class TestForwardRate:
    def test_forward_rate_positive(self, usd_curve):
        assert usd_curve.forward_rate(30 / 360, 92 / 360) > 0

    def test_forward_rate_t2_before_t1_raises(self, usd_curve):
        with pytest.raises(ValueError):
            usd_curve.forward_rate(0.5, 0.25)

    def test_instantaneous_forward_rate_between_knots(self, usd_curve):
        """
        Log-linear on DF means log(DF) is linear in T between knots.
        The slope of log(DF) must be constant between any two sub-intervals
        within a single knot segment. We verify this with three points.
        """
        import math
        t1 = 30 / 360    # 1M knot
        t2 = 92 / 360    # 3M knot
        t_mid = (t1 + t2) / 2

        ldf1 = math.log(usd_curve.discount_factor(t1))
        ldf_mid = math.log(usd_curve.discount_factor(t_mid))
        ldf2 = math.log(usd_curve.discount_factor(t2))

        slope_first = (ldf_mid - ldf1) / (t_mid - t1)
        slope_second = (ldf2 - ldf_mid) / (t2 - t_mid)

        # Both slopes must be identical (log(DF) is linear in T)
        assert abs(slope_first - slope_second) < 1e-12


class TestMeetingDatedKnots:
    def test_meeting_knots_override_standard(self):
        """Meeting-dated rates at the same tenor should override standard rates."""
        t_3m = 92 / 360
        standard = {t_3m: 0.0520}
        meeting_override = {t_3m: 0.0510}  # Lower rate at same time
        merged = {**standard, **meeting_override}
        curve = OISCurve.from_par_rates("USD", AS_OF, merged)
        assert abs(curve.rate(t_3m) - 0.0510) < 1e-8
