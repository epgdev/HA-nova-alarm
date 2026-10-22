"""One coordinated cloud poll for all entities in an installation."""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AccountError,
    AvsClient,
    AvsError,
    CannotConnect,
    CommandRejected,
    InvalidAuth,
    Snapshot,
)
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

    async def async_set_sector_mode(self, sector_id: str, mode: int) -> None:
        try:
            await self.client.async_set_sector_mode(sector_id, mode)
        except AvsError as error:
            # A failed response may follow an applied command. Reconcile with a read,
            # without replaying the write or publishing an optimistic alarm state.
            await self.async_request_refresh()
            key = "command_rejected" if isinstance(error, CommandRejected) else "command_failed"
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key=key) from None
        await self.async_request_refresh()
        if not self.last_update_success:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_unconfirmed"
            )

    async def _async_update_data(self) -> Snapshot:
        try:
            return await self.client.async_snapshot()
        except InvalidAuth as error:
            raise ConfigEntryAuthFailed(str(error)) from error
        except AccountError as error:
            raise ConfigEntryError(str(error)) from error
        except CannotConnect as error:
            raise UpdateFailed(str(error)) from error
