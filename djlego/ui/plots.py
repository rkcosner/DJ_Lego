"""The analysis panel: the transfer-function magnitude (Bode) stacked directly
above the live input/output spectrum, sharing one frequency x-axis.

Putting them on the *same* log-frequency axis is the whole point -- the filter's
gain curve sits right on top of the spectrum it is shaping, so you can read off
exactly how the chain reshapes the music.  (Phase is intentionally omitted: it
isn't audible here, and dropping it lets the magnitude line up with the FFT.)

Both the Bode curve and the two FFT curves are drawn with **blitting** -- only
the line artists are redrawn each frame, not the whole figure -- so the 30 fps
spectrum stays smooth even on a software renderer.
"""

from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from . import theme

F_MIN, F_MAX = 20.0, 20000.0


def _style_ax(ax):
    ax.set_facecolor(theme.PANEL)
    for spine in ax.spines.values():
        spine.set_color(theme.LINE)
    ax.tick_params(colors=theme.TEXT_DIM, labelsize=8)
    ax.grid(True, which="both", color=theme.LINE, linewidth=0.5, alpha=0.7)
    ax.xaxis.label.set_color(theme.TEXT_DIM)
    ax.yaxis.label.set_color(theme.TEXT_DIM)


class AnalysisCanvas(FigureCanvasQTAgg):
    """Magnitude Bode (top) + live spectrum (bottom) on a shared x-axis."""

    def __init__(self):
        fig = Figure(figsize=(4, 5), facecolor=theme.PANEL)
        super().__init__(fig)
        self.ax_mag = fig.add_subplot(2, 1, 1)
        self.ax_fft = fig.add_subplot(2, 1, 2, sharex=self.ax_mag)
        # Identical horizontal margins guarantee the two plot boxes line up.
        fig.subplots_adjust(left=0.13, right=0.97, top=0.93, bottom=0.1, hspace=0.28)

        for ax in (self.ax_mag, self.ax_fft):
            _style_ax(ax)
            ax.set_xscale("log")
            ax.set_xlim(F_MIN, F_MAX)

        self.ax_mag.set_title(
            "Transfer function — |H(jw)|", color=theme.TEXT, fontsize=10, loc="left"
        )
        self.ax_mag.set_ylabel("gain (dB)")
        self.ax_mag.set_ylim(-60, 20)
        self.ax_mag.axhline(0, color=theme.TEXT_DIM, lw=0.7, alpha=0.5)
        # Shared axis: hide the top plot's x tick labels, label only the bottom.
        for lbl in self.ax_mag.get_xticklabels():
            lbl.set_visible(False)

        self.ax_fft.set_title(
            "Live spectrum — input vs output", color=theme.TEXT, fontsize=10, loc="left"
        )
        self.ax_fft.set_ylabel("level (dB)")
        self.ax_fft.set_xlabel("frequency (Hz)")
        self.ax_fft.set_ylim(-80, 0)

        (self._mag_line,) = self.ax_mag.plot([], [], color=theme.MAG, lw=2, animated=True)
        (self._in_line,) = self.ax_fft.plot(
            [], [], color=theme.INPUT, lw=1.2, alpha=0.8, label="input", animated=True
        )
        (self._out_line,) = self.ax_fft.plot(
            [], [], color=theme.ACCENT, lw=1.4, label="output", animated=True
        )
        leg = self.ax_fft.legend(
            loc="upper right", fontsize=8, framealpha=0.0, labelcolor=theme.TEXT
        )
        for txt in leg.get_texts():
            txt.set_color(theme.TEXT)

        self._bg = None
        self.mpl_connect("draw_event", self._on_draw)

    # -- blitting helpers ----------------------------------------------------

    def _on_draw(self, _event):
        self._bg = self.copy_from_bbox(self.figure.bbox)
        self._draw_lines()

    def _draw_lines(self):
        self.ax_mag.draw_artist(self._mag_line)
        self.ax_fft.draw_artist(self._in_line)
        self.ax_fft.draw_artist(self._out_line)

    def _blit(self):
        if self._bg is None:
            self.draw()
            return
        self.restore_region(self._bg)
        self._draw_lines()
        self.blit(self.figure.bbox)

    # -- updates -------------------------------------------------------------

    def update_bode(self, f, mag_db):
        self._mag_line.set_data(f, mag_db)
        # Expand the magnitude y-limits only when the curve runs off-view; a
        # limit change alters the ticks, so it needs a full redraw + recapture.
        lo, hi = float(np.min(mag_db)) - 6, float(np.max(mag_db)) + 6
        cur_lo, cur_hi = self.ax_mag.get_ylim()
        if self._bg is None or lo < cur_lo or hi > cur_hi:
            self.ax_mag.set_ylim(min(lo, cur_lo), max(hi, cur_hi))
            self.draw()
        else:
            self._blit()

    def update_fft(self, freqs, in_db, out_db):
        # Skip the DC bin (freqs[0] == 0) so the log axis is happy.
        self._in_line.set_data(freqs[1:], in_db[1:])
        self._out_line.set_data(freqs[1:], out_db[1:])
        self._blit()
