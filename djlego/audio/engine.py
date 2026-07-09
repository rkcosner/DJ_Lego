"""Real-time playback + live IIR filtering with a safety limiter.

Design notes (the parts that make the "DJ" experience work):

* A background PortAudio thread (via ``sounddevice``) pulls blocks from the
  decoded song and runs one direct-form IIR stage (``scipy.signal.lfilter``)
  using the *current* ``(b, a)`` coefficients.  The GUI thread swaps those
  coefficients whenever a knob moves.
* **Filter state (`zi`) is preserved across coefficient swaps** as long as the
  filter order is unchanged.  That is what makes dragging a knob smooth rather
  than a burst of clicks -- the state carries over, only the coefficients
  nudge.  The order only changes on structural edits (adding/removing a block),
  where a tiny transient is acceptable.
* A ``tanh`` **safety limiter** on the master output guarantees the signal
  stays in [-1, 1].  This is deliberate: cranking a Delay/Echo's feedback toward
  runaway *howls* instead of exploding -- the limiter turns what would be a
  speaker-destroying blow-up into a bounded, safe howl.  A finite-check
  additionally resets the filter state if the IIR diverges to inf/NaN.
* The most recent input and output samples are stashed in ring buffers so the
  GUI can draw live input/output FFTs.
"""

from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd
from scipy import signal

BLOCKSIZE = 1024
FFT_N = 4096  # ring-buffer length feeding the live FFT panels


class DelayLine:
    """A stereo feedback comb filter:  y[n] = x[n] + g·y[n−D].

    Transfer function ``H(z) = 1 / (1 - g·z^-D)``.  The output ``y`` is stored
    in the buffer so it feeds back, so the impulse response is the input plus
    echoes at ``D, 2D, 3D, ...`` decaying by ``g`` each hop.  Vectorised per
    block, which is exact as long as ``D >= frames`` (guaranteed by the >=30 ms
    minimum delay), since then every ``y[n-D]`` comes from an earlier block.
    """

    def __init__(self, maxlen: int, channels: int):
        self.buf = np.zeros((maxlen, channels), dtype=np.float64)
        self.maxlen = maxlen
        self.w = 0

    def process(self, x, D, g):
        frames = x.shape[0]
        n = np.arange(frames)
        y = x + g * self.buf[(self.w - D + n) % self.maxlen]
        self.buf[(self.w + n) % self.maxlen] = y
        self.w = (self.w + frames) % self.maxlen
        return y


