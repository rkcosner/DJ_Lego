"""Combine a rack of linear blocks into one transfer function.

The forward path is a **series** chain: block outputs feed the next block's
input, so the overall transfer function is the *product* of the individual
block transfer functions -- numerators convolve, denominators convolve::

    G(s) = G1(s) * G2(s) * ... * Gn(s)

This single continuous transfer function is used for *both* the Bode plot /
readout and (after discretization) the real-time audio filter, so what students
see is exactly what they hear.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .polynomial import poly_mul


@dataclass
class ChainBlock:
    """A block's contribution to the chain: its num/den and a label."""

    num: np.ndarray
    den: np.ndarray
    label: str = ""


def combine_chain(blocks: list[ChainBlock]) -> tuple[np.ndarray, np.ndarray]:
    """Series product of every block's transfer function.

    An empty chain is the identity ``1/1`` (audio passes through untouched).
    """
    num = np.array([1.0])
    den = np.array([1.0])
    for b in blocks:
        num = poly_mul(num, b.num)
        den = poly_mul(den, b.den)
    return num, den
