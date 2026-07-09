"""The "LEGO control" panel: connect devices and map their inputs to knobs.

The panel is deliberately self-contained -- it talks to the rest of the app
through two callbacks passed in by the main window:

* ``knob_provider()``  -> list of ``(knob_id, label)`` for every tunable knob
  currently in the rack (plus feedback/effect params);
* ``knob_setter(knob_id, t)`` -> drive that knob to normalized position ``t``.

Each connected device contributes one or two **channels** (motor position,
lever percent).  Every channel gets a live 0-100% bar and a dropdown to pick
which knob it drives.  On each ``tick()`` the panel reads the channels and, for
any that are mapped, pushes the value to the knob.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QComboBox,
    QLineEdit,
    QCheckBox,
    QProgressBar,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFrame,
)

from ..lego import LegoManager, LEGO_AVAILABLE, CARD_COLORS, DEVICE_KINDS
from . import theme

NONE_LABEL = "— not mapped —"


class LegoPanel(QWidget):
    def __init__(self, knob_provider, knob_setter):
        super().__init__()
        self._knobs = knob_provider
        self._set_knob = knob_setter
        self.manager = LegoManager()

        # (device_key, channel) -> knob_id currently mapped
        self.mappings: dict[tuple[str, str], str] = {}
        # (device_key, channel) -> widgets {"bar", "pct", "combo"}
        self._rows: dict[tuple[str, str], dict] = {}

        self._build()

    # ----------------------------------------------------------------- UI --

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        title = QLabel("LEGO control")
        title.setObjectName("h1")
        lay.addWidget(title)

        if not LEGO_AVAILABLE:
            hint = QLabel(
                "Package not installed — use Simulate, or run "
                "<b>pip install legoeducation</b> for real hardware."
            )
        else:
            hint = QLabel("Pick your card color + serial, attach a device, map it to a knob.")
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # --- connect controls (kind, color, serial, simulate, button) ------
        form = QGridLayout()
        form.setHorizontalSpacing(6)
        form.setVerticalSpacing(4)

        self.kind_combo = QComboBox()
        for name, kind in DEVICE_KINDS:
            self.kind_combo.addItem(name, kind)

        self.color_combo = QComboBox()
        for name, const in CARD_COLORS:
            self.color_combo.addItem(name, (name, const))

        self.serial_edit = QLineEdit()
        self.serial_edit.setPlaceholderText("card serial, e.g. 3683")

        form.addWidget(QLabel("device"), 0, 0)
        form.addWidget(self.kind_combo, 0, 1)
        form.addWidget(QLabel("card"), 1, 0)
        form.addWidget(self.color_combo, 1, 1)
        form.addWidget(QLabel("serial"), 2, 0)
        form.addWidget(self.serial_edit, 2, 1)
        lay.addLayout(form)

        row = QHBoxLayout()
        self.simulate_check = QCheckBox("Simulate (no hardware)")
        if not LEGO_AVAILABLE:
            self.simulate_check.setChecked(True)
            self.simulate_check.setEnabled(False)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("accent")
        self.connect_btn.clicked.connect(self._on_connect)
        row.addWidget(self.simulate_check)
        row.addStretch(1)
        row.addWidget(self.connect_btn)
        lay.addLayout(row)

        self.status = QLabel("")
        self.status.setObjectName("dim")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {theme.LINE};")
        lay.addWidget(line)

        # --- connected devices + their channel rows ------------------------
        self.devices_box = QVBoxLayout()
        self.devices_box.setSpacing(6)
        lay.addLayout(self.devices_box)
        self._empty = QLabel("No devices connected.")
        self._empty.setObjectName("dim")
        self.devices_box.addWidget(self._empty)

        lay.addStretch(1)

    # ------------------------------------------------------------- connect --

    def _on_connect(self):
        kind = self.kind_combo.currentData()
        color_name, color_const = self.color_combo.currentData()
        serial = self.serial_edit.text().strip()
        simulate = self.simulate_check.isChecked()
        if not simulate and not serial:
            self.status.setText("Enter the card serial (or tick Simulate).")
            return
        self.status.setText("Connecting…" if not simulate else "Simulating…")
        self.connect_btn.setEnabled(False)  # re-enabled by tick() once resolved
        self.manager.connect(kind, color_name, color_const, serial, simulate)

    # -------------------------------------------------------- device rows --

    def _rebuild_devices(self):
        # Clear the layout.
        while self.devices_box.count():
            item = self.devices_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self._rows.clear()

        devices = self.manager.snapshot()
        if not devices:
            self._empty = QLabel("No devices connected.")
            self._empty.setObjectName("dim")
            self.devices_box.addWidget(self._empty)
            return

        for dev in devices:
            head = QHBoxLayout()
            tag = "sim" if dev.simulated else f"{dev.color_name}/{dev.serial}"
            name = dict(DEVICE_KINDS).get(dev.kind, dev.kind)
            dlabel = QLabel(f"● {name}  ·  {tag}")
            drop = QPushButton("✕")
            drop.setFixedWidth(28)
            drop.clicked.connect(lambda _=False, k=dev.key: self._disconnect(k))
            head.addWidget(dlabel, 1)
            head.addWidget(drop)
            self.devices_box.addLayout(head)

            for chan, clabel in dev.channels():
                self.devices_box.addLayout(self._make_channel_row(dev.key, chan, clabel))

    def _make_channel_row(self, key: str, chan: str, clabel: str) -> QHBoxLayout:
        row = QHBoxLayout()
        name = QLabel(clabel)
        name.setFixedWidth(74)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setTextVisible(True)
        bar.setFixedWidth(90)
        combo = QComboBox()
        self._populate_combo(combo, self.mappings.get((key, chan)))
        combo.currentIndexChanged.connect(
            lambda _=0, k=key, c=chan, cb=combo: self._on_map_changed(k, c, cb)
        )
        row.addWidget(name)
        row.addWidget(bar)
        row.addWidget(combo, 1)
        self._rows[(key, chan)] = {"bar": bar, "combo": combo}
        return row

    def _populate_combo(self, combo: QComboBox, selected_id):
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(NONE_LABEL, None)
        idx_sel = 0
        for i, (knob_id, label) in enumerate(self._knobs(), start=1):
            combo.addItem(label, knob_id)
            if knob_id == selected_id:
                idx_sel = i
        combo.setCurrentIndex(idx_sel)
        combo.blockSignals(False)

    def _on_map_changed(self, key: str, chan: str, combo: QComboBox):
        knob_id = combo.currentData()
        if knob_id is None:
            self.mappings.pop((key, chan), None)
            return
        # One input per knob: if another channel already drives this knob, take
        # it away from that channel (reset its dropdown to "not mapped").
        for other in [kc for kc, kid in self.mappings.items()
                      if kid == knob_id and kc != (key, chan)]:
            self.mappings.pop(other, None)
            w = self._rows.get(other)
            if w is not None:
                c = w["combo"]
                c.blockSignals(True)
                c.setCurrentIndex(0)
                c.blockSignals(False)
        self.mappings[(key, chan)] = knob_id

    def _disconnect(self, key: str):
        # Drop any mappings for this device, then disconnect.
        for k in [k for k in self.mappings if k[0] == key]:
            self.mappings.pop(k, None)
        self.manager.disconnect(key)

    # ------------------------------------------------------------ updates --

    def refresh_knobs(self):
        """Re-populate every mapping dropdown (call when the rack changes)."""
        # Drop mappings whose knob no longer exists.
        valid = {kid for kid, _ in self._knobs()}
        for k in [k for k, v in self.mappings.items() if v not in valid]:
            self.mappings.pop(k, None)
        for (key, chan), w in self._rows.items():
            self._populate_combo(w["combo"], self.mappings.get((key, chan)))

    def tick(self):
        """Drain connection events, refresh live bars, and drive mapped knobs."""
        rebuilt = False
        for kind, detail in self.manager.pop_events():
            if kind == "connected":
                self.status.setText(f"Connected: {detail}")
                self._rebuild_devices()
                rebuilt = True
            elif kind == "disconnected":
                self.status.setText("Disconnected.")
                self._rebuild_devices()
                rebuilt = True
            elif kind == "error":
                self.status.setText(f"Connection failed — {detail}")
            elif kind == "busy":
                self.status.setText("That device is already connected/connecting.")
        # The Connect button is live only when nothing is mid-connect.
        self.connect_btn.setEnabled(not self.manager.busy())
        if rebuilt:
            return  # widgets just changed; read values next tick

        devices = {d.key: d for d in self.manager.snapshot()}
        for (key, chan), w in self._rows.items():
            dev = devices.get(key)
            if dev is None:
                continue
            t = dev.read(chan)
            if t is None:
                w["bar"].setFormat("—")
                continue
            w["bar"].setValue(int(round(t * 100)))
            w["bar"].setFormat("%p%")
            knob_id = self.mappings.get((key, chan))
            if knob_id is not None:
                self._set_knob(knob_id, t)
