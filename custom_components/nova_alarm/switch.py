"""Ordinary controls for excluding and including individual zones."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import AvsCoordinator
from .entity import AvsEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AvsCoordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def add_new() -> None:
        new = coordinator.data.zones.keys() - known
        async_add_entities(AvsZoneExclusion(coordinator, key) for key in sorted(new))
        known.update(new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class AvsZoneExclusion(AvsEntity, SwitchEntity):
    _attr_translation_key = "zone_exclusion"
    _attr_icon = "mdi:shield-off-outline"

    def __init__(self, coordinator: AvsCoordinator, zone_id: str) -> None:
        super().__init__(coordinator, f"zone_{zone_id}_exclusion")
        self.zone_id = zone_id
        zone = coordinator.data.zones[zone_id]
        self._attr_translation_placeholders = {"zone": zone.name or f"Zone {zone_id}"}

    @property
    def available(self) -> bool:
        zone = self.coordinator.data.zones.get(self.zone_id)
        return super().available and zone is not None and zone.flags is not None

    @property
    def is_on(self) -> bool | None:
        zone = self.coordinator.data.zones.get(self.zone_id)
        return zone.bit(2) if zone else None

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set_excluded(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set_excluded(False)

    async def _async_set_excluded(self, excluded: bool) -> None:
        zone = self.coordinator.data.zones.get(self.zone_id)
        if not self.available or zone is None or zone.bit(3):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="zone_not_editable"
            )
        await self.coordinator.async_set_zone_excluded(self.zone_id, excluded)
