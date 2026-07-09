"""Small polynomial helpers for combining transfer functions.

Coefficients are ordered highest-power-first (numpy convention).  These are
thin wrappers around numpy, kept as named functions so the chain-combination
code reads like the algebra the students already know.
"""

from __future__ import annotations

import numpy as np

# A coefficient array is just a 1-D real numpy array, highest power first.
Poly = np.ndarray


def as_poly(coeffs) -> Poly:
    """Coerce a list/array of coefficients to a 1-D float array."""
    p = np.atleast_1d(np.asarray(coeffs, dtype=float))
    return p


def poly_mul(a, b) -> Poly:
    """Multiply two polynomials.  ``(s+1)(s+2) -> s^2 + 3s + 2``."""
    return np.convolve(as_poly(a), as_poly(b))


def poly_add(a, b) -> Poly:
    """Add two polynomials, left-padding the shorter one with zeros."""
    a = as_poly(a)
    b = as_poly(b)
    n = max(a.size, b.size)
    a = np.pad(a, (n - a.size, 0))
    b = np.pad(b, (n - b.size, 0))
    return a + b


def poly_eval(coeffs, s) -> complex:
    """Evaluate a polynomial at (possibly complex) ``s`` via Horner's rule."""
    return np.polyval(as_poly(coeffs), s)


def _trim(coeffs) -> Poly:
    """Drop leading (highest-power) coefficients that are ~0."""
    p = as_poly(coeffs)
    nz = np.flatnonzero(np.abs(p) > 1e-12)
    if nz.size == 0:
        return np.array([0.0])
    return p[nz[0]:]


def format_poly(coeffs, var: str = "s") -> str:
    """Render a coefficient array as a human-readable polynomial string.

    Highest power first, ~zero terms dropped, e.g. ``[1, 3, 2] -> "s^2 + 3s + 2"``.
    Used by the on-screen transfer-function readout.
    """
    p = _trim(coeffs)
    order = p.size - 1
    terms: list[str] = []
    for i, c in enumerate(p):
        power = order - i
        if abs(c) <= 1e-12:
            continue
        sign = "-" if c < 0 else "+"
        mag = abs(c)
        # Coefficient text: hide a leading "1" unless it's the constant term.
        if power == 0:
            coef_txt = _num(mag)
        elif abs(mag - 1.0) < 1e-9:
            coef_txt = ""
        else:
            coef_txt = _num(mag)
        if power == 0:
            var_txt = ""
        elif power == 1:
            var_txt = var
        else:
            var_txt = f"{var}^{power}"
        body = f"{coef_txt}{var_txt}" or "0"
        if not terms:
            # First (leading) term keeps its sign inline only if negative.
            terms.append(f"-{body}" if c < 0 else body)
        else:
            terms.append(f" {sign} {body}")
    return "".join(terms) if terms else "0"


def _num(x: float) -> str:
    """Compact number formatting: 2 instead of 2.0, 3.14 instead of 3.14000."""
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:.3g}"


def format_tf(num, den, var: str = "s") -> tuple[str, str]:
    """Return ``(numerator_str, denominator_str)`` for display as a fraction."""
    return format_poly(num, var), format_poly(den, var)
