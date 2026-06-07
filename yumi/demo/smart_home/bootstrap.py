"""
Yumi SDK integration for the Smart Home demo.

Registers application tools with ``YumiAgent`` — same pattern as a real app.
"""

from __future__ import annotations

from yumi.demo.smart_home.app import (
    brew_coffee,
    set_alarm,
    set_curtains,
    set_door_lock,
    set_fan,
    set_gate,
    set_light,
    set_oven,
    set_porch_light,
    set_speaker,
    set_sprinkler,
    set_thermostat,
    set_tv,
    set_water_heater,
)
from yumi.sdk import YumiAgent


def init_yumi(connection_code: str | None = None) -> YumiAgent:
    agent = YumiAgent(connection_code=connection_code, edge_name="SmartHome-Demo")

    agent.register(set_light, "Control room lights. Rooms: living_room, kitchen, bedroom, bathroom")
    agent.register(set_tv, "Turn the living room TV on/off and change channel")
    agent.register(set_speaker, "Turn the living room speaker on/off and choose a song/genre")
    agent.register(set_oven, "Turn the kitchen oven on/off and set temperature in Celsius")
    agent.register(brew_coffee, "Start or stop the coffee machine")
    agent.register(set_curtains, "Open or close the bedroom curtains")
    agent.register(set_alarm, "Set or clear the bedroom alarm clock")
    agent.register(set_fan, "Turn the bathroom fan on or off")
    agent.register(set_water_heater, "Turn the bathroom water heater on/off and set temperature")
    agent.register(set_sprinkler, "Turn the garden sprinkler on or off")
    agent.register(set_porch_light, "Turn the garden porch light on or off")
    agent.register(set_gate, "Open or close the garden gate", require_confirmation=True)
    agent.register(set_thermostat, "Set the whole-house thermostat temperature (10-35 Celsius)")
    agent.register(set_door_lock, "Lock or unlock the front door", require_confirmation=True)

    agent.run_in_background()

    return agent
