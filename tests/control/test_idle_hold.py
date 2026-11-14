"""Never idle (hold), outdoor heat lock, and configurable setback offset."""

from __future__ import annotations

from unittest.mock import ANY, MagicMock

import pytest

from custom_components.roommind.const import MODE_COOLING, MODE_HEATING, MODE_IDLE, TargetTemps
from custom_components.roommind.control.mpc_controller import (
    async_idle_device,
    clear_command_cache,
)

from .conftest import build_hass


def _ac_state(hvac: str, *, temperature: float = 21.0, modes: list[str] | None = None) -> MagicMock:
    state = MagicMock()
    state.state = hvac
    state.attributes = {
        "hvac_modes": modes or ["heat", "cool", "fan_only", "off"],
        "min_temp": 5.0,
        "max_temp": 35.0,
        "temperature": temperature,
    }
    return state


def _states(*pairs: tuple[str, MagicMock]):
    table = dict(pairs)

    def _get(eid):
        return table.get(eid)

    return _get


@pytest.mark.asyncio
async def test_hold_keeps_heat_mode_without_touching_setpoint():
    """Never idle leaves heat on and does not rewrite the setpoint."""
    clear_command_cache()
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state("heat", temperature=23.0))
    devices = [{"entity_id": "climate.ac1", "type": "ac", "idle_action": "hold"}]
    await async_idle_device(
        hass, "climate.ac1", devices, area_id="living_room", targets=TargetTemps(heat=21.0, cool=24.0)
    )
    calls = hass.services.async_call.call_args_list
    assert [c for c in calls if c[0][1] == "set_hvac_mode"] == []
    assert [c for c in calls if c[0][1] == "set_temperature"] == []


@pytest.mark.asyncio
async def test_hold_from_fan_only_switches_to_heat():
    clear_command_cache()
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state("fan_only"))
    devices = [{"entity_id": "climate.ac1", "type": "ac", "idle_action": "hold"}]
    await async_idle_device(
        hass,
        "climate.ac1",
        devices,
        area_id="living_room",
        targets=TargetTemps(heat=21.0, cool=24.0),
        previous_mode=MODE_HEATING,
        apply_outdoor_lock=True,
    )
    calls = hass.services.async_call.call_args_list
    assert len(calls) == 1
    assert calls[0][0][1] == "set_hvac_mode"
    assert calls[0][0][2]["hvac_mode"] == "heat"


@pytest.mark.asyncio
async def test_hold_keeps_cool_mode_without_touching_setpoint():
    clear_command_cache()
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state("cool", temperature=22.0))
    devices = [{"entity_id": "climate.ac1", "type": "ac", "idle_action": "hold"}]
    await async_idle_device(
        hass, "climate.ac1", devices, area_id="living_room", targets=TargetTemps(heat=21.0, cool=24.0)
    )
    calls = hass.services.async_call.call_args_list
    assert [c for c in calls if c[0][1] == "set_temperature"] == []
    assert [c for c in calls if c[0][1] == "set_hvac_mode"] == []


@pytest.mark.asyncio
async def test_force_off_overrides_hold():
    clear_command_cache()
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state("heat"))
    devices = [{"entity_id": "climate.ac1", "type": "ac", "idle_action": "hold"}]
    await async_idle_device(hass, "climate.ac1", devices, area_id="living_room", force_off=True)
    hass.services.async_call.assert_called_with(
        "climate",
        "set_hvac_mode",
        {"entity_id": "climate.ac1", "hvac_mode": "off"},
        blocking=True,
        context=ANY,
    )


@pytest.mark.asyncio
async def test_setback_offset_heating():
    clear_command_cache()
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state("heat", temperature=21.0))
    devices = [{"entity_id": "climate.ac1", "type": "ac", "idle_action": "setback", "setback_offset": 1.0}]
    await async_idle_device(
        hass, "climate.ac1", devices, area_id="living_room", targets=TargetTemps(heat=21.0, cool=None)
    )
    temp = [c for c in hass.services.async_call.call_args_list if c[0][1] == "set_temperature"]
    assert temp[0][0][2]["temperature"] == 20.0


@pytest.mark.asyncio
async def test_setback_offset_cooling():
    clear_command_cache()
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state("cool", temperature=24.0))
    devices = [{"entity_id": "climate.ac1", "type": "ac", "idle_action": "setback", "setback_offset": 3.0}]
    await async_idle_device(
        hass, "climate.ac1", devices, area_id="living_room", targets=TargetTemps(heat=None, cool=24.0)
    )
    temp = [c for c in hass.services.async_call.call_args_list if c[0][1] == "set_temperature"]
    assert temp[0][0][2]["temperature"] == 27.0


def _outdoor_state(value: str) -> MagicMock:
    state = MagicMock()
    state.state = value
    state.attributes = {"unit_of_measurement": "°C"}
    return state


@pytest.mark.asyncio
async def test_outdoor_lock_overrides_fan_only_when_cold():
    clear_command_cache()
    hass = build_hass()
    ac = _ac_state("heat", temperature=19.0)
    hass.states.get = MagicMock(side_effect=_states(("climate.ac1", ac), ("sensor.out", _outdoor_state("-5"))))
    devices = [
        {
            "entity_id": "climate.ac1",
            "type": "ac",
            "idle_action": "fan_only",
            "idle_heat_outdoor_lock": True,
            "idle_heat_outdoor_sensor": "sensor.out",
            "idle_heat_outdoor_below": 0.0,
        }
    ]
    await async_idle_device(
        hass,
        "climate.ac1",
        devices,
        area_id="living_room",
        targets=TargetTemps(heat=21.0, cool=24.0),
        previous_mode=MODE_HEATING,
        apply_outdoor_lock=True,
    )
    hvac = [c for c in hass.services.async_call.call_args_list if c[0][1] == "set_hvac_mode"]
    assert all(c[0][2].get("hvac_mode") != "fan_only" for c in hvac)
    assert [c for c in hass.services.async_call.call_args_list if c[0][1] == "set_temperature"] == []


