# 🎛️ DJ Lego

### Build a transfer function out of Lego-like blocks, then *hear* it.

Control theory isn't just robots and inverted pendulums. A transfer function is
a transfer function — and one of the most fun places they live is **audio**.
In this project you load a song, snap together classic control blocks (poles,
a resonant second-order pair, lead/lag, plus an echo and a distortion...), and
the app shows you the **Bode plot**, the **transfer function**, and the **live
spectrum** of what goes in versus what comes out — all while the music plays and
you turn the knobs
like a DJ.

Move a pole and you'll *hear* the treble roll off. Drop the damping on the
second-order block and a resonant peak whistles out of your speakers. Add a
delay and crank its feedback until the echoes run away and howl (safely —
there's a limiter). It's the same math you'll use all semester, but this time
it's coming out of the speakers.

![screenshot](assets/screenshot.png)

---

## Setup

You need **Python 3.11+** (3.14 recommended — it's what this is tested on; the
optional LEGO package requires 3.11+). From this folder:

```bash
git clone git@github.com:rkcosner/DJ_Lego.git

cd DJ_lego 

python -m venv .venv

# Windows:
.venv\Scripts\activate
# macOS
brew install portaudio
source .venv/bin/activate
# Linux:
sudo apt install portaudio19-dev
source .venv/bin/activate

pip install -r requirements.txt
```

Everything installs from pip — **no system ffmpeg or audio libraries to
install**. The wheels bundle what they need.

> **On a managed/locked-down Windows machine** (e.g. one with an enforced
> WDAC / Application Control policy, common on university/corporate laptops),
> the bundled MP3/MP4 decoder's DLLs may be blocked. The app handles this
> automatically: it falls back to **Windows Media Foundation** (built-in,
> signed OS codecs) to decode the song, so MP4/M4A/MP3 still work with no extra
> setup. WAV always works everywhere.

## Run

```bash
python run.py
```

Then click **Open song…** and pick an audio file. Don't have one handy? Generate
a demo tone:

```bash
python scripts/make_demo_audio.py     # writes assets/demo_tone.wav
```

## How to play

1. **Click a block** in the left palette (or drag it onto the rack) to add it to
   your signal chain. The **linear** blocks combine into a single transfer
   function `H(s)` — that's the curve in the top-right plot, which sits directly
   above the live spectrum so you see the filter imposed on the music.
2. **Click a block in the rack** to reveal its knobs, then drag the sliders. The
   plot, the `H(s)` readout, and the sound all update **live**.
3. **Drag blocks in the rack** to reorder them; press **Delete** to remove one.
4. Use the **Bypass** button to A/B your chain against the raw signal.

## The blocks

The first six are **linear** — they fold into the one transfer function `H(s)`
on the Bode plot. The last two are **effects** that can't be written as a
transfer function, so they're handled specially (see below).

| Block | What it is | What you hear |
|-------|-----------|---------------|
| **Gain** | `K` | Straight level (0–4×). |
| **Low-pass (real pole)** | `wc/(s+wc)` | A pole at the cutoff — bass passes, treble rolls off −20 dB/dec. |
| **High-pass (pole + zero)** | `s/(s+wc)` | Pole at the cutoff, zero at DC — treble passes, bass rolls off −20 dB/dec. |
| **Resonance (2nd-order)** | `wn²/(s²+2ζwn·s+wn²)` | Underdamped pair. Low `ζ` (down to 0.02) = a sharp resonant peak/whistle at `fn`. |
| **Lead / Lag** | `(1+s/fz)/(1+s/fp)` | A shelf: `fz<fp` lifts treble, `fz>fp` cuts it. |
| **Feedback comb (delay)** | `y[n]=x[n]+g·y[n−D]` | Echoes spaced `T` apart, each ×`g`. Linear — its comb *is* drawn on the plot. |
| **Saturation (nonlinear)** | `y[n]=tanh(a·x[n])` | Clipping — *creates* new harmonics. No transfer function; nothing to plot. |

### The two effect blocks (handled outside the polynomial `H(s)`)

These two live in the audio engine instead of the `(num, den)` chain — but for
*opposite* reasons, and that contrast is a lesson in itself:

- **Feedback comb / delay** is still **linear** (`y[n] = x[n] + g·y[n−D]`), so
  it *does* have a transfer function — a *comb*, `H(z) = 1/(1 − g·z^{−D}) =
  1/(1 − g·e^{−sT})` — and we **do draw it on the Bode plot**. It's kept out of
  the `(num, den)` chain only for *representational* reasons: a delay is
  `e^{−sT}` in `s` (transcendental — the classic "dead time" you'd
  Padé-approximate) and a ~thousand-order IIR in `z`. Knobs are the delay `T`
  and feedback gain `g` (`|g|<1` for stability). Note the comb teeth are spaced
  `1/T` apart, so for long `T` they get very dense on a log axis.
- **Saturation / distortion** `y[n] = tanh(a·x[n])` is genuinely **nonlinear**:
  superposition fails, so it has **no transfer function in any domain** and
  nothing to draw. Its one knob is the input gain `a`. Instead of reshaping
  existing frequencies it **manufactures brand-new harmonics** — turn `a` up
  and watch new spikes sprout in the output spectrum with no counterpart in the
  input. That's the thing no transfer function can do.

## Try this

- **Make a DJ low-pass sweep.** Add one **Low-pass** block and drag its cutoff
  from 18 kHz down to 100 Hz while a track plays. That's the classic "filter
  drop." Watch the pole (the −3 dB corner) slide down the plot, right above the
  spectrum it's carving.
- **Build a resonant wah.** Add a **Resonance** block, set `ζ ≈ 0.02`, and sweep
  `fn`. The magnitude peak lines up exactly with the spike it pumps into the
  output spectrum below it.
- **Echo / dub, and see its comb.** Add a **Feedback comb (delay)**, set
  `T ≈ 300 ms`, `g ≈ 0.6`. You hear echoes — and the plot grows the comb teeth
  of `1/(1 − g·e^{−sT})` (dense at long `T`; shorten `T` to spread them out).
  Push `g` toward 0.95 for runaway dub echoes (the limiter keeps it safe) — a
  feedback loop going unstable that you can *hear*.
- **Hear (and see) nonlinearity.** Play a fairly pure/simple sound, add
  **Saturation**, and raise `a`. New harmonic spikes appear in the output
  spectrum with no counterpart in the input — proof that a nonlinearity
  *creates* frequencies, which no transfer function can do. Note there's nothing
  new on the Bode plot: it has no `H(s)`. Toggle **Bypass** to A/B it.

---

## Drive the knobs with LEGO (optional)

You can turn the dials with **LEGO Education motors and controllers** (the
Computer Science & AI kit) instead of the mouse — become a literal DJ with
physical faders. It uses the [`legoeducation`](https://github.com/LEGO/LEGOEducation)
package over Bluetooth:

```bash
pip install legoeducation      # or:  uv pip install legoeducation
```

In the **LEGO control** panel (bottom-left):

1. Pick your device type (**single motor**, **double motor**, or **controller**),
   your **connection-card color**, and type its **serial number**.
2. Hit **Connect**. (No hardware yet? Tick **Simulate** to get a moving mock
   input so you can wire up and test the mapping.)
3. Each connected device shows one or two **input channels** with a live 0–100 %
   bar. Use the dropdown next to a channel to point it at any knob in your rack.
   Now the motor/lever drives that dial in real time.

Every input is normalized to **[0, 1]** the same way, so mappings are consistent:

| Input | Read as | → [0, 1] |
|-------|---------|----------|
| Single motor | `motor.position` (deg) | `(deg mod 360)/360` — one turn = full sweep |
| Double motor | `motor[MOTOR_LEFT/RIGHT].position` | same, per side |
| Controller | `sensor.leftPercent / rightPercent` | `(pct+100)/200` — lever centre = 0.5 |

> The package doesn't publish exact value ranges, so those two mappings are
> documented assumptions in [`djlego/lego/manager.py`](djlego/lego/manager.py)
> (`normalize_position`, `normalize_percent`) — tweak them if your hardware
> reports a different range. The whole panel also runs in **Simulate** mode with
> no package and no hardware.

---

## How it works (for the curious)

```
song file ──▶ decode (PyAV/stdlib) ──▶ ┌─ real-time audio thread ─┐
                                        │  IIR filter (b,a)  ──▶ 🔊 │
   your block rack ─▶ combine TFs ─▶ H(s)│  limiter (tanh)          │
        │                    │           └──────────────────────────┘
        │                    └─▶ bilinear transform ─▶ (b,a) discrete filter
        └─▶ Bode plot  +  H(s) readout       (pushed live on every knob move)
```

- **`djlego/dsp/`** — the control math. Each linear block maps its knobs to a
  continuous `(num, den)` in `s`; the chain multiplies them (series);
  `bode()` evaluates `H(jω)`; `discretize.py` bilinear-transforms the *one*
  combined `H(s)` into a digital filter for playback, so **what you see on the
  Bode plot is what you hear**.
- **`djlego/audio/`** — decode a song to a stereo array, then a background
  PortAudio thread runs the IIR filter with the *current* coefficients, followed
  by the effect blocks (distortion, delay). Filter state carries across knob
  changes so dragging a slider is smooth, and a `tanh` limiter guarantees the
  output never leaves `[-1, 1]` (that's why a runaway echo *howls* instead of
  destroying your speakers).
- **`djlego/ui/`** — the PySide6 (Qt) interface and the embedded matplotlib
  Bode/FFT plots.

Run the tests with `pytest` — they pin down the control-theory facts (a
low-pass is −3 dB at its cutoff, the hand-rolled bilinear transform matches
`scipy.signal.bilinear`, feedback moves the poles, every block discretises to a
stable filter, distortion creates harmonics, and the delay produces an echo).

### Extending it (optional, C++)

The real-time filter is a single IIR stage in Python (`scipy.signal.lfilter`),
which is plenty fast for one chain. If you want a systems-programming exercise,
the natural extension is to reimplement that inner loop in C++ and expose it
with `pybind11` — the `AudioEngine` filter call is the only thing you'd swap.

### Troubleshooting

- **MP3/MP4 won't load on a managed Windows laptop** — a WDAC/Application
  Control policy is blocking PyAV's DLLs. The app automatically falls back to
  **Windows Media Foundation** to decode the file, so this normally just works
  (the first load may take a second longer while it transcodes). If you see
  *"the Windows Media Foundation fallback also failed"* too, the file may have
  no audio track or an unusual codec — convert it to WAV and load that. WAV
  always works.
- **No sound / no output device** — check your system's default output device;
  the app opens a stereo stream at 44.1 kHz.
