"""Zone controls and selectable arming modes, without real AVS traffic."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.components.alarm_control_panel import AlarmControlPanelEntityFeature
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from test_homeassistant import make_entry, snapshot

from custom_components.nova_alarm.alarm_control_panel import AvsAlarm
from custom_components.nova_alarm.api import CommandRejected, Sector, Snapshot
from custom_components.nova_alarm.coordinator import AvsCoordinator
from custom_components.nova_alarm.switch import AvsZoneExclusion


async def test_only_on_is_shown_and_other_services_blocked(hass):
    client = AsyncMock()
    client.async_snapshot.return_value = snapshot()
    entry = make_entry({"enabled_modes": ["ON"]})
    coordinator = AvsCoordinator(hass, entry, client)
    coordinator.async_set_updated_data(snapshot())
    alarm = AvsAlarm(coordinator, "1")
    assert alarm.supported_features == AlarmControlPanelEntityFeature.ARM_AWAY
    for method in [
        alarm.async_alarm_arm_home,
        alarm.async_alarm_arm_night,
        alarm.async_alarm_arm_custom_bypass,
        alarm.async_alarm_arm_vacation,
    ]:
        with pytest.raises(ServiceValidationError):
            await method("01234")
    client.async_set_sector_mode.assert_not_awaited()
    await alarm.async_alarm_arm_away("01234")
    client.async_set_sector_mode.assert_awaited_once_with("1", 0)
    await alarm.async_alarm_disarm("01234")
    assert client.async_set_sector_mode.call_args.args == ("1", 4)


async def test_hidden_modes_still_display_actual_state(hass):
    coordinator = AvsCoordinator(hass, make_entry({"enabled_modes": []}), AsyncMock())
    coordinator.async_set_updated_data(Snapshot({"1": Sector("1", 1, allowed_modes=(1, 4))}, {}))
    alarm = AvsAlarm(coordinator, "1")
    assert alarm.supported_features == 0
    assert alarm.alarm_state == "armed_home"


@pytest.mark.parametrize("excluded,flags", [(True, 4), (False, 0)])
async def test_zone_switch_updates_from_observed_state(hass, excluded, flags):
    client = AsyncMock()
    client.async_snapshot.return_value = snapshot(flags)
    coordinator = AvsCoordinator(hass, make_entry(), client)
    coordinator.async_set_updated_data(snapshot(0 if excluded else 4))
    switch = AvsZoneExclusion(coordinator, "1")
    assert switch.entity_category is None
    assert switch.entity_registry_enabled_default
    if excluded:
        await switch.async_turn_on()
    else:
        await switch.async_turn_off()
    client.async_set_zone_excluded.assert_awaited_once_with("1", excluded)
    assert switch.is_on is excluded


@pytest.mark.parametrize("flags", [None, 8, 12])
async def test_switch_blocks_unknown_or_active_zone(hass, flags):
    client = AsyncMock()
    coordinator = AvsCoordinator(hass, make_entry(), client)
    coordinator.async_set_updated_data(snapshot(flags))
    switch = AvsZoneExclusion(coordinator, "1")
    for command in [switch.async_turn_on, switch.async_turn_off]:
        with pytest.raises(ServiceValidationError):
            await command()
    client.async_set_zone_excluded.assert_not_awaited()


async def test_zone_ack_without_changed_state_is_not_success(hass):
    client = AsyncMock()
    client.async_snapshot.return_value = snapshot(0)
    coordinator = AvsCoordinator(hass, make_entry(), client)
    coordinator.async_set_updated_data(snapshot(0))
    switch = AvsZoneExclusion(coordinator, "1")
    with pytest.raises(HomeAssistantError) as caught:
        await switch.async_turn_on()
    assert caught.value.translation_key == "command_unconfirmed"
    assert switch.is_on is False
    client.async_set_zone_excluded.assert_awaited_once()


async def test_zone_rejection_refreshes_without_replay(hass):
    client = AsyncMock()
    client.async_set_zone_excluded.side_effect = CommandRejected("secret")
    client.async_snapshot.return_value = snapshot(0)
    coordinator = AvsCoordinator(hass, make_entry(), client)
    coordinator.async_set_updated_data(snapshot(0))
    with pytest.raises(HomeAssistantError) as caught:
        await AvsZoneExclusion(coordinator, "1").async_turn_on()
    assert caught.value.translation_key == "command_rejected"
    client.async_set_zone_excluded.assert_awaited_once()
    client.async_snapshot.assert_awaited_once()
