"""BasisMarket — registry and cross triangulation. Deferred to v2."""

from __future__ import annotations


class BasisMarket:
    """
    Registry of FXSwapBasis instances with cross-pair triangulation.

    Status: deferred to v2. Only EUR/USD is in scope for v1.

    When implemented, this class will:
    - Hold multiple FXSwapBasis instances (all USD-leg pairs)
    - Derive non-USD crosses by triangulating via USD
      e.g. NOK/JPY = NOK/USD + USD/JPY (sign-adjusted, tenor-aligned)
    - Expose a unified refresh_all() method
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "BasisMarket is not yet implemented — deferred to v2."
        )
