"""The DJ booth main window: palette -> signal chain -> Bode / TF / FFT / audio."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QSplitter,
    QListWidgetItem,
    QFileDialog,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
)

from ..dsp import combine_chain, bode, to_discrete, format_tf
from ..dsp.chain import ChainBlock
from ..dsp.blocks import BLOCKS, make_block, PlacedBlock, ParamSpec
from ..audio import AudioEngine, load_audio, AudioLoadError
from . import theme
from .controls import FloatSlider, DraggableButton, RackList, unit_to_value
from .plots import AnalysisCanvas
from .lego_panel import LegoPanel


def _panel() -> QFrame:
    f = QFrame()
    f.setObjectName("panel")
    return f


def _format_param(spec: ParamSpec, value: float) -> str:
    if spec.unit == "Hz" and value >= 1000:
        return f"{value/1000:.2g}k"
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2g}"


class TFReadout(QWidget):
    """Shows H(s) = N(s)/D(s) as a fraction, plus any delay/distortion terms."""

    def __init__(self):
        super().__init__()
        self.title = QLabel("H(s) =")
        self.title.setObjectName("h1")
        self.num = QLabel("1")
        self.num.setObjectName("tf")
        self.num.setAlignment(Qt.AlignCenter)
        self.bar = QFrame()
        self.bar.setFrameShape(QFrame.HLine)
        self.bar.setStyleSheet(f"color: {theme.TEXT};")
        self.den = QLabel("1")
        self.den.setObjectName("tf")
        self.den.setAlignment(Qt.AlignCenter)
        # Extra factors that aren't a small polynomial: delay combs (linear,
        # shown on the plot) and the nonlinear tanh (not on the plot).
        self.extra = QLabel("")
        self.extra.setObjectName("tf")

        frac = QVBoxLayout()
        frac.setSpacing(3)
        frac.addWidget(self.num)
        frac.addWidget(self.bar)
        frac.addWidget(self.den)

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 14, 10)
        row.addWidget(self.title)
        row.addLayout(frac, 0)
        row.addWidget(self.extra, 1)

    def update_tf(self, num, den, delays=(), distortions=()):
        num_s, den_s = format_tf(num, den)
        self.num.setText(num_s)
        self.den.setText(den_s)
        parts = []
        for T, g in delays:
            parts.append(f"· 1/(1 − {g:.2g}·e^(−{T:.3g}s))")
        for a in distortions:
            parts.append(f",  then  tanh({a:.2g}·x)")
        self.extra.setText("  ".join(parts))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DJ Lego — build a transfer function, hear it live")
        self.resize(1320, 820)

        self.engine = AudioEngine()
        self._audio_ok = self.engine.start()
        self.sr = self.engine.samplerate

        self.blocks: list[PlacedBlock] = []
        self.selected_id: str | None = None
        self._seeking = False

        # Cached combined TF so the (cheap) audio path and the (heavier) plot
        # path don't both recompute it.
        self._num = np.array([1.0])
        self._den = np.array([1.0])

        self._build_ui()

        # Plot updates are throttled: a knob drag fires many events, but we
        # only redraw the Bode/TF readout ~25x/sec.  Audio coefficients, by
        # contrast, update immediately on every change so the sound stays live.
        self._plot_timer = QTimer(self)
        self._plot_timer.setSingleShot(True)
        self._plot_timer.setInterval(40)
        self._plot_timer.timeout.connect(self._update_plots)

        self.refresh_tf()
        self._update_plots()  # initial draw right away

        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30 fps for the live FFT + transport
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

        if not self._audio_ok:
            QTimer.singleShot(150, self._warn_no_audio)

    def _warn_no_audio(self):
        QMessageBox.warning(
            self,
            "No audio output",
            "Couldn't open an audio output device, so playback is disabled — "
            "but everything else (blocks, Bode plot, transfer function) still "
            f"works.\n\nDetails: {self.engine.start_error}",
        )

    # ------------------------------------------------------------------ UI --

    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left_column())
        splitter.addWidget(self._build_chain_column())
        splitter.addWidget(self._build_analysis_column())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 4)
        splitter.setSizes([260, 360, 700])

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)
        outer.addWidget(self._build_transport())
        outer.addWidget(splitter, 1)
        self.setCentralWidget(root)

    def _build_transport(self) -> QWidget:
        bar = _panel()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 8, 12, 8)

        open_btn = QPushButton("📂  Open song…")
        open_btn.clicked.connect(self._open_file)
        self.song_label = QLabel("no song loaded")
        self.song_label.setObjectName("dim")

        self.play_btn = QPushButton("▶  Play")
        self.play_btn.setObjectName("accent")
        self.play_btn.clicked.connect(self._toggle_play)
        self.play_btn.setEnabled(False)

        self.bypass_btn = QPushButton("Bypass")
        self.bypass_btn.setObjectName("bypass")
        self.bypass_btn.setCheckable(True)
        self.bypass_btn.setToolTip(
            "A/B compare: play the dry (unprocessed) signal so you can hear "
            "exactly what your chain is doing. The chain stays built."
        )
        self.bypass_btn.toggled.connect(self._on_bypass)

        self.pos_slider = QSlider(Qt.Horizontal)
        self.pos_slider.setRange(0, 1000)
        self.pos_slider.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.pos_slider.sliderReleased.connect(self._end_seek)
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("dim")

        vol = QSlider(Qt.Horizontal)
        vol.setRange(0, 100)
        vol.setValue(80)
        vol.setFixedWidth(110)
        vol.valueChanged.connect(lambda v: self.engine.set_volume(v / 100.0))

        lay.addWidget(open_btn)
        lay.addWidget(self.song_label, 1)
        lay.addWidget(self.play_btn)
        lay.addWidget(self.bypass_btn)
        lay.addWidget(self.pos_slider, 2)
        lay.addWidget(self.time_label)
        lay.addWidget(QLabel("🔊"))
        lay.addWidget(vol)
        return bar

    def _build_palette(self) -> QWidget:
        panel = _panel()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        title = QLabel("Blocks")
        title.setObjectName("h1")
        hint = QLabel("click to add · drag onto the rack")
        hint.setObjectName("dim")
        lay.addWidget(title)
        lay.addWidget(hint)
        for spec in BLOCKS.values():
            btn = DraggableButton(spec.type, spec.name)
            btn.setToolTip(spec.blurb)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(lambda _=False, t=spec.type: self.add_block(t))
            lay.addWidget(btn)
        lay.addStretch(1)
        return panel

    def _build_left_column(self) -> QWidget:
        col = QWidget()
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # Blocks palette on top; LEGO control below (scrollable).
        self.lego_panel = LegoPanel(self._lego_knobs, self._lego_set_knob)
        lego_frame = _panel()
        lf = QVBoxLayout(lego_frame)
        lf.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.lego_panel)
        lf.addWidget(scroll)

        lay.addWidget(self._build_palette())
        lay.addWidget(lego_frame, 1)
        return col

    def _build_chain_column(self) -> QWidget:
        col = QWidget()
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # Signal chain rack
        rack_panel = _panel()
        rl = QVBoxLayout(rack_panel)
        rl.setContentsMargins(12, 12, 12, 12)
        head = QHBoxLayout()
        t = QLabel("Signal chain")
        t.setObjectName("h1")
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear_chain)
        head.addWidget(t)
        head.addStretch(1)
        head.addWidget(clear)
        hint = QLabel("input ▸ blocks run top→bottom ▸ output · drag to reorder · Del to remove")
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        self.rack = RackList()
        self.rack.itemSelectionChanged.connect(self._on_select)
        self.rack.reordered.connect(self._on_reorder)
        self.rack.addRequested.connect(self.add_block)
        self.rack.removeRequested.connect(self.remove_block)
        rl.addLayout(head)
        rl.addWidget(hint)
        rl.addWidget(self.rack, 1)

        # Selected-block knobs
        self.param_panel = _panel()
        self.param_layout = QVBoxLayout(self.param_panel)
        self.param_layout.setContentsMargins(12, 12, 12, 12)
        self.param_layout.setSpacing(6)
        self._rebuild_params()

        lay.addWidget(rack_panel, 1)
        lay.addWidget(self.param_panel)
        return col

    def _build_analysis_column(self) -> QWidget:
        col = QWidget()
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        tf_panel = _panel()
        tfl = QVBoxLayout(tf_panel)
        tfl.setContentsMargins(6, 4, 6, 4)
        self.tf_readout = TFReadout()
        tfl.addWidget(self.tf_readout)

        analysis_panel = _panel()
        al = QVBoxLayout(analysis_panel)
        al.setContentsMargins(8, 8, 8, 8)
        self.analysis = AnalysisCanvas()
        al.addWidget(self.analysis)

        lay.addWidget(tf_panel)
        lay.addWidget(analysis_panel, 1)
        return col

    # -------------------------------------------------------- chain edits --

    def add_block(self, block_type: str, row: int | None = None):
        block = make_block(block_type)
        if row is None or row < 0 or row > len(self.blocks):
            self.blocks.append(block)
        else:
            self.blocks.insert(row, block)
        self.selected_id = block.id
        self._rebuild_rack()
        self._rebuild_params()
        self._sync_lego_knobs()
        self.refresh_tf()

    def remove_block(self, block_id: str):
        self.blocks = [b for b in self.blocks if b.id != block_id]
        if self.selected_id == block_id:
            self.selected_id = self.blocks[-1].id if self.blocks else None
        self._rebuild_rack()
        self._rebuild_params()
        self._sync_lego_knobs()
        self.refresh_tf()

    def _clear_chain(self):
        self.blocks = []
        self.selected_id = None
        self._rebuild_rack()
        self._rebuild_params()
        self._sync_lego_knobs()
        self.refresh_tf()

    def _sync_lego_knobs(self):
        if hasattr(self, "lego_panel"):
            self.lego_panel.refresh_knobs()

    def _on_reorder(self):
        # Read the new order back from the rack widget and reorder the model.
        order = [self.rack.item(i).data(Qt.UserRole) for i in range(self.rack.count())]
        by_id = {b.id: b for b in self.blocks}
        self.blocks = [by_id[i] for i in order if i in by_id]
        self.refresh_tf()

    def _on_select(self):
        item = self.rack.currentItem()
        self.selected_id = item.data(Qt.UserRole) if item else None
        self._rebuild_params()

    # --------------------------------------------------------- rack/params --

    def _rack_label(self, b: PlacedBlock) -> str:
        spec = b.spec
        parts = [f"{p.label}={_format_param(p, b.params[p.key])}" for p in spec.params]
        detail = "  ·  ".join(parts)
        return f"{spec.name}\n{detail}" if detail else spec.name

    def _rebuild_rack(self):
        self.rack.blockSignals(True)
        self.rack.clear()
        for b in self.blocks:
            item = QListWidgetItem(self._rack_label(b))
            item.setData(Qt.UserRole, b.id)
            self.rack.addItem(item)
            if b.id == self.selected_id:
                self.rack.setCurrentItem(item)
        self.rack.blockSignals(False)

    def _update_rack_label(self, b: PlacedBlock):
        for i in range(self.rack.count()):
            item = self.rack.item(i)
            if item.data(Qt.UserRole) == b.id:
                item.setText(self._rack_label(b))
                return

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def _rebuild_params(self):
        self._clear_layout(self.param_layout)
        # Sliders for the currently-selected block, keyed by param, so an
        # external driver (LEGO) can move the on-screen slider too.
        self._param_sliders: dict[str, FloatSlider] = {}
        block = next((b for b in self.blocks if b.id == self.selected_id), None)
        if block is None:
            hint = QLabel("Select a block to tune its knobs.")
            hint.setObjectName("dim")
            self.param_layout.addWidget(hint)
            return
        title = QLabel(block.spec.name)
        title.setObjectName("h1")
        blurb = QLabel(block.spec.blurb)
        blurb.setObjectName("dim")
        blurb.setWordWrap(True)
        self.param_layout.addWidget(title)
        self.param_layout.addWidget(blurb)
        for spec in block.spec.params:
            slider = FloatSlider(spec)
            slider.set_value(block.params[spec.key])
            slider.valueChangedFloat.connect(
                lambda v, b=block, k=spec.key: self._on_param(b, k, v)
            )
            self.param_layout.addWidget(slider)
            self._param_sliders[spec.key] = slider
        self.param_layout.addStretch(1)

    def _on_param(self, block: PlacedBlock, key: str, value: float):
        block.params[key] = value
        self._update_rack_label(block)
        self.refresh_tf()

    # ------------------------------------------------------- LEGO knob bridge --

    def _lego_knobs(self) -> list[tuple[str, str]]:
        """Every tunable knob in the rack, as (knob_id, label) for the LEGO panel."""
        knobs = []
        for b in self.blocks:
            for p in b.spec.params:
                knobs.append((f"{b.id}:{p.key}", f"{b.spec.name} · {p.label}"))
        return knobs

    def _lego_set_knob(self, knob_id: str, t: float):
        """Drive a knob from a normalized [0, 1] LEGO input."""
        block_id, _, key = knob_id.partition(":")
        block = next((b for b in self.blocks if b.id == block_id), None)
        if block is None:
            return
        spec = next((p for p in block.spec.params if p.key == key), None)
        if spec is None:
            return
        value = unit_to_value(spec, t)
        block.params[key] = value
        self._update_rack_label(block)
        # Reflect on the visible slider if this block is the selected one.
        if block.id == self.selected_id and key in self._param_sliders:
            self._param_sliders[key].set_value(value)
        self.refresh_tf()

    # ------------------------------------------------------- the live math --

    def refresh_tf(self):
        """Recompute the combined TF, push audio *now*, schedule a plot redraw.

        The audio filter must track the knobs with no perceptible delay, so we
        recompute and push coefficients on every single change.  The Bode plot
        and TF readout are comparatively expensive to redraw, so they are
        coalesced onto a ~25 fps timer instead of redrawing on every event.
        """
        # Only the *linear* blocks form the transfer function; effect blocks
        # (Distortion, Delay) are handled separately in the audio engine.
        linear = [b for b in self.blocks if not b.spec.effect]
        chain = [ChainBlock(*b.tf(), label=b.spec.name) for b in linear]
        self._num, self._den = combine_chain(chain)

        # Audio: immediate.  Linear filter...
        b, a = to_discrete(self._num, self._den, self.sr)
        self.engine.set_coefficients(b, a)
        # ...then the post-chain effects, in rack order.
        self.engine.set_effects(self._collect_effects())

        # Plots: throttled (start the one-shot timer if it isn't already
        # pending, so a burst of drag events collapses to one redraw per tick).
        if not self._plot_timer.isActive():
            self._plot_timer.start()

    def _collect_effects(self) -> list[dict]:
        """Build the ordered post-chain effect list for the audio engine."""
        effects: list[dict] = []
        for bl in self.blocks:
            if bl.spec.effect == "distort":
                effects.append({"kind": "distort", "a": bl.params["a"]})
            elif bl.spec.effect == "delay":
                effects.append(
                    {
                        "kind": "delay",
                        "id": bl.id,
                        "T": bl.params["T"],
                        "g": bl.params["g"],
                    }
                )
        return effects

    def _update_plots(self):
        num, den = self._num, self._den
        # Delay/Echo blocks are linear -- fold their comb factors into the
        # displayed response.  (T in seconds for e^{-sT}.)
        delays = [
            (b.params["T"] / 1000.0, b.params["g"])
            for b in self.blocks
            if b.spec.effect == "delay"
        ]
        distortions = [b.params["a"] for b in self.blocks if b.spec.effect == "distort"]
        # More points so the comb teeth resolve; delays make the response wig.
        f, mag_db, _phase = bode(num, den, delays=delays, n=1400)
        self.analysis.update_bode(f, mag_db)
        self.tf_readout.update_tf(num, den, delays, distortions)

    # ---------------------------------------------------------- transport --

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open a song",
            "",
            "Audio / video (*.mp4 *.m4a *.mp3 *.wav *.flac *.ogg *.aac *.mov);;All files (*)",
        )
        if not path:
            return
        self.setCursor(Qt.WaitCursor)
        try:
            data, sr = load_audio(path, target_sr=self.sr)
        except (AudioLoadError, Exception) as exc:  # noqa: BLE001 - show any decode error
            self.unsetCursor()
            QMessageBox.critical(self, "Could not load audio", str(exc))
            return
        self.unsetCursor()
        self.engine.load(data, sr)
        self.song_label.setText(path.replace("\\", "/").split("/")[-1])
        self.play_btn.setEnabled(True)
        self.play_btn.setText("▶  Play")

    def _toggle_play(self):
        if self.engine.playing:
            self.engine.pause()
            self.play_btn.setText("▶  Play")
        else:
            self.engine.play()
            self.play_btn.setText("⏸  Pause")

    def _on_bypass(self, on: bool):
        self.engine.set_bypass(on)
        self.bypass_btn.setText("Bypassed — dry" if on else "Bypass")

    def _end_seek(self):
        self.engine.seek_fraction(self.pos_slider.value() / 1000.0)
        self._seeking = False

    def _on_tick(self):
        # LEGO inputs are read every tick (they can move knobs while paused).
        self.lego_panel.tick()

        playing = self.engine.playing
        # Only animate the spectrum while audio is actually flowing -- when
        # paused the picture is static, so there's nothing to redraw.
        if playing:
            freqs, in_db, out_db = self.engine.spectra()
            self.analysis.update_fft(freqs, in_db, out_db)
            cur, dur = self.engine.position()
            if dur > 0 and not self._seeking:
                self.pos_slider.blockSignals(True)
                self.pos_slider.setValue(int(1000 * cur / dur))
                self.pos_slider.blockSignals(False)
            self.time_label.setText(f"{self._fmt_time(cur)} / {self._fmt_time(dur)}")
        # reflect track-ended
        if not playing and self.play_btn.text().startswith("⏸"):
            self.play_btn.setText("▶  Play")

    @staticmethod
    def _fmt_time(sec: float) -> str:
        sec = int(sec)
        return f"{sec // 60}:{sec % 60:02d}"

    def closeEvent(self, e):
        self._timer.stop()
        self.lego_panel.manager.disconnect_all()
        self.engine.close()
        super().closeEvent(e)
