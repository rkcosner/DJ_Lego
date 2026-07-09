"""Bilinear (Tustin) transform: continuous ``H(s)`` -> discrete ``H(z)``.

We roll this by hand instead of calling ``scipy.signal.bilinear`` for two
reasons that matter for this toy:

1. **Improper transfer functions must work.**  A bare differentiator ``s`` or
   PID's ``Kd*s^2`` term has a numerator of higher degree than the
   denominator.  These are perfectly realizable digital filters (a pure
   differentiator becomes ``2*fs*(1 - z^-1)/(1 + z^-1)``), and the direct
   substitution handles them without special-casing.
2. **It's a teaching artifact.**  The algorithm is exactly the substitution
   ``s = 2*fs*(z-1)/(z+1)`` cleared of denominators -- a student can read it.

The substitution maps every ``s^k`` to
``(2*fs)^k * (z-1)^k * (z+1)^(M-k)`` after multiplying numerator and
denominator through by ``(z+1)^M``, where ``M`` is the highest degree present.
Both results come out as degree-``M`` polynomials in ``z`` (highest power
first), which -- once normalised by the leading denominator coefficient -- is
precisely the ``(b, a)`` order ``scipy.signal.lfilter`` expects.
"""

from __future__ import annotations

import numpy as np

from .polynomial import as_poly, poly_add


def _poly_pow(base: np.ndarray, k: int) -> np.ndarray:
    """Raise a polynomial to a non-negative integer power by convolution."""
    out = np.array([1.0])
    for _ in range(k):
        out = np.convolve(out, base)
    return out


def _substitute(coeffs: np.ndarray, c: float, M: int) -> np.ndarray:
    """Apply the bilinear substitution to one polynomial in ``s``.

    ``coeffs`` is highest-power-first in ``s`` (degree d = len-1).  Returns the
    degree-``M`` polynomial in ``z`` (highest power first) obtained by
    substituting ``s = c*(z-1)/(z+1)`` and multiplying through by ``(z+1)^M``.
    """
    coeffs = as_poly(coeffs)
    d = coeffs.size - 1
    zm1 = np.array([1.0, -1.0])  # (z - 1)
    zp1 = np.array([1.0, 1.0])  # (z + 1)
    result = np.zeros(M + 1)
    for i, coef in enumerate(coeffs):
        if coef == 0.0:
            continue
        k = d - i  # power of s for this term
        term = coef * (c**k) * np.convolve(_poly_pow(zm1, k), _poly_pow(zp1, M - k))
        result = poly_add(result, term)
    return result


def to_discrete(num, den, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """Bilinear-transform ``num/den`` (in ``s``) to ``(b, a)`` (in ``z``) at ``fs``.

    ``b`` and ``a`` are highest-power-first / ``lfilter``-ready, with ``a``
    normalised so ``a[0] == 1``.
    """
    num = as_poly(num)
    den = as_poly(den)
    c = 2.0 * fs
    M = max(num.size, den.size) - 1
    b = _substitute(num, c, M)
    a = _substitute(den, c, M)
    a0 = a[0]
    if a0 == 0.0:  # should not happen for a proper leaky denominator
        a0 = 1e-12
    return b / a0, a / a0