@pytest.mark.asyncio
async def test_outdoor_lock_unavailable_keeps_heat():
    clear_command_cache()
    hass = build_hass()
    ac = _ac_state("heat", temperature=19.0)
    hass.states.get = MagicMock(side_effect=_states(("climate.ac1", ac), ("sensor.out", _outdoor_state("unavailable"))))
    devices = [
        {
            "entity_id": "climate.ac1",
            "type": "ac",
            "idle_action": "fan_only",
            "idle_heat_outdoor_lock": True,
            "idle_heat_outdoor_sensor": "sensor.out",
            "idle_heat_outdoor_below": 0.0,
        }
    ]
    await async_idle_device(
        hass,
        "climate.ac1",
        devices,
        area_id="living_room",
        targets=TargetTemps(heat=21.0, cool=24.0),
        apply_outdoor_lock=True,
    )
    hvac = [c for c in hass.services.async_call.call_args_list if c[0][1] == "set_hvac_mode"]
    assert all(c[0][2].get("hvac_mode") != "fan_only" for c in hvac)


@pytest.mark.asyncio
async def test_outdoor_lock_hysteresis_and_release():
    clear_command_cache()
    hass = build_hass()
    ac = _ac_state("heat", temperature=21.0)
    devices = [
        {
            "entity_id": "climate.ac1",
            "type": "ac",
            "idle_action": "fan_only",
            "idle_fan_mode": "low",
            "idle_heat_outdoor_lock": True,
            "idle_heat_outdoor_sensor": "sensor.out",
            "idle_heat_outdoor_below": 0.0,
        }
    ]
    targets = TargetTemps(heat=21.0, cool=24.0)

    hass.states.get = MagicMock(side_effect=_states(("climate.ac1", ac), ("sensor.out", _outdoor_state("-2"))))
    await async_idle_device(
        hass,
        "climate.ac1",
        devices,
        area_id="lr",
        targets=targets,
        previous_mode=MODE_HEATING,
        apply_outdoor_lock=True,
    )
    assert all(c[0][2].get("hvac_mode") != "fan_only" for c in hass.services.async_call.call_args_list)

    hass.services.async_call.reset_mock()
    ac.state = "heat"
    hass.states.get = MagicMock(side_effect=_states(("climate.ac1", ac), ("sensor.out", _outdoor_state("0.5"))))
    await async_idle_device(
        hass,
        "climate.ac1",
        devices,
        area_id="lr",
        targets=targets,
        previous_mode=MODE_IDLE,
        apply_outdoor_lock=True,
    )
    assert all(c[0][2].get("hvac_mode") != "fan_only" for c in hass.services.async_call.call_args_list)

    hass.services.async_call.reset_mock()
    ac.state = "heat"
    hass.states.get = MagicMock(side_effect=_states(("climate.ac1", ac), ("sensor.out", _outdoor_state("2"))))
    await async_idle_device(
        hass,
        "climate.ac1",
        devices,
        area_id="lr",
        targets=targets,
        previous_mode=MODE_IDLE,
        apply_outdoor_lock=True,
    )
    hvac = [c for c in hass.services.async_call.call_args_list if c[0][1] == "set_hvac_mode"]
    assert any(c[0][2].get("hvac_mode") == "fan_only" for c in hvac)


@pytest.mark.asyncio
async def test_outdoor_lock_skips_cooling_idle():
    clear_command_cache()
    hass = build_hass()
    ac = _ac_state("cool", temperature=24.0)
    hass.states.get = MagicMock(side_effect=_states(("climate.ac1", ac), ("sensor.out", _outdoor_state("-5"))))
    devices = [
        {
            "entity_id": "climate.ac1",
            "type": "ac",
            "idle_action": "fan_only",
            "idle_fan_mode": "low",
            "idle_heat_outdoor_lock": True,
            "idle_heat_outdoor_sensor": "sensor.out",
            "idle_heat_outdoor_below": 0.0,
        }
    ]
    await async_idle_device(
        hass,
        "climate.ac1",
        devices,
        area_id="living_room",
        targets=TargetTemps(heat=21.0, cool=24.0),
        previous_mode=MODE_COOLING,
        apply_outdoor_lock=True,
    )
    hvac = [c for c in hass.services.async_call.call_args_list if c[0][1] == "set_hvac_mode"]
    assert any(c[0][2].get("hvac_mode") == "fan_only" for c in hvac)


@pytest.mark.asyncio
async def test_force_off_wins_outdoor_lock():
    clear_command_cache()
    hass = build_hass()
    ac = _ac_state("heat")
    hass.states.get = MagicMock(side_effect=_states(("climate.ac1", ac), ("sensor.out", _outdoor_state("-8"))))
    devices = [
        {
            "entity_id": "climate.ac1",
            "type": "ac",
            "idle_action": "hold",
            "idle_heat_outdoor_lock": True,
            "idle_heat_outdoor_sensor": "sensor.out",
            "idle_heat_outdoor_below": 0.0,
        }
    ]
    await async_idle_device(
        hass, "climate.ac1", devices, area_id="living_room", force_off=True, apply_outdoor_lock=True
    )
    hvac = [c for c in hass.services.async_call.call_args_list if c[0][1] == "set_hvac_mode"]
    assert any(c[0][2].get("hvac_mode") == "off" for c in hvac)
