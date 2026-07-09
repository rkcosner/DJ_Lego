"""Continuous-time transfer-function math for the DJ booth.

Everything here works on ``(num, den)`` pairs of real polynomial coefficients
in the Laplace variable ``s``, ordered **highest power first** (the same
convention as ``numpy.poly1d`` and ``scipy.signal``).  For example the
first-order low-pass ``a / (s + a)`` is ``num = [a]``, ``den = [1, a]``.
"""

from .polynomial import poly_mul, poly_add, poly_eval, format_poly, format_tf
from .blocks import BLOCKS, BlockSpec, ParamSpec, make_block, block_tf
from .chain import ChainBlock, combine_chain
from .freqresp import bode
from .discretize import to_discrete

__all__ = [
    "poly_mul",
    "poly_add",
    "poly_eval",
    "format_poly",
    "format_tf",
    "BLOCKS",
    "BlockSpec",
    "ParamSpec",
    "make_block",
    "block_tf",
    "ChainBlock",
    "combine_chain",
    "bode",
    "to_discrete",
]