class AudioEngine:
    def __init__(self, samplerate: int = 44100, channels: int = 2):
        self.samplerate = samplerate
        self.channels = channels

        self._lock = threading.Lock()
        self._data: np.ndarray | None = None  # (n, channels) float32
        self._pos = 0
        self._playing = False
        self.loop = True
        self._bypass = False  # A/B: play the dry input, ignore the chain

        # Post-chain effects handled outside the linear H(s), applied in rack
        # order: nonlinear distortion (tanh) and feedback delay/echo lines.
        # `_effects` is a list of dicts; delay lines keep persistent state in
        # `_delay_lines`, keyed by block id so echoes survive knob tweaks.
        self._effects: list[dict] = []
        self._delay_lines: dict[str, DelayLine] = {}
        self._delay_maxlen = int(samplerate * 1.2)  # up to ~1 s delay + headroom

        # Current filter (identity until a chain is set).
        self._b = np.array([1.0])
        self._a = np.array([1.0])
        self._zi = np.zeros((0, channels))
        self._volume = 0.8

        # Live-FFT ring buffers (mono mixdown of input and output).
        self._ring_in = np.zeros(FFT_N, dtype=np.float32)
        self._ring_out = np.zeros(FFT_N, dtype=np.float32)
        # Precompute the FFT window + frequency axis once (reused every frame).
        self._fft_win = np.hanning(FFT_N).astype(np.float32)
        self._fft_freqs = np.fft.rfftfreq(FFT_N, 1.0 / samplerate)
        self._fft_scale = 2.0 / (FFT_N * 0.5)

        self._stream: sd.OutputStream | None = None
        self.start_error: str | None = None

    # --- stream lifecycle ---------------------------------------------------

    def start(self) -> bool:
        """Open the output stream.  Returns True on success.

        Never raises: a machine with no output device (or a blocked PortAudio)
        should still get a working UI -- it just won't make sound.  The reason
        is stashed on ``self.start_error`` for the caller to surface.
        """
        if self._stream is not None:
            return True
        try:
            self._stream = sd.OutputStream(
                samplerate=self.samplerate,
                channels=self.channels,
                blocksize=BLOCKSIZE,
                dtype="float32",
                latency="high",  # bigger buffer = fewer dropouts on slow CPUs
                callback=self._callback,
            )
            self._stream.start()
            return True
        except Exception as exc:  # noqa: BLE001
            self._stream = None
            self.start_error = str(exc)
            return False

    def close(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    # --- transport ----------------------------------------------------------

    def load(self, data: np.ndarray, samplerate: int):
        """Install a decoded song (must already match the engine samplerate)."""
        if samplerate != self.samplerate:
            raise ValueError("song samplerate must match engine samplerate")
        with self._lock:
            self._data = np.ascontiguousarray(data, dtype=np.float32)
            self._pos = 0
            self._playing = False

    def play(self):
        with self._lock:
            if self._data is not None:
                self._playing = True

    def pause(self):
        with self._lock:
            self._playing = False

    @property
    def playing(self) -> bool:
        with self._lock:
            return self._playing

    def seek_fraction(self, frac: float):
        with self._lock:
            if self._data is not None:
                n = len(self._data)
                self._pos = int(np.clip(frac, 0.0, 1.0) * n) % max(n, 1)

    def set_volume(self, vol: float):
        with self._lock:
            self._volume = float(np.clip(vol, 0.0, 1.0))

    def set_bypass(self, on: bool):
        """When on, playback is the dry input signal (the chain is ignored)."""
        with self._lock:
            self._bypass = bool(on)

    def set_effects(self, effects):
        """Set the ordered post-chain effects (distortion + delay blocks).

        ``effects`` is a list of dicts in rack order, e.g.
        ``{"kind": "distort", "a": 6.0}`` or
        ``{"kind": "delay", "id": ..., "T": 300.0, "g": 0.45}`` (T in ms).
        """
        with self._lock:
            self._effects = list(effects)
            active = {e["id"] for e in effects if e.get("kind") == "delay"}
            for k in list(self._delay_lines):
                if k not in active:
                    del self._delay_lines[k]  # forget removed delays' echoes
            for e in effects:
                if e.get("kind") == "delay" and e["id"] not in self._delay_lines:
                    self._delay_lines[e["id"]] = DelayLine(
                        self._delay_maxlen, self.channels
                    )

    def position(self) -> tuple[float, float]:
        """Return ``(current_seconds, duration_seconds)``."""
        with self._lock:
            if self._data is None:
                return 0.0, 0.0
            n = len(self._data)
            return self._pos / self.samplerate, n / self.samplerate

    # --- live filter --------------------------------------------------------

    def set_coefficients(self, b: np.ndarray, a: np.ndarray):
        """Swap in new discrete filter coefficients (called on every knob move)."""
        b = np.asarray(b, dtype=float)
        a = np.asarray(a, dtype=float)
        order = max(b.size, a.size) - 1
        with self._lock:
            self._b = b
            self._a = a
            if self._zi.shape[0] != order:
                # Structural change -> restart filter memory from rest.
                self._zi = np.zeros((order, self.channels))

    # --- live FFT -----------------------------------------------------------

    def spectra(self):
        """Return ``(freqs_hz, in_db, out_db)`` for the current audio window."""
        with self._lock:
            xi = self._ring_in.copy()
            xo = self._ring_out.copy()
        win = self._fft_win
        mag_in = np.abs(np.fft.rfft(xi * win))
        mag_out = np.abs(np.fft.rfft(xo * win))
        in_db = 20.0 * np.log10(np.maximum(mag_in * self._fft_scale, 1e-6))
        out_db = 20.0 * np.log10(np.maximum(mag_out * self._fft_scale, 1e-6))
        return self._fft_freqs, in_db, out_db

    # --- audio callback (runs on the PortAudio thread) ----------------------

    def _callback(self, outdata, frames, time_info, status):
        with self._lock:
            data = self._data
            playing = self._playing
            if data is None or not playing:
                outdata.fill(0.0)
                return
            pos = self._pos
            b, a, zi, vol = self._b, self._a, self._zi, self._volume
            loop = self.loop
            bypass = self._bypass
            # Freeze an effect "plan" for this block while holding the lock, so
            # coefficients/state can't change mid-callback.  Bypass = fully dry.
            plan = []
            if not bypass:
                for e in self._effects:
                    if e["kind"] == "distort":
                        plan.append(("distort", e["a"]))
                    elif e["kind"] == "delay":
                        line = self._delay_lines.get(e["id"])
                        if line is not None:
                            D = int(e["T"] / 1000.0 * self.samplerate)
                            D = max(frames, min(D, self._delay_maxlen - frames))
                            plan.append(("delay", line, D, e["g"]))
            n = len(data)

        # Gather the next `frames` samples, wrapping if we loop.
        end = pos + frames
        if end <= n:
            block = data[pos:end]
            newpos = end
            done = False
        elif loop:
            first = data[pos:]
            rem = frames - len(first)
            block = np.concatenate([first, data[:rem]], axis=0)
            newpos = rem
            done = False
        else:
            first = data[pos:]
            block = np.zeros((frames, self.channels), dtype=np.float32)
            block[: len(first)] = first
            newpos = n
            done = True

        # Filter each channel with continuous state.  Work in float64 so an
        # unstable loop grows gracefully instead of overflowing float32.
        out = np.empty((frames, self.channels), dtype=np.float64)
        if bypass:
            out[:] = block  # dry A/B: play the input untouched
        elif zi.shape[0] == 0:
            # Order-0 filter: a pure scalar gain b0/a0.  This covers a Gain
            # block (or any all-gain chain) *and* the identity case where an
            # empty chain gives b0/a0 == 1.  (Do NOT just copy -- that would
            # silently drop the gain.)
            out[:] = block * (b[0] / a[0])
        else:
            for ch in range(self.channels):
                y, zi[:, ch] = signal.lfilter(b, a, block[:, ch], zi=zi[:, ch])
                out[:, ch] = y

        # Bound the recursion so an unstable feedback loop *saturates into a
        # sustained howl* rather than exploding to inf and going silent.  The
        # bounds are far above any normal (~[-1, 1]) signal, so stable chains
        # are untouched; only a diverging loop ever hits them.
        np.clip(zi, -32.0, 32.0, out=zi)
        np.clip(out, -8.0, 8.0, out=out)
        # Last-resort safety in case something still went non-finite.
        if not np.all(np.isfinite(out)):
            out[:] = 0.0
            zi[:] = 0.0

        # Post-chain effects (NOT part of the linear H(s)), in rack order:
        #   distort -> tanh clipper; delay -> feedback echo.
        # We apply them *before* capturing the output FFT so the harmonics a
        # clipper creates (and the echoes) show up in the spectrum.
        for stage in plan:
            if stage[0] == "distort":
                a = stage[1]
                # Pre-gain a into the clipper, post-scale by 1/a.  Since
                # tanh(u) <= u this can never raise the level (more drive = more
                # harmonics, not more volume); small signals pass at ~unity.
                out = np.tanh(out * a) / a
            else:
                _, line, D, g = stage
                out = line.process(out, D, g)

        out *= vol
        outdata[:] = np.tanh(out)  # safety limiter -> always in (-1, 1)

        # Publish state + FFT ring buffers.
        in_mono = block.mean(axis=1)
        out_mono = out.mean(axis=1)
        with self._lock:
            self._pos = newpos
            self._zi = zi
            self._ring_in = np.concatenate([self._ring_in, in_mono])[-FFT_N:]
            self._ring_out = np.concatenate([self._ring_out, out_mono])[-FFT_N:]
            if done:
                self._playing = False
