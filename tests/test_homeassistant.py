"""Real HA flow, lifecycle, state and availability tests with a fake AVS client."""

from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.alarm_control_panel import AlarmControlPanelState
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ConfigEntryAuthFailed, ServiceValidationError

from custom_components.nova_alarm.alarm_control_panel import AvsAlarm
from custom_components.nova_alarm.api import InvalidAuth, Plant, Sector, Snapshot, Zone
from custom_components.nova_alarm.binary_sensor import DESCRIPTIONS, AvsZone
from custom_components.nova_alarm.const import DOMAIN
from custom_components.nova_alarm.coordinator import AvsCoordinator


def make_entry():
    return ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        source="user",
        title="AVS test",
        data={
            CONF_USERNAME: "user",
            CONF_PASSWORD: "secret",
            "plant_id": "test-plant",
            "plant_name": "Casa",
            "pin": "01234",
            "device_id": "1234567890abcdef",
        },
        options={},
        unique_id="test-plant",
        discovery_keys=MappingProxyType({}),
        subentries_data=[],
    )


def snapshot(flags=1):
    return Snapshot(
        {"1": Sector("1", 16777236, "Casa")}, {"1": Zone("1", flags, "Finestra cucina")}
    )


async def test_entities_and_unknown_data(hass):
    coordinator = AvsCoordinator(hass, make_entry(), AsyncMock())
    coordinator.async_set_updated_data(snapshot())
    alarm = AvsAlarm(coordinator, "1")
    zone = AvsZone(coordinator, "1", DESCRIPTIONS[0])
    assert alarm.alarm_state == AlarmControlPanelState.DISARMED
    assert alarm.extra_state_attributes["avs_mode"] == "OFF"
    assert zone.is_on is True
    coordinator.async_set_updated_data(snapshot(0))
    assert zone.is_on is False
    coordinator.async_set_updated_data(snapshot(None))
    assert zone.is_on is None and not zone.available
    coordinator.async_set_updated_data(Snapshot({}, {}))
    assert not alarm.available and not zone.available


async def test_no_disarming_command(hass):
    coordinator = AvsCoordinator(hass, make_entry(), AsyncMock())
    coordinator.async_set_updated_data(snapshot())
    alarm = AvsAlarm(coordinator, "1")
    with pytest.raises(ServiceValidationError):
        await alarm.async_alarm_disarm("01234")
    coordinator.client.async_snapshot.assert_not_awaited()


async def test_bad_credentials_start_reauthentication(hass):
    client = AsyncMock()
    client.async_snapshot.side_effect = InvalidAuth("Authentication refused")
    coordinator = AvsCoordinator(hass, make_entry(), client)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_flow_through_manager(hass):
    with (
        patch("custom_components.nova_alarm.config_flow.AvsClient") as cls,
        patch(
            "custom_components.nova_alarm.config_flow.async_get_clientsession",
            return_value=MagicMock(),
        ),
    ):
        client = cls.return_value
        client.async_list_plants = AsyncMock(return_value=[Plant("test-plant", "Casa")])
        client.async_snapshot = AsyncMock(return_value=snapshot())
        client.async_close = AsyncMock()
        with patch("custom_components.nova_alarm.async_setup_entry", return_value=True):
            result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "user"
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "username": "user",
                    "password": "secret",
                    "device_id": "1234567890abcdef",
                },
            )
            assert result["step_id"] == "plant"
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "plant_id": "test-plant",
                    "pin": "01234",
                },
            )
            assert result["type"] is FlowResultType.CREATE_ENTRY
            assert result["data"]["pin"] == "01234"
            assert result["data"]["device_id"] == "1234567890abcdef"
            client.async_close.assert_awaited_once()
            await hass.async_block_till_done()


async def test_real_entry_setup_states_options_and_unload(hass):
    client = AsyncMock()
    client.async_snapshot.return_value = snapshot()
    with (
        patch("custom_components.nova_alarm.AvsClient", return_value=client),
        patch("custom_components.nova_alarm.async_get_clientsession", return_value=MagicMock()),
    ):
        entry = make_entry()
        await hass.config_entries.async_add(entry)
        await hass.async_block_till_done()
        states = hass.states.async_all()
        alarms = [state for state in states if state.domain == "alarm_control_panel"]
        openings = [
            state
            for state in states
            if state.domain == "binary_sensor" and state.attributes.get("device_class") == "opening"
        ]
        assert len(alarms) == 1
        assert alarms[0].state == "disarmed"
        assert len(openings) == 1
        assert openings[0].state == "on"
        assert "Finestra cucina" in openings[0].name
        coordinator = entry.runtime_data
        coordinator.async_set_updated_data(snapshot(0))
        await hass.async_block_till_done()
        assert hass.states.get(openings[0].entity_id).state == "off"
        coordinator.async_set_updated_data(snapshot(None))
        await hass.async_block_till_done()
        assert hass.states.get(openings[0].entity_id).state == "unavailable"
        options = await hass.config_entries.options.async_init(entry.entry_id)
        assert options["type"] is FlowResultType.FORM
        assert options["step_id"] == "init"
        assert await hass.config_entries.async_unload(entry.entry_id)
        client.async_close.assert_awaited_once()
