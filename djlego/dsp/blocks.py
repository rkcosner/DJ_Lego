"""The palette of control blocks students drag into their signal chain.

Every block maps its knob values to a continuous-time transfer function
``(num, den)`` in ``s`` (highest power first).  The frequency labels are in
**Hz** because that is what a DJ thinks in, but the transfer functions are
built with angular frequency ``w = 2*pi*f`` so the poles/zeros land where the
Bode plot says they do.

Pedagogical framing baked into the choices:

* a **real pole** is presented as a *low-pass cutoff* -- students literally
  hear the pole location as a tone control;
* the **2nd-order** block is a *resonant peak* whose sharpness is the damping
  ratio zeta they know from mechatronics.

Most blocks are **linear** and fold into the combined ``H(s)``.  Two are
audio-engine **effects** (``effect != ""``) handled outside that polynomial,
for *different* reasons:

* **Delay/Echo** is still linear -- it has a transfer function (a comb) -- but
  a delay is ``e^{-sT}`` in ``s`` (transcendental, not a polynomial ratio) and
  ``1/(1 - g*z^-D)`` in ``z`` with ``D`` in the thousands, so it's impractical
  to fold into the small-polynomial chain.
* **Distortion** ``tanh(drive*x)`` is genuinely nonlinear -- no transfer
  function in any domain -- and *creates* new harmonics.

The palette deliberately sticks to effects you can actually *hear* -- no ideal
integrator (muddies everything into bass) or all-pass (inaudible phase-only).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
import uuid

import numpy as np


@dataclass(frozen=True)
class ParamSpec:
    """One tunable knob on a block."""

    key: str
    label: str
    minv: float
    maxv: float
    default: float
    unit: str = ""
    log: bool = False  # frequency knobs sweep logarithmically


@dataclass(frozen=True)
class BlockSpec:
    """A block *type* in the palette (not a placed instance)."""

    type: str
    name: str
    blurb: str  # one-line "what it does" shown as a tooltip / caption
    params: tuple[ParamSpec, ...]
    tf: Callable[[dict], tuple[np.ndarray, np.ndarray]]
    # "" for ordinary linear blocks that fold into H(s).  Otherwise the name of
    # an audio-engine effect handled outside the transfer function:
    #   "distort" -> nonlinear clipper;  "delay" -> feedback echo (comb filter).
    effect: str = ""

    def default_params(self) -> dict:
        return {p.key: p.default for p in self.params}


def _hz(f: float) -> float:
    """Hz -> rad/s."""
    return 2.0 * np.pi * f


# --- transfer-function builders (num, den) in s, highest power first --------


def _tf_gain(p):
    K = p["K"]
    return np.array([K]), np.array([1.0])


def _tf_identity(p):
    # Placeholder for nonlinear blocks (distortion): they carry no transfer
    # function, so if this is ever combined into the linear chain it is a no-op.
    return np.array([1.0]), np.array([1.0])


def _tf_lowpass(p):
    # Real pole as a low-pass cutoff:  wc / (s + wc),  unity DC gain
    wc = _hz(p["fc"])
    return np.array([wc]), np.array([1.0, wc])


def _tf_highpass(p):
    # Pole at wc + zero at the origin:  s / (s + wc).  Passes treble, rolls off
    # bass -20 dB/decade below fc.  Unity gain at high frequency.
    wc = _hz(p["fc"])
    return np.array([1.0, 0.0]), np.array([1.0, wc])


def _tf_leadlag(p):
    # (1 + s/wz) / (1 + s/wp).  fz < fp -> phase LEAD; fz > fp -> phase LAG.
    wz = _hz(p["fz"])
    wp = _hz(p["fp"])
    return np.array([1.0 / wz, 1.0]), np.array([1.0 / wp, 1.0])


def _tf_second_order(p):
    # Underdamped resonance:  wn^2 / (s^2 + 2*zeta*wn*s + wn^2), unity DC gain
    wn = _hz(p["fn"])
    zeta = p["zeta"]
    return np.array([wn * wn]), np.array([1.0, 2.0 * zeta * wn, wn * wn])


# --- the palette ------------------------------------------------------------

BLOCKS: dict[str, BlockSpec] = {
    b.type: b
    for b in [
        BlockSpec(
            "gain",
            "Gain",
            "Turns the whole signal up or down. K = flat level.",
            (ParamSpec("K", "K", 0.0, 8.0, 1.0),),
            _tf_gain,
        ),
        BlockSpec(
            "lowpass",
            "Low-pass (real pole)",
            "A real pole at the cutoff. Passes bass, rolls off treble "
            "-20 dB/decade above fc.",
            (ParamSpec("fc", "cutoff fc", 20.0, 18000.0, 800.0, "Hz", log=True),),
            _tf_lowpass,
        ),
        BlockSpec(
            "highpass",
            "High-pass (pole + zero)",
            "A pole at the cutoff with a zero at DC. Passes treble, rolls off "
            "bass -20 dB/decade below fc.",
            (ParamSpec("fc", "cutoff fc", 20.0, 18000.0, 400.0, "Hz", log=True),),
            _tf_highpass,
        ),
        BlockSpec(
            "second_order",
            "Resonance (2nd-order)",
            "Underdamped pair. Small zeta = sharp resonant peak at fn "
            "(a wah/EQ bump).",
            (
                ParamSpec("fn", "freq fn", 40.0, 12000.0, 1000.0, "Hz", log=True),
                ParamSpec("zeta", "damping zeta", 0.025, 2.0, 0.5),
            ),
            _tf_second_order,
        ),
        BlockSpec(
            "leadlag",
            "Lead / Lag",
            "(1+s/fz)/(1+s/fp): a shelf. fz<fp lifts treble; fz>fp cuts it.",
            (
                ParamSpec("fz", "zero fz", 20.0, 18000.0, 300.0, "Hz", log=True),
                ParamSpec("fp", "pole fp", 20.0, 18000.0, 3000.0, "Hz", log=True),
            ),
            _tf_leadlag,
        ),
        BlockSpec(
            "delay",
            "Feedback comb (delay)",
            "Linear comb filter:  y[n] = x[n] + g·y[n−D],  D = round(T·f_s).\n"
            "H(z) = 1 / (1 − g·z^(−D)) = 1 / (1 − g·e^(−sT)).\n"
            "Echoes spaced T apart, each ×g; needs |g| < 1 to stay stable. Its "
            "comb response is drawn on the Bode plot.",
            (
                ParamSpec("T", "T", 30.0, 1000.0, 300.0, "ms", log=True),
                ParamSpec("g", "g", 0.0, 0.95, 0.45),
            ),
            _tf_identity,
            effect="delay",
        ),
        BlockSpec(
            "distortion",
            "Saturation (nonlinear)",
            "Nonlinear waveshaper:  y[n] = tanh(a·x[n]).\n"
            "Superposition fails, so there is NO transfer function and nothing "
            "to draw on the Bode plot. Raising the input gain a drives the "
            "signal into the tanh, synthesising new harmonics you can watch "
            "appear in the output spectrum.",
            (ParamSpec("a", "a", 1.0, 50.0, 6.0, log=True),),
            _tf_identity,
            effect="distort",
        ),
    ]
}


def make_block(block_type: str) -> "PlacedBlock":
    """Create a fresh placed-block instance with default knob values."""
    spec = BLOCKS[block_type]
    return PlacedBlock(
        id=uuid.uuid4().hex,
        type=block_type,
        params=spec.default_params(),
    )


def block_tf(block_type: str, params: dict) -> tuple[np.ndarray, np.ndarray]:
    """Continuous ``(num, den)`` for a block type at the given knob values."""
    return BLOCKS[block_type].tf(params)


@dataclass
class PlacedBlock:
    """An instance of a block placed in the signal chain, with live knobs."""

    id: str
    type: str
    params: dict = field(default_factory=dict)

    @property
    def spec(self) -> BlockSpec:
        return BLOCKS[self.type]

    def tf(self) -> tuple[np.ndarray, np.ndarray]:
        return block_tf(self.type, self.params)
