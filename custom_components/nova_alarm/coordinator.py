"""One coordinated cloud poll for all entities in an installation."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
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
from .const import CONF_AUTOMATIC_UPDATES, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

LOGGER = logging.getLogger(__name__)
CONFIRMATION_ATTEMPTS = 3
CONFIRMATION_DELAY = 2
CONFIRMATION_TIMEOUT = 20


class AvsCoordinator(DataUpdateCoordinator[Snapshot]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: AvsClient) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=(
                timedelta(seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
                if entry.options.get(CONF_AUTOMATIC_UPDATES, True)
                else None
            ),
            always_update=False,
        )
        self.client = client
        self._command_lock = asyncio.Lock()

    async def async_set_sector_mode(self, sector_id: str, mode: int) -> None:
        def matches(data: Snapshot) -> bool:
            sector = data.sectors.get(sector_id)
            return sector is not None and sector.mode == mode

        await self._async_command(
            lambda: self.client.async_set_sector_mode(sector_id, mode), matches
        )

    async def async_set_zone_excluded(self, zone_id: str, excluded: bool) -> None:
        def matches(data: Snapshot) -> bool:
            zone = data.zones.get(zone_id)
            return zone is not None and zone.bit(2) == excluded

        await self._async_command(
            lambda: self.client.async_set_zone_excluded(zone_id, excluded), matches
        )

    async def _async_command(
        self, command: Callable[[], Awaitable[None]], matches: Callable[[Snapshot], bool]
    ) -> None:
        # Serialize the write and its confirmation; a second command must not
        # supersede the target while we are still checking the first one.
        async with self._command_lock:
            try:
                await command()
            except AvsError as error:
                LOGGER.warning(
                    "AVS command failed: operation=%s category=%s reason=%s; write not retried",
                    error.operation,
                    type(error).__name__,
                    error.reason,
                )
                # Delivery can be uncertain. Reconcile with one read, never a replay.
                await self.async_refresh()
                key = "command_rejected" if isinstance(error, CommandRejected) else "command_failed"
                raise HomeAssistantError(translation_domain=DOMAIN, translation_key=key) from None
            try:
                async with asyncio.timeout(CONFIRMATION_TIMEOUT):
                    for attempt in range(CONFIRMATION_ATTEMPTS):
                        await self.async_refresh()
                        if not self.last_update_success:
                            break
                        if matches(self.data):
                            return
                        if attempt + 1 < CONFIRMATION_ATTEMPTS:
                            await asyncio.sleep(CONFIRMATION_DELAY)
            except TimeoutError:
                self.async_set_update_error(UpdateFailed("AVS command confirmation timed out"))
            LOGGER.warning("AVS command state unconfirmed; write not retried")
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
            LOGGER.warning(
                "AVS read failed: operation=%s category=%s reason=%s",
                error.operation,
                type(error).__name__,
                error.reason,
            )
            raise UpdateFailed(str(error)) from error
