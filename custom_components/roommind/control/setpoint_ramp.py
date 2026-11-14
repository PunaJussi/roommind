"""Fine-tune of an AC thermostat setpoint from the room sensor.

The heat pump's own thermostat runs the compressor. Its sensor sits inside the
indoor unit, so it only roughly tracks the room, and that gap follows the
outdoor temperature. RoomMind nudges the setpoint the user left on the unit,
at most one step per interval, until the room sensor is at the target.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from ..const import (
    MODE_COOLING,
    MODE_HEATING,
    MODE_IDLE,
    SETPOINT_RAMP_DEADBAND_DEFAULT,
    SETPOINT_RAMP_MINUTES_MAX,
    SETPOINT_RAMP_MINUTES_MIN,
    SETPOINT_RAMP_MODE_DEFAULT,
    SETPOINT_RAMP_MODES,
    SETPOINT_RAMP_STEP_DEFAULT,
    SETPOINT_RAMP_STEP_MAX,
    SETPOINT_RAMP_STEP_MIN,
)
from ..utils.device_utils import DEVICE_TYPE_AC, SETPOINT_MODE_DIRECT

_MODES = frozenset({MODE_HEATING, MODE_COOLING})


class RampConfig(NamedTuple):
    """Interval, fixed-step size, mode, and delta deadband for a ramped AC."""

    minutes: int
    step: float
    mode: str = SETPOINT_RAMP_MODE_DEFAULT
    deadband: float = SETPOINT_RAMP_DEADBAND_DEFAULT


def _clamp_delta(raw: Any, default: float) -> float:
    """Clamp a °C delta to the gradual-thermostat step range."""
    try:
        value = float(default if raw in (None, "") else raw)
    except (TypeError, ValueError):
        value = default
    if value != value:  # NaN
        value = default
    return min(SETPOINT_RAMP_STEP_MAX, max(SETPOINT_RAMP_STEP_MIN, value))


def ramp_config(device: dict | None) -> RampConfig | None:
    """Return ramp settings for a ramped AC, else None.

    Only a proportional climate device with a positive interval is ramped.
    A TRV keeps its immediate boost, and a direct device keeps the room target.
    """
    if not device or device.get("type") != DEVICE_TYPE_AC:
        return None
    if device.get("setpoint_mode") == SETPOINT_MODE_DIRECT:
        return None
    try:
        minutes = int(device.get("setpoint_ramp_minutes") or 0)
    except (TypeError, ValueError):
        return None
    if minutes <= 0:
        return None
    minutes = min(SETPOINT_RAMP_MINUTES_MAX, max(SETPOINT_RAMP_MINUTES_MIN, minutes))
    step = _clamp_delta(device.get("setpoint_ramp_step"), SETPOINT_RAMP_STEP_DEFAULT)
    mode = device.get("setpoint_ramp_mode") or SETPOINT_RAMP_MODE_DEFAULT
    if mode not in SETPOINT_RAMP_MODES:
        mode = SETPOINT_RAMP_MODE_DEFAULT
    deadband = _clamp_delta(device.get("setpoint_ramp_deadband"), SETPOINT_RAMP_DEADBAND_DEFAULT)
    return RampConfig(minutes, step, mode, deadband)


def ramped_display_eid(
    mode: str,
    devices: list[dict],
    *,
    heat_source_plan: Any = None,
    direct_eids: set[str] | None = None,
) -> str | None:
    """Entity whose ramped setpoint is the one number the room can show.

    A single AC-only room, or the orchestrated plan's first active AC. Mixed
    rooms keep the existing combined figure.
    """
    direct = direct_eids or set()
    if heat_source_plan is not None:
        active = [cmd for cmd in heat_source_plan.commands if cmd.active]
        if not active or getattr(active[0], "device_type", None) != DEVICE_TYPE_AC:
            return None
        eid = active[0].entity_id
        return None if eid in direct else eid
    acs = [d["entity_id"] for d in devices if d.get("type") == DEVICE_TYPE_AC and d.get("entity_id")]
    if mode == MODE_COOLING:
        relevant = acs
    elif mode in (MODE_HEATING, MODE_IDLE):
        if any(d.get("type") != DEVICE_TYPE_AC and d.get("entity_id") for d in devices):
            return None
        relevant = [eid for eid in acs if eid not in direct]
    else:
        return None
    if len(relevant) != 1:
        return None
    return relevant[0]


def _move_toward(current: float, desired: float, step: float) -> float:
    """Move ``current`` toward ``desired`` by at most ``step``, on a 0.1 °C grid."""
    delta = desired - current
    if abs(delta) <= step + 1e-9:
        return round(desired, 1)
    moved = round(current + (step if delta > 0 else -step), 1)
    if moved == round(current, 1) and abs(desired - current) > 0.05:
        moved = round(current + (0.1 if delta > 0 else -0.1), 1)
    return moved


class SetpointRamp:
    """Last setpoint sent to each ramped AC, and when."""

    def __init__(self) -> None:
        # entity_id -> [setpoint_c, updated_unix, mode]
        self._records: dict[str, list] = {}
        self.dirty = False

    def advance(
        self,
        entity_id: str,
        mode: str,
        now: float,
        *,
        minutes: int,
        step: float,
        direction: int,
        seed: float | None,
        device_step: float | None = None,
        desired: float | None = None,
    ) -> float | None:
        """Setpoint to send now, at most one stride from the last one.

        ``direction`` is +1 to raise the setpoint, -1 to lower it, and 0 to
        keep it. ``desired`` is the value to move toward; without it a step
        is taken in ``direction``. A change between heating and cooling keeps
        the last value: the user switched the unit, and the next step leaves
        from there. With no history, ``seed`` (the unit's current thermostat
        reading) is the start, and a non-zero direction takes the first step
        at once.
        """
        stride = step
        if device_step is not None and device_step > stride:
            stride = device_step

        def _goal(current: float) -> float:
            if desired is not None:
                return desired
            return current + direction * (stride + 1.0)

        record = self._records.get(entity_id)
        if record is None:
            if seed is None:
                return None
            sent = seed if direction == 0 else _move_toward(seed, _goal(seed), stride)
            self._store(entity_id, sent, now, mode)
            return sent
        if record[2] != mode:
            record[2] = mode
            self.dirty = True
        if direction == 0 or now - float(record[1]) < minutes * 60:
            return float(record[0])
        current = float(record[0])
        sent = _move_toward(current, _goal(current), stride)
        self._store(entity_id, sent, now, mode)
        return sent

    def note(self, entity_id: str, setpoint: float, mode: str, now: float) -> None:
        """Remember a setpoint sent by another path (a hold that eased the unit off)."""
        if mode not in _MODES:
            return
        self._store(entity_id, round(setpoint, 1), now, mode)

    def clear(self, entity_id: str) -> None:
        """Forget a trim that was stopped, so the next one starts from the unit's thermostat."""
        if self._records.pop(entity_id, None) is not None:
            self.dirty = True

    def setpoint(self, entity_id: str) -> float | None:
        """Last ramped setpoint in °C, or None when this device has no run in progress."""
        record = self._records.get(entity_id)
        return None if record is None else float(record[0])

    def mode(self, entity_id: str) -> str | None:
        """Last heating/cooling intent stored for this device, or None."""
        record = self._records.get(entity_id)
        return None if record is None else str(record[2])

    def prune(self, known_eids: set[str]) -> None:
        """Drop ramps of devices that are no longer configured anywhere."""
        stale = [eid for eid in self._records if eid not in known_eids]
        for eid in stale:
            del self._records[eid]
        if stale:
            self.dirty = True

    def get_state(self) -> dict:
        """Persistable state. Timestamps are wall-clock so a restart keeps the interval."""
        return {
            eid: {"setpoint": record[0], "updated": record[1], "mode": record[2]}
            for eid, record in self._records.items()
        }

    def load_state(self, data: dict) -> None:
        """Restore persisted ramps, skipping malformed entries."""
        self._records = {}
        for eid, entry in (data or {}).items():
            if not isinstance(entry, dict):
                continue
            mode = entry.get("mode")
            if mode not in _MODES:
                continue
            try:
                setpoint = round(float(entry["setpoint"]), 1)
                updated = float(entry["updated"])
            except (KeyError, TypeError, ValueError):
                continue
            self._records[eid] = [setpoint, updated, mode]
        self.dirty = False

    def _store(self, entity_id: str, setpoint: float, now: float, mode: str) -> None:
        self._records[entity_id] = [round(setpoint, 1), now, mode]
        self.dirty = True
