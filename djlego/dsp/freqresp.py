"""Bode data: evaluate the combined transfer function at ``s = jw``.

The rational part comes straight from the combined ``(num, den)``.  Optional
``delays`` add feedback-comb factors ``1 / (1 - g * e^{-s T})`` -- the linear
transfer function of each Delay/Echo block -- so the plot shows the full
*linear* response, including the comb.  (Nonlinear blocks like distortion have
no transfer function and are not represented here.)
"""

from __future__ import annotations

import numpy as np

from .polynomial import poly_eval


def bode(
    num,
    den,
    delays=(),
    f_min: float = 10.0,
    f_max: float = 20000.0,
    n: int = 512,
):
    """Return ``(freq_hz, mag_db, phase_deg)`` over a log-spaced frequency grid.

    ``delays`` is an iterable of ``(T_seconds, g)`` feedback-comb factors, each
    contributing ``1 / (1 - g * e^{-j w T})`` to the response.  Phase is
    unwrapped so lead/lag and resonance read as smooth curves.
    """
    f = np.logspace(np.log10(f_min), np.log10(f_max), n)
    w = 2.0 * np.pi * f
    s = 1j * w
    with np.errstate(divide="ignore", invalid="ignore"):
        h = poly_eval(num, s) / poly_eval(den, s)
        for T, g in delays:
            h = h / (1.0 - g * np.exp(-s * T))
    # Guard against a pole landing on (or near) the jw axis -- e.g. a feedback
    # loop tuned to marginal stability -- which sends |H| to infinity.  We clamp
    # the magnitude to a large-but-finite range and zero out any non-finite
    # phase, so the Bode plot can never crash with "limits cannot be NaN/Inf".
    mag = np.abs(h)
    mag = np.where(np.isfinite(mag), mag, 1e6)
    mag_db = 20.0 * np.log10(np.clip(mag, 1e-12, 1e6))
    ang = np.angle(h)
    ang = np.where(np.isfinite(ang), ang, 0.0)
    phase_deg = np.degrees(np.unwrap(ang))
    return f, mag_db, phase_deg
