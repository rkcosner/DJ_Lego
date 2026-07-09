"""Custom widgets: a float/log slider, a draggable palette button, and a
drag-to-reorder rack that also accepts blocks dropped from the palette.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal, QMimeData, QPoint
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QSlider,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QListWidget,
    QAbstractItemView,
)

from ..dsp.blocks import ParamSpec
from . import theme

# Custom MIME type carrying a block *type* string when dragging from palette.
BLOCK_MIME = "application/x-djlego-block"

_STEPS = 1000  # slider integer resolution


def unit_to_value(spec: ParamSpec, t: float) -> float:
    """Map a normalized ``t`` in [0, 1] to a knob value (log or linear).

    Shared by the slider and by external drivers (e.g. LEGO motors) so a motor
    at 30% of its travel lands a knob exactly where dragging the slider to 30%
    would -- consistent for every input.
    """
    t = float(np.clip(t, 0.0, 1.0))
    if spec.log:
        lo, hi = np.log10(spec.minv), np.log10(spec.maxv)
        return float(10 ** (lo + t * (hi - lo)))
    return float(spec.minv + t * (spec.maxv - spec.minv))


def value_to_unit(spec: ParamSpec, value: float) -> float:
    """Inverse of :func:`unit_to_value`: knob value -> normalized [0, 1]."""
    if spec.log:
        lo, hi = np.log10(spec.minv), np.log10(spec.maxv)
        t = (np.log10(max(value, spec.minv)) - lo) / (hi - lo)
    else:
        t = (value - spec.minv) / (spec.maxv - spec.minv)
    return float(np.clip(t, 0.0, 1.0))


class FloatSlider(QWidget):
    """A labelled slider mapping an integer track to a float (linear or log)."""

    valueChangedFloat = Signal(float)

    def __init__(self, spec: ParamSpec):
        super().__init__()
        self.spec = spec
        self._log = spec.log

        self.name = QLabel(spec.label)
        self.value_label = QLabel()
        self.value_label.setObjectName("dim")
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, _STEPS)
        self.slider.valueChanged.connect(self._on_slider)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.name)
        top.addStretch(1)
        top.addWidget(self.value_label)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        lay.addLayout(top)
        lay.addWidget(self.slider)

        self.set_value(spec.default)

    # -- mapping between slider position and float value --------------------

    def _pos_to_value(self, pos: int) -> float:
        return unit_to_value(self.spec, pos / _STEPS)

    def _value_to_pos(self, value: float) -> int:
        return int(round(value_to_unit(self.spec, value) * _STEPS))

    def value(self) -> float:
        return self._pos_to_value(self.slider.value())

    def set_value(self, value: float):
        self.slider.blockSignals(True)
        self.slider.setValue(self._value_to_pos(value))
        self.slider.blockSignals(False)
        self._refresh_label(value)

    def _refresh_label(self, value: float):
        unit = f" {self.spec.unit}" if self.spec.unit else ""
        if self.spec.unit == "Hz" and value >= 1000:
            txt = f"{value/1000:.2f} kHz"
        elif abs(value - round(value)) < 1e-9:
            txt = f"{int(round(value))}{unit}"
        else:
            txt = f"{value:.3g}{unit}"
        self.value_label.setText(txt)

    def _on_slider(self, pos: int):
        v = self._pos_to_value(pos)
        self._refresh_label(v)
        self.valueChangedFloat.emit(v)


class DraggableButton(QPushButton):
    """Palette button: click to append the block, or drag it onto the rack."""

    def __init__(self, block_type: str, text: str):
        super().__init__(text)
        self.block_type = block_type
        self._press_pos: QPoint | None = None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_pos = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press_pos is None or not (e.buttons() & Qt.LeftButton):
            return
        if (e.position().toPoint() - self._press_pos).manhattanLength() < 12:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(BLOCK_MIME, self.block_type.encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)
        self._press_pos = None


class RackList(QListWidget):
    """The signal chain: drag items to reorder, drop palette blocks to add."""

    reordered = Signal()
    addRequested = Signal(str, int)  # (block_type, insert_row)
    removeRequested = Signal(str)  # block id

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAcceptDrops(True)
        self.setSpacing(0)

    # accept palette drags in addition to internal reorders
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(BLOCK_MIME) or e.source() is self:
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(BLOCK_MIME) or e.source() is self:
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasFormat(BLOCK_MIME) and e.source() is not self:
            btype = bytes(e.mimeData().data(BLOCK_MIME)).decode("utf-8")
            row = self.indexAt(e.position().toPoint()).row()
            if row < 0:
                row = self.count()
            self.addRequested.emit(btype, row)
            e.acceptProposedAction()
        else:
            super().dropEvent(e)
            self.reordered.emit()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            item = self.currentItem()
            if item is not None:
                self.removeRequested.emit(item.data(Qt.UserRole))
                return
        super().keyPressEvent(e)
