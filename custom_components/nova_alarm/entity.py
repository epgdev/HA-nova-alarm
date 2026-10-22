"""Common entity properties."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PLANT_ID, CONF_PLANT_NAME, DOMAIN
from .coordinator import AvsCoordinator


class AvsEntity(CoordinatorEntity[AvsCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: AvsCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        plant_id = entry.data[CONF_PLANT_ID]
        self._attr_unique_id = f"{plant_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, plant_id)},
            name=entry.data[CONF_PLANT_NAME] or "AVS",
            manufacturer="AVS Electronics",
        )
