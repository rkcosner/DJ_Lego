"""Connect to LEGO Education devices and read their inputs as [0, 1] values.

The ``legoeducation`` package (https://github.com/LEGO/LEGOEducation) talks to
the Computer Science & AI kit hardware over Bluetooth.  We wrap it so the rest
of the app only ever sees **normalized [0, 1] input channels**, whatever the
device:

* Single motor  -> one channel from ``motor.position``
* Double motor  -> two channels: ``motor[MOTOR_LEFT|MOTOR_RIGHT].position``
* Controller    -> two channels: ``sensor.leftPercent / rightPercent``

Normalization (the package doesn't document exact ranges, so these are the
documented assumptions -- adjust the two functions below if your hardware
differs):

* motor **position** is in degrees; ``(deg mod 360) / 360`` -> one full turn
  sweeps the knob from 0 to 1 and then wraps (an endless-encoder feel).
* controller **percent** is a bidirectional lever ``-100..+100``;
  ``(pct + 100) / 200`` puts the lever's centre at 0.5.

A ``simulate=True`` connection creates a **mock** device (a slow sine) so the
whole mapping UI works with no package and no hardware -- handy for demos, and
what the tests exercise.
"""

from __future__ import annotations

import math
import time
import threading
from dataclasses import dataclass, field

try:  # the hardware package is an optional extra
    import legoeducation as le

    LEGO_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import failure means "no hardware layer"
    le = None
    LEGO_AVAILABLE = False


# (display name, legoeducation constant) — constants only resolved if installed.
def _color(name: str, const_name: str):
    return (name, getattr(le, const_name, const_name) if LEGO_AVAILABLE else const_name)


CARD_COLORS = [
    _color("Green", "LEGO_COLOR_GREEN"),
    _color("Blue", "LEGO_COLOR_BLUE"),
    _color("Red", "LEGO_COLOR_RED"),
    _color("Orange", "LEGO_COLOR_ORANGE"),
    _color("Yellow", "LEGO_COLOR_YELLOW"),
    _color("Azure", "LEGO_COLOR_AZURE"),
    _color("Purple", "LEGO_COLOR_PURPLE"),
    _color("Magenta", "LEGO_COLOR_MAGENTA"),
]

# (display name, internal kind)
DEVICE_KINDS = [
    ("Single motor", "single"),
    ("Double motor", "double"),
    ("Controller", "controller"),
]


# --- normalization ----------------------------------------------------------


def normalize_position(deg: float) -> float:
    """Motor angle (degrees) -> [0, 1); one full turn sweeps 0->1 then wraps."""
    return (float(deg) % 360.0) / 360.0


def normalize_percent(pct: float) -> float:
    """Controller lever percent (-100..+100) -> [0, 1], centre at 0.5."""
    return min(1.0, max(0.0, (float(pct) + 100.0) / 200.0))


# --- mock hardware (for Simulate mode / tests) ------------------------------


class _MockMotor:
    def __init__(self, phase: float):
        self._phase = phase

    @property
    def position(self) -> float:
        # A slow sweep through the full 0..360 range.
        return (math.sin(time.time() * 0.5 + self._phase) * 0.5 + 0.5) * 360.0


class _MockSensor:
    @property
    def leftPercent(self) -> float:
        return math.sin(time.time() * 0.6) * 100.0

    @property
    def rightPercent(self) -> float:
        return math.cos(time.time() * 0.4) * 100.0


class MockDevice:
    """Stands in for a ``legoeducation`` device with synthetic moving values."""

    def __init__(self, kind: str):
        self.kind = kind
        self.motor = {0: _MockMotor(0.0), 1: _MockMotor(1.5)}
        # A single motor is read as ``.motor.position`` (not indexed), so give
        # the mapping a direct attribute too.
        self.motor_single = _MockMotor(0.0)
        self.sensor = _MockSensor()

    def disconnect(self):
        pass


# --- connected device -------------------------------------------------------

# channel key -> (human label, reader-kind)
_CHANNELS = {
    "single": [("motor", "motor.position")],
    "double": [("left", "left motor"), ("right", "right motor")],
    "controller": [("left", "left lever"), ("right", "right lever")],
}


@dataclass
class ConnectedDevice:
    key: str  # unique id, e.g. "single:Azure:3683"
    kind: str  # single | double | controller
    color_name: str
    serial: str
    obj: object  # the legoeducation device or a MockDevice
    simulated: bool = False

    def channels(self) -> list[tuple[str, str]]:
        """Return ``(channel_key, label)`` pairs this device exposes."""
        return _CHANNELS[self.kind]

    def read(self, channel: str) -> float | None:
        """Read one channel as a normalized [0, 1] value (or None if unread)."""
        try:
            if self.kind == "single":
                src = self.obj.motor_single if self.simulated else self.obj.motor
                return normalize_position(src.position)
            if self.kind == "double":
                idx = _motor_index(channel)
                sign_change = 1 * (idx==1) - 1 * (idx==0) # to make motor turns change knobs in the same direction
                return normalize_position(360 * (idx==1) + sign_change * self.obj.motor[idx].position)
            if self.kind == "controller":
                attr = "leftPercent" if channel == "left" else "rightPercent"
                return normalize_percent(getattr(self.obj.sensor, attr))
        except Exception:  # noqa: BLE001 - value not available yet / disconnected
            return None
        return None


def _motor_index(channel: str) -> int:
    if LEGO_AVAILABLE:
        return le.MOTOR_LEFT if channel == "left" else le.MOTOR_RIGHT
    return 0 if channel == "left" else 1  # mock uses 0/1


# --- manager ----------------------------------------------------------------


@dataclass
class LegoManager:
    """Owns connected devices and connects to new ones (off the UI thread)."""

    devices: dict[str, ConnectedDevice] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _events: list[tuple[str, str]] = field(default_factory=list)  # (kind, detail)

    # -- events (drained by the UI so it can react on the main thread) -------

    def pop_events(self) -> list[tuple[str, str]]:
        with self._lock:
            ev, self._events = self._events, []
            return ev

    def _emit(self, kind: str, detail: str):
        with self._lock:
            self._events.append((kind, detail))

    # -- connecting ----------------------------------------------------------

    def connect(self, kind: str, color_name: str, color_const, serial: str, simulate: bool):
        """Start connecting a device.  Real connections run on a worker thread
        (BLE scanning blocks); simulated ones are instant."""
        key = f"{kind}:{color_name}:{serial or 'sim'}"
        if simulate or not LEGO_AVAILABLE:
            dev = ConnectedDevice(key, kind, color_name, serial,
                                  MockDevice(kind), simulated=True)
            with self._lock:
                self.devices[key] = dev
            self._emit("connected", key)
            return

        def _worker():
            try:
                ctor = {
                    "single": le.SingleMotor,
                    "double": le.DoubleMotor,
                    "controller": le.Controller,
                }[kind]
                obj = ctor()
                obj.connect(card_color=color_const, card_serial=str(serial))
                dev = ConnectedDevice(key, kind, color_name, serial, obj)
                with self._lock:
                    self.devices[key] = dev
                self._emit("connected", key)
            except Exception as exc:  # noqa: BLE001
                self._emit("error", f"{key}: {exc}")

        threading.Thread(target=_worker, daemon=True).start()

    def disconnect(self, key: str):
        with self._lock:
            dev = self.devices.pop(key, None)
        if dev is not None:
            try:
                dev.obj.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._emit("disconnected", key)

    def disconnect_all(self):
        for key in list(self.devices):
            self.disconnect(key)

    def snapshot(self) -> list[ConnectedDevice]:
        with self._lock:
            return list(self.devices.values())
