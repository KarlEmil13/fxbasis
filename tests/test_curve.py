"""Tests for BasisCurve."""

import numpy as np
import pytest
from fxbasis.curve import BasisCurve


TENORS = ["ON", "1W", "1M", "3M", "6M", "9M", "1Y"]
TIMES = np.array([1/360, 7/360, 30/360, 92/360, 183/360, 274/360, 365/360])
BASIS = np.array([-3.1, -6.2, -9.5, -14.7, -18.3, -20.1, -22.0])


@pytest.fixture
def curve() -> BasisCurve:
    return BasisCurve(pair="EURUSD", tenors=TENORS, times=TIMES, basis_bps=BASIS)


class TestBasisCurveConstruction:
    def test_pair(self, curve):
        assert curve.pair == "EURUSD"

    def test_tenors(self, curve):
        assert curve.tenors == TENORS

    def test_too_few_knots_raises(self):
        with pytest.raises(ValueError, match="At least 2"):
            BasisCurve("EURUSD", ["3M"], np.array([0.25]), np.array([-10.0]))


class TestAtMethod:
    def test_at_knot_matches_input(self, curve):
        """At each knot, interpolated value should match input exactly."""
        for tenor, expected in zip(TENORS, BASIS):
            assert abs(curve.at(tenor) - expected) < 1e-6

    def test_at_float_input(self, curve):
        val = curve.at(92 / 360)
        assert abs(val - (-14.7)) < 1e-6

    def test_at_between_knots(self, curve):
        """Value between 1M and 3M should be between those basis values."""
        t_2m = 61 / 360
        val = curve.at(t_2m)
        assert -14.7 <= val <= -9.5  # monotone-preserving: between the two knots

    def test_flat_extrapolation_below(self, curve):
        val = curve.at(0.0001)
        assert abs(val - BASIS[0]) < 0.5  # close to ON basis

    def test_flat_extrapolation_above(self, curve):
        val = curve.at(2.0)  # beyond 1Y
        assert abs(val - BASIS[-1]) < 0.5  # close to 1Y basis

    def test_unknown_tenor_raises(self, curve):
        with pytest.raises(ValueError):
            curve.at("5Y")


class TestForwardBasis:
    def test_positive_t2_required(self, curve):
        with pytest.raises(ValueError):
            curve.forward_basis("6M", "3M")

    def test_forward_basis_between_knots(self, curve):
        """Forward basis from 3M to 6M should be between the two spot basis values."""
        fb = curve.forward_basis("3M", "6M")
        # Forward basis should be more negative than 3M (since curve goes more negative)
        assert fb < curve.at("3M")

    def test_forward_basis_float_input(self, curve):
        fb1 = curve.forward_basis("3M", "6M")
        fb2 = curve.forward_basis(92 / 360, 183 / 360)
        assert abs(fb1 - fb2) < 1e-6


class TestToSeries:
    def test_series_index(self, curve):
        s = curve.to_series()
        assert list(s.index) == TENORS

    def test_series_values(self, curve):
        s = curve.to_series()
        np.testing.assert_array_equal(s.values, BASIS)

    def test_series_name(self, curve):
        assert curve.to_series().name == "EURUSD_basis_bps"
