"""Gradual thermostat setpoint for inverter minisplits."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.roommind.const import MODE_COOLING, MODE_HEATING
from custom_components.roommind.control.mpc_controller import MPCController
from custom_components.roommind.control.setpoint_ramp import (
    RampConfig,
    SetpointRamp,
    ramp_config,
    ramped_display_eid,
)
from custom_components.roommind.control.thermal_model import RoomModelManager

from .conftest import build_hass, make_room

_AC = {"entity_id": "climate.ac", "type": "ac", "setpoint_mode": "proportional"}


def test_first_step_leaves_the_thermostat_reading():
    ramp = SetpointRamp()
    sent = ramp.advance("climate.ac", MODE_HEATING, 1_000, minutes=60, step=0.5, direction=1, seed=22.0)
    assert sent == 22.5


def test_interval_holds_the_last_step():
    ramp = SetpointRamp()
    ramp.advance("climate.ac", MODE_HEATING, 1_000, minutes=60, step=0.5, direction=1, seed=22.0)
    held = ramp.advance("climate.ac", MODE_HEATING, 1_000 + 3_599, minutes=60, step=0.5, direction=1, seed=22.0)
    assert held == 22.5


def test_next_step_after_the_interval():
    ramp = SetpointRamp()
    ramp.advance("climate.ac", MODE_HEATING, 1_000, minutes=60, step=0.5, direction=1, seed=22.0)
    sent = ramp.advance("climate.ac", MODE_HEATING, 1_000 + 3_600, minutes=60, step=0.5, direction=1, seed=22.0)
    assert sent == 23.0


def test_cooling_steps_down():
    ramp = SetpointRamp()
    sent = ramp.advance("climate.ac", MODE_COOLING, 1_000, minutes=60, step=0.5, direction=-1, seed=25.0)
    assert sent == 24.5


def test_advance_moves_toward_desired_without_overshoot():
    ramp = SetpointRamp()
    sent = ramp.advance("climate.ac", MODE_HEATING, 1_000, minutes=60, step=0.5, direction=-1, seed=22.3, desired=22.0)
    assert sent == 22.0


def test_mode_change_keeps_the_last_value():
    ramp = SetpointRamp()
    ramp.advance("climate.ac", MODE_HEATING, 1_000, minutes=60, step=0.5, direction=1, seed=22.0)
    held = ramp.advance("climate.ac", MODE_COOLING, 1_100, minutes=60, step=0.5, direction=-1, seed=18.0)
    assert held == 22.5
    sent = ramp.advance("climate.ac", MODE_COOLING, 1_000 + 3_600, minutes=60, step=0.5, direction=-1, seed=18.0)
    assert sent == 22.0


def test_inside_the_band_holds_after_the_interval():
    ramp = SetpointRamp()
    ramp.advance("climate.ac", MODE_HEATING, 1_000, minutes=60, step=0.5, direction=1, seed=22.0)
    held = ramp.advance("climate.ac", MODE_HEATING, 1_000 + 3_600, minutes=60, step=0.5, direction=0, seed=22.0)
    assert held == 22.5


def test_device_step_is_the_smallest_move():
    ramp = SetpointRamp()
    sent = ramp.advance(
        "climate.ac", MODE_HEATING, 1_000, minutes=60, step=0.5, direction=1, seed=19.2, device_step=1.0
    )
    assert sent == 20.2


def test_clear_starts_the_next_trim_from_the_thermostat():
    ramp = SetpointRamp()
    ramp.advance("climate.ac", MODE_HEATING, 1_000, minutes=60, step=0.5, direction=1, seed=22.0)
    ramp.advance("climate.ac", MODE_HEATING, 1_000 + 3_600, minutes=60, step=0.5, direction=1, seed=22.0)
    ramp.clear("climate.ac")
    sent = ramp.advance("climate.ac", MODE_HEATING, 9_000, minutes=60, step=0.5, direction=1, seed=21.0)
    assert sent == 21.5


def test_persisted_ramp_survives_a_restart():
    ramp = SetpointRamp()
    ramp.advance("climate.ac", MODE_HEATING, 1_000, minutes=60, step=0.5, direction=1, seed=22.0)
    restored = SetpointRamp()
    restored.load_state(ramp.get_state())
    held = restored.advance("climate.ac", MODE_HEATING, 1_500, minutes=60, step=0.5, direction=1, seed=22.0)
    assert held == 22.5


def test_missing_history_without_a_seed_sends_nothing():
    ramp = SetpointRamp()
    assert ramp.advance("climate.ac", MODE_HEATING, 1_000, minutes=60, step=0.5, direction=1, seed=None) is None


def test_ramp_config_is_only_for_proportional_acs():
    assert ramp_config(None) is None
    assert ramp_config({"type": "trv", "setpoint_ramp_minutes": 60}) is None
    assert ramp_config({**_AC, "setpoint_mode": "direct", "setpoint_ramp_minutes": 60}) is None
    assert ramp_config({**_AC, "setpoint_ramp_minutes": 0}) is None
    assert ramp_config({**_AC, "setpoint_ramp_minutes": 60, "setpoint_ramp_step": 0.5}) == RampConfig(60, 0.5)
    # A hand-edited interval below the minimum is raised to it
    assert ramp_config({**_AC, "setpoint_ramp_minutes": 3}) == RampConfig(5, 0.5)


def test_ramp_config_delta_mode_and_deadband():
    cfg = ramp_config(
        {
            **_AC,
            "setpoint_ramp_minutes": 60,
            "setpoint_ramp_mode": "delta",
            "setpoint_ramp_deadband": 0.3,
        }
    )
    assert cfg == RampConfig(60, 0.5, "delta", 0.3)
    assert ramp_config({**_AC, "setpoint_ramp_minutes": 60, "setpoint_ramp_mode": "nope"}).mode == "fixed"


def test_display_uses_the_single_ramped_ac():
    ac = {**_AC, "setpoint_ramp_minutes": 60}
    assert ramped_display_eid(MODE_HEATING, [ac]) == "climate.ac"
    assert ramped_display_eid(MODE_COOLING, [ac]) == "climate.ac"
    assert ramped_display_eid("idle", [ac]) == "climate.ac"
    trv = {"entity_id": "climate.trv", "type": "trv"}
    assert ramped_display_eid(MODE_HEATING, [trv, ac]) is None
    plan = SimpleNamespace(commands=[SimpleNamespace(active=True, device_type="ac", entity_id="climate.ac")])
    assert ramped_display_eid(MODE_HEATING, [trv, ac], heat_source_plan=plan) == "climate.ac"
    direct = {**_AC, "setpoint_mode": "direct"}
    assert ramped_display_eid(MODE_HEATING, [direct], direct_eids={"climate.ac"}) is None


def _ramped_room():
    room = make_room(thermostats=[], acs=["climate.ac"])
    room["devices"][0]["setpoint_ramp_minutes"] = 60
    room["devices"][0]["setpoint_ramp_step"] = 0.5
    return room


def _delta_room(*, deadband=0.5):
    room = _ramped_room()
    room["devices"][0]["setpoint_ramp_mode"] = "delta"
    room["devices"][0]["setpoint_ramp_deadband"] = deadband
    return room


def _ac_state(hvac="heat", **attrs):
    state = MagicMock()
    state.state = hvac
    state.attributes = {
        "hvac_modes": ["heat", "cool", "fan_only", "off"],
        "temperature": 22.0,
        "current_temperature": 19.0,
        "min_temp": 16.0,
        "max_temp": 30.0,
        **attrs,
    }
    return state


def _temps(hass):
    return [c[0][2]["temperature"] for c in hass.services.async_call.call_args_list if c[0][1] == "set_temperature"]


def _modes(hass):
    return [c[0][1] for c in hass.services.async_call.call_args_list]


@pytest.mark.asyncio
async def test_apply_steps_up_from_the_thermostat_when_the_room_is_cold():
    """A cold room raises the setpoint one step and does not switch a unit already in heat."""
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state())
    ctrl = MPCController(
        hass,
        _ramped_room(),
        model_manager=RoomModelManager(),
        outdoor_temp=5.0,
        settings={},
        has_external_sensor=True,
    )
    await ctrl.async_apply("heating", 22.0, power_fraction=1.0, current_temp=20.0)
    assert _temps(hass) == [22.5]
    assert "set_hvac_mode" not in _modes(hass)

    await ctrl.async_apply("heating", 22.0, power_fraction=1.0, current_temp=20.0)
    assert _temps(hass) == [22.5, 22.5]


@pytest.mark.asyncio
async def test_idle_applies_idle_action_and_eases_the_setpoint():
    """At the target Gradual does not keep heat on; the idle action runs and the setpoint eases down."""
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state(temperature=25.0))
    room = _ramped_room()
    room["devices"][0]["idle_action"] = "fan_only"
    ctrl = MPCController(
        hass,
        room,
        model_manager=RoomModelManager(),
        outdoor_temp=5.0,
        settings={},
        has_external_sensor=True,
    )
    await ctrl.async_apply("idle", 22.0, current_temp=23.0)
    assert _temps(hass) == [24.5]
    mode_calls = [c for c in hass.services.async_call.call_args_list if c[0][1] == "set_hvac_mode"]
    assert mode_calls and mode_calls[0][0][2]["hvac_mode"] == "fan_only"
    assert "heat" not in [c[0][2].get("hvac_mode") for c in mode_calls]


@pytest.mark.asyncio
async def test_room_inside_the_step_eases_toward_the_target():
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state(temperature=23.0))
    ctrl = MPCController(
        hass,
        _ramped_room(),
        model_manager=RoomModelManager(),
        outdoor_temp=5.0,
        settings={},
        has_external_sensor=True,
    )
    await ctrl.async_apply("heating", 22.0, power_fraction=0.0, current_temp=22.2)
    assert _temps(hass) == [22.5]
    assert "set_hvac_mode" not in _modes(hass)


@pytest.mark.asyncio
async def test_cooling_steps_toward_the_cool_target():
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state(hvac="cool", temperature=24.0))
    ctrl = MPCController(
        hass,
        _ramped_room(),
        model_manager=RoomModelManager(),
        outdoor_temp=28.0,
        settings={},
        has_external_sensor=True,
    )
    await ctrl.async_apply("cooling", 24.0, power_fraction=1.0, current_temp=26.0)
    assert _temps(hass) == [23.5]
    assert "set_hvac_mode" not in _modes(hass)


@pytest.mark.asyncio
async def test_heating_from_fan_only_switches_to_heat_then_steps():
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state(hvac="fan_only", temperature=22.0))
    ctrl = MPCController(
        hass,
        _ramped_room(),
        model_manager=RoomModelManager(),
        outdoor_temp=5.0,
        settings={},
        has_external_sensor=True,
    )
    await ctrl.async_apply("heating", 22.0, power_fraction=1.0, current_temp=18.0)
    mode_calls = [c for c in hass.services.async_call.call_args_list if c[0][1] == "set_hvac_mode"]
    assert mode_calls and mode_calls[0][0][2]["hvac_mode"] == "heat"
    assert _temps(hass) == [22.5]
    assert all(t < 25 for t in _temps(hass))


@pytest.mark.asyncio
async def test_heating_from_off_switches_to_heat_then_steps():
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state(hvac="off"))
    ctrl = MPCController(
        hass,
        _ramped_room(),
        model_manager=RoomModelManager(),
        outdoor_temp=5.0,
        settings={},
        has_external_sensor=True,
    )
    await ctrl.async_apply("heating", 22.0, power_fraction=1.0, current_temp=18.0)
    mode_calls = [c for c in hass.services.async_call.call_args_list if c[0][1] == "set_hvac_mode"]
    assert mode_calls and mode_calls[0][0][2]["hvac_mode"] == "heat"
    assert _temps(hass) == [22.5]


@pytest.mark.asyncio
async def test_delta_step_moves_by_the_room_error():
    """A 2 °C gap raises the setpoint by 2 °C, not by the deadband."""
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state())
    ctrl = MPCController(
        hass,
        _delta_room(),
        model_manager=RoomModelManager(),
        outdoor_temp=5.0,
        settings={},
        has_external_sensor=True,
    )
    await ctrl.async_apply("heating", 22.0, power_fraction=1.0, current_temp=20.0)
    assert _temps(hass) == [24.0]


@pytest.mark.asyncio
async def test_delta_deadband_eases_toward_the_target():
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state(temperature=23.0))
    ctrl = MPCController(
        hass,
        _delta_room(deadband=0.5),
        model_manager=RoomModelManager(),
        outdoor_temp=5.0,
        settings={},
        has_external_sensor=True,
    )
    await ctrl.async_apply("heating", 22.0, power_fraction=0.0, current_temp=22.2)
    assert _temps(hass) == [22.5]


@pytest.mark.asyncio
async def test_heating_overshoot_lowers_the_setpoint():
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state(temperature=23.0))
    ctrl = MPCController(
        hass,
        _ramped_room(),
        model_manager=RoomModelManager(),
        outdoor_temp=5.0,
        settings={},
        has_external_sensor=True,
    )
    await ctrl.async_apply("heating", 22.0, power_fraction=1.0, current_temp=24.0)
    assert _temps(hass) == [22.5]


@pytest.mark.asyncio
async def test_ramp_clamps_to_offset_max():
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state(temperature=28.5))
    ctrl = MPCController(
        hass,
        _ramped_room(),
        model_manager=RoomModelManager(),
        outdoor_temp=5.0,
        settings={},
        has_external_sensor=True,
    )
    await ctrl.async_apply("heating", 21.0, power_fraction=1.0, current_temp=20.0)
    assert _temps(hass) == [26.0]


@pytest.mark.asyncio
async def test_delta_clamps_a_large_error_to_five_degrees():
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state())
    ctrl = MPCController(
        hass,
        _delta_room(),
        model_manager=RoomModelManager(),
        outdoor_temp=5.0,
        settings={},
        has_external_sensor=True,
    )
    await ctrl.async_apply("heating", 22.0, power_fraction=1.0, current_temp=14.0)
    assert _temps(hass) == [27.0]


@pytest.mark.asyncio
async def test_idle_on_an_off_unit_sends_nothing():
    hass = build_hass()
    hass.states.get = MagicMock(return_value=_ac_state(hvac="off"))
    ctrl = MPCController(
        hass,
        _ramped_room(),
        model_manager=RoomModelManager(),
        outdoor_temp=5.0,
        settings={},
        has_external_sensor=True,
    )
    await ctrl.async_apply("idle", 22.0, current_temp=18.0)
    assert hass.services.async_call.call_args_list == []
