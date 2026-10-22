"""Read-only alarm state. No alarm commands are implemented."""

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import AVS_MODES, DEFAULT_MODE_MAP, DOMAIN
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
    _attr_supported_features = AlarmControlPanelEntityFeature(0)
    _attr_code_arm_required = False
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
            "read_only": True,
        }

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="read_only")
