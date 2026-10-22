"""Sector states and PIN-protected AVS commands."""

import hmac

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    AVS_MODES,
    CONF_ENABLED_MODES,
    CONF_PIN,
    CONF_REQUIRE_COMMAND_PIN,
    DEFAULT_ENABLED_MODES,
    DEFAULT_MODE_MAP,
    DOMAIN,
)
from .coordinator import AvsCoordinator
from .entity import AvsEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AvsCoordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def add_new() -> None:
        new = coordinator.data.sectors.keys() - known
        async_add_entities(AvsAlarm(coordinator, key) for key in sorted(new))
        known.update(new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class AvsAlarm(AvsEntity, AlarmControlPanelEntity):
    _attr_translation_key = "sector"

    def __init__(self, coordinator: AvsCoordinator, sector_id: str) -> None:
        super().__init__(coordinator, f"sector_{sector_id}")
        self.sector_id = sector_id
        sector = coordinator.data.sectors[sector_id]
        self._attr_translation_placeholders = {
            "sector": sector.name or f"Sector {sector_id}",
        }

    @property
    def available(self) -> bool:
        return super().available and self.sector_id in self.coordinator.data.sectors

    @property
    def code_arm_required(self) -> bool:
        return self.coordinator.config_entry.options.get(CONF_REQUIRE_COMMAND_PIN, True)

    @property
    def code_format(self) -> CodeFormat | None:
        return CodeFormat.NUMBER if self.code_arm_required else None

    def _mapped_modes(self) -> dict[str, list[int]]:
        mapped: dict[str, list[int]] = {}
        for mode, label in AVS_MODES.items():
            if mode == 4:
                continue
            if label not in self.coordinator.config_entry.options.get(
                CONF_ENABLED_MODES, DEFAULT_ENABLED_MODES
            ):
                continue
            key = "mode_" + label.lower()
            state = self.coordinator.config_entry.options.get(key, DEFAULT_MODE_MAP[key])
            mapped.setdefault(state, []).append(mode)
        return mapped

    @property
    def supported_features(self) -> AlarmControlPanelEntityFeature:
        features = AlarmControlPanelEntityFeature(0)
        sector = self.coordinator.data.sectors.get(self.sector_id)
        if sector is None or self.sector_id == "0":
            return features
        for state, modes in self._mapped_modes().items():
            if len(modes) == 1 and modes[0] in sector.allowed_modes:
                feature = {
                    "armed_away": AlarmControlPanelEntityFeature.ARM_AWAY,
                    "armed_home": AlarmControlPanelEntityFeature.ARM_HOME,
                    "armed_night": AlarmControlPanelEntityFeature.ARM_NIGHT,
                    "armed_custom_bypass": AlarmControlPanelEntityFeature.ARM_CUSTOM_BYPASS,
                    "armed_vacation": AlarmControlPanelEntityFeature.ARM_VACATION,
                }.get(state)
                if feature is not None:
                    features |= feature
        return features

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        sector = self.coordinator.data.sectors.get(self.sector_id)
        if sector is None or sector.mode is None:
            return None
        if sector.mode == 4:
            return AlarmControlPanelState.DISARMED
        if sector.mode not in AVS_MODES:
            return None
        key = "mode_" + AVS_MODES[sector.mode].lower()
        mapped = self.coordinator.config_entry.options.get(key, DEFAULT_MODE_MAP[key])
        try:
            return AlarmControlPanelState(mapped)
        except ValueError:
            return None

    @property
    def extra_state_attributes(self) -> dict:
        sector = self.coordinator.data.sectors.get(self.sector_id)
        return {
            "avs_mode": AVS_MODES.get(sector.mode) if sector else None,
            "avs_flags": sector.flags if sector else None,
            "read_only": False,
        }

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        await self._async_command(4, code)

    async def _async_arm(self, state: str, code: str | None) -> None:
        modes = self._mapped_modes().get(state, [])
        if len(modes) != 1:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="ambiguous_mode"
            )
        await self._async_command(modes[0], code)

    async def _async_command(self, mode: int, code: str | None) -> None:
        expected = self.coordinator.config_entry.data[CONF_PIN]
        if self.code_arm_required and (
            not isinstance(code, str)
            or not code
            or not hmac.compare_digest(code.encode("utf-8"), expected.encode("utf-8"))
        ):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="invalid_code")
        sector = self.coordinator.data.sectors.get(self.sector_id)
        if not self.available or sector is None or mode not in sector.allowed_modes:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="mode_not_allowed"
            )
        await self.coordinator.async_set_sector_mode(self.sector_id, mode)

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        await self._async_arm("armed_away", code)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        await self._async_arm("armed_home", code)

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        await self._async_arm("armed_night", code)

    async def async_alarm_arm_custom_bypass(self, code: str | None = None) -> None:
        await self._async_arm("armed_custom_bypass", code)

    async def async_alarm_arm_vacation(self, code: str | None = None) -> None:
        await self._async_arm("armed_vacation", code)
