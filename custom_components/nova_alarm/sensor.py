"""Raw AVS mode, so installation-specific HA mappings remain inspectable."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import AVS_MODES
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
        async_add_entities(AvsMode(coordinator, key) for key in sorted(new))
        known.update(new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class AvsMode(AvsEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "avs_mode"

    def __init__(self, coordinator: AvsCoordinator, sector_id: str) -> None:
        super().__init__(coordinator, f"sector_{sector_id}_mode")
        self._attr_options = list(AVS_MODES.values())
        self.sector_id = sector_id
        sector = coordinator.data.sectors[sector_id]
        self._attr_translation_placeholders = {"sector": sector.name or f"Sector {sector_id}"}

    @property
    def available(self) -> bool:
        return super().available and self.sector_id in self.coordinator.data.sectors

    @property
    def native_value(self) -> str | None:
        sector = self.coordinator.data.sectors.get(self.sector_id)
        return AVS_MODES.get(sector.mode) if sector else None
