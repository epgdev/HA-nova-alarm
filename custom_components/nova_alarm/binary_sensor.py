"""Zone states and diagnostics."""

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import AvsCoordinator
from .entity import AvsEntity


@dataclass(frozen=True, kw_only=True)
class AvsBinaryDescription(BinarySensorEntityDescription):
    bit: int


DESCRIPTIONS = (
    AvsBinaryDescription(
        key="opening",
        bit=0,
        translation_key="opening",
        device_class=BinarySensorDeviceClass.OPENING,
    ),
    AvsBinaryDescription(
        key="tamper",
        bit=1,
        translation_key="tamper",
        device_class=BinarySensorDeviceClass.TAMPER,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AvsBinaryDescription(
        key="excluded",
        bit=2,
        translation_key="excluded",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    AvsBinaryDescription(
        key="battery",
        bit=4,
        translation_key="battery",
        device_class=BinarySensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    AvsBinaryDescription(
        key="fault",
        bit=5,
        translation_key="fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    AvsBinaryDescription(
        key="antimask",
        bit=6,
        translation_key="antimask",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    AvsBinaryDescription(
        key="alarm_memory",
        bit=7,
        translation_key="alarm_memory",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AvsCoordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def add_new() -> None:
        new = coordinator.data.zones.keys() - known
        async_add_entities(
            AvsZone(coordinator, key, description)
            for key in sorted(new)
            for description in DESCRIPTIONS
        )
        known.update(new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class AvsZone(AvsEntity, BinarySensorEntity):
    entity_description: AvsBinaryDescription

    def __init__(
        self, coordinator: AvsCoordinator, zone_id: str, description: AvsBinaryDescription
    ) -> None:
        super().__init__(coordinator, f"zone_{zone_id}_{description.key}")
        self.zone_id = zone_id
        self.entity_description = description
        zone = coordinator.data.zones[zone_id]
        self._attr_translation_placeholders = {"zone": zone.name or f"Zone {zone_id}"}

    @property
    def available(self) -> bool:
        zone = self.coordinator.data.zones.get(self.zone_id)
        return super().available and zone is not None and zone.flags is not None

    @property
    def is_on(self) -> bool | None:
        zone = self.coordinator.data.zones.get(self.zone_id)
        return zone.bit(self.entity_description.bit) if zone else None
