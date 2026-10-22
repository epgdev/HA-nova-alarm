"""Real HA flow, lifecycle, state and availability tests with a fake AVS client."""

from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)

from custom_components.nova_alarm.alarm_control_panel import AvsAlarm
from custom_components.nova_alarm.api import (
    CannotConnect,
    CommandRejected,
    InvalidAuth,
    Plant,
    Sector,
    Snapshot,
    Zone,
)
from custom_components.nova_alarm.binary_sensor import DESCRIPTIONS, AvsZone
from custom_components.nova_alarm.const import DEFAULT_MODE_MAP, DOMAIN
from custom_components.nova_alarm.coordinator import AvsCoordinator


def make_entry(options=None):
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
        options=options or {},
        unique_id="test-plant",
        discovery_keys=MappingProxyType({}),
        subentries_data=[],
    )


def snapshot(flags=1):
    return Snapshot(
        {"1": Sector("1", 16777236, "Casa", (0, 1, 2, 3, 4))},
        {"1": Zone("1", flags, "Finestra cucina")},
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


@pytest.mark.parametrize("code", [None, "", "1234", "wrong", "０１２３４"])
async def test_commands_require_exact_pin(hass, code):
    coordinator = AvsCoordinator(hass, make_entry(), AsyncMock())
    coordinator.async_set_updated_data(snapshot())
    alarm = AvsAlarm(coordinator, "1")
    for command in (alarm.async_alarm_disarm, alarm.async_alarm_arm_away):
        with pytest.raises(ServiceValidationError):
            await command(code)
    coordinator.client.async_set_sector_mode.assert_not_awaited()


@pytest.mark.parametrize(
    "method,mode",
    [
        ("async_alarm_arm_away", 0),
        ("async_alarm_arm_home", 1),
        ("async_alarm_arm_custom_bypass", 2),
        ("async_alarm_arm_night", 3),
        ("async_alarm_disarm", 4),
    ],
)
async def test_commands_refresh_actual_state(hass, method, mode):
    client = AsyncMock()
    client.async_snapshot.return_value = snapshot()
    coordinator = AvsCoordinator(hass, make_entry(), client)
    coordinator.async_set_updated_data(snapshot())
    alarm = AvsAlarm(coordinator, "1")
    assert alarm.code_format == CodeFormat.NUMBER
    assert alarm.code_arm_required
    await getattr(alarm, method)("01234")
    client.async_set_sector_mode.assert_awaited_once_with("1", mode)
    client.async_snapshot.assert_awaited_once()
    # Even if the panel takes time to arm, publish only the observed state.
    assert alarm.alarm_state == AlarmControlPanelState.DISARMED


async def test_mapping_and_ambiguous_legacy_options(hass):
    entry = make_entry({"mode_on": "armed_vacation"})
    client = AsyncMock()
    client.async_snapshot.return_value = snapshot()
    coordinator = AvsCoordinator(hass, entry, client)
    coordinator.async_set_updated_data(snapshot())
    alarm = AvsAlarm(coordinator, "1")
    assert alarm.supported_features & AlarmControlPanelEntityFeature.ARM_VACATION
    assert not alarm.supported_features & AlarmControlPanelEntityFeature.ARM_AWAY
    await alarm.async_alarm_arm_vacation("01234")
    client.async_set_sector_mode.assert_awaited_once_with("1", 0)
    coordinator.config_entry = make_entry({"mode_on": "armed_home"})
    assert not alarm.supported_features & AlarmControlPanelEntityFeature.ARM_HOME
    with pytest.raises(ServiceValidationError):
        await alarm.async_alarm_arm_home("01234")
    assert client.async_set_sector_mode.await_count == 1


async def test_missing_permissions_and_unavailable_block_commands(hass):
    client = AsyncMock()
    coordinator = AvsCoordinator(hass, make_entry(), client)
    coordinator.async_set_updated_data(Snapshot({"1": Sector("1", 4)}, {}))
    alarm = AvsAlarm(coordinator, "1")
    assert alarm.supported_features == 0
    with pytest.raises(ServiceValidationError):
        await alarm.async_alarm_disarm("01234")
    coordinator.async_set_updated_data(snapshot())
    coordinator.async_set_update_error(CannotConnect("offline"))
    with pytest.raises(ServiceValidationError):
        await alarm.async_alarm_arm_away("01234")
    client.async_set_sector_mode.assert_not_awaited()


@pytest.mark.parametrize("error", [CommandRejected("secret"), CannotConnect("secret")])
async def test_command_errors_are_redacted_and_state_refreshed(hass, error):
    client = AsyncMock()
    client.async_set_sector_mode.side_effect = error
    client.async_snapshot.return_value = snapshot()
    coordinator = AvsCoordinator(hass, make_entry(), client)
    coordinator.async_set_updated_data(snapshot())
    with pytest.raises(HomeAssistantError) as caught:
        await AvsAlarm(coordinator, "1").async_alarm_disarm("01234")
    assert "secret" not in str(caught.value)
    client.async_set_sector_mode.assert_awaited_once()
    client.async_snapshot.assert_awaited_once()


async def test_accepted_command_with_failed_refresh_is_unconfirmed(hass):
    client = AsyncMock()
    client.async_snapshot.side_effect = CannotConnect("offline")
    coordinator = AvsCoordinator(hass, make_entry(), client)
    coordinator.async_set_updated_data(snapshot())
    with pytest.raises(HomeAssistantError) as caught:
        await AvsAlarm(coordinator, "1").async_alarm_disarm("01234")
    assert caught.value.translation_key == "command_unconfirmed"
    assert not coordinator.last_update_success


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
        assert alarms[0].attributes["code_format"] == "number"
        await hass.services.async_call(
            "alarm_control_panel",
            "alarm_arm_away",
            {"entity_id": alarms[0].entity_id, "code": "01234"},
            blocking=True,
        )
        client.async_set_sector_mode.assert_awaited_once_with("1", 0)
        client.async_set_sector_mode.reset_mock()
        await hass.services.async_call(
            "alarm_control_panel",
            "alarm_disarm",
            {"entity_id": alarms[0].entity_id, "code": "01234"},
            blocking=True,
        )
        client.async_set_sector_mode.assert_awaited_once_with("1", 4)
        switches = [state for state in hass.states.async_all() if state.domain == "switch"]
        assert len(switches) == 1
        from homeassistant.helpers import entity_registry as er

        registry_entry = er.async_get(hass).async_get(switches[0].entity_id)
        assert registry_entry.entity_category is None
        client.async_snapshot.return_value = snapshot(4)
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": switches[0].entity_id},
            blocking=True,
        )
        await hass.async_block_till_done()
        client.async_set_zone_excluded.assert_awaited_once_with("1", True)
        assert hass.states.get(switches[0].entity_id).state == "on"
        client.async_snapshot.return_value = snapshot(0)
        client.async_set_zone_excluded.reset_mock()
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": switches[0].entity_id},
            blocking=True,
        )
        await hass.async_block_till_done()
        client.async_set_zone_excluded.assert_awaited_once_with("1", False)
        assert hass.states.get(switches[0].entity_id).state == "off"
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
        duplicate = {**DEFAULT_MODE_MAP, "scan_interval": 60, "mode_on": "armed_home"}
        result = await hass.config_entries.options.async_configure(options["flow_id"], duplicate)
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "duplicate_modes"}
        with patch.object(hass.config_entries, "async_reload", new=AsyncMock()):
            result = await hass.config_entries.options.async_configure(
                options["flow_id"],
                {**duplicate, "enabled_modes": ["ON"]},
            )
            assert result["type"] is FlowResultType.CREATE_ENTRY
            assert entry.options["enabled_modes"] == ["ON"]
            await hass.async_block_till_done()
        assert await hass.config_entries.async_unload(entry.entry_id)
        client.async_close.assert_awaited_once()
