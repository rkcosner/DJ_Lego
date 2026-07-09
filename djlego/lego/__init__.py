"""Optional LEGO Education hardware control for the DJ booth.

Lets students drive the knobs with LEGO motors and controllers from the
Computer Science & AI kits (the ``legoeducation`` PyPI package, over BLE).
Everything here is optional and import-guarded: if the package isn't installed
(or there's no hardware), the app runs exactly as before.
"""

from .manager import (
    LegoManager,
    LEGO_AVAILABLE,
    CARD_COLORS,
    DEVICE_KINDS,
    ConnectedDevice,
    normalize_position,
    normalize_percent,
)

__all__ = [
    "LegoManager",
    "LEGO_AVAILABLE",
    "CARD_COLORS",
    "DEVICE_KINDS",
    "ConnectedDevice",
    "normalize_position",
    "normalize_percent",
]
