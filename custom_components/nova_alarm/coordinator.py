"""One coordinated cloud poll for all entities in an installation."""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AccountError, AvsClient, CannotConnect, InvalidAuth, Snapshot
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

LOGGER = logging.getLogger(__name__)


class AvsCoordinator(DataUpdateCoordinator[Snapshot]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: AvsClient) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
            always_update=False,
        )
        self.client = client

    async def _async_update_data(self) -> Snapshot:
        try:
            return await self.client.async_snapshot()
        except InvalidAuth as error:
            raise ConfigEntryAuthFailed(str(error)) from error
        except AccountError as error:
            raise ConfigEntryError(str(error)) from error
        except CannotConnect as error:
            raise UpdateFailed(str(error)) from error
