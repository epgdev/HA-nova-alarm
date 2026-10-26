"""Confirm observed alarm state before completing actions, without replaying writes."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_homeassistant import make_entry, snapshot

from custom_components.nova_alarm.coordinator import AvsCoordinator


@pytest.mark.parametrize("mode", [0, 1, 2, 3, 4])
async def test_wait_for_requested_sector_mode_without_replaying(hass, mode):
    client = AsyncMock()
    previous = 0 if mode == 4 else 4
    client.async_snapshot.side_effect = [
        snapshot(mode=previous),
        snapshot(mode=previous),
        snapshot(mode=mode),
    ]
    coordinator = AvsCoordinator(hass, make_entry(), client)
    coordinator.async_set_updated_data(snapshot(mode=previous))
    await coordinator.async_set_sector_mode("1", mode)
    client.async_set_sector_mode.assert_awaited_once_with("1", mode)
    assert client.async_snapshot.await_count == 3
    assert coordinator.data.sectors["1"].mode == mode


async def test_unchanged_sector_is_unconfirmed_and_never_optimistic(hass):
    client = AsyncMock()
    client.async_snapshot.return_value = snapshot()
    coordinator = AvsCoordinator(hass, make_entry(), client)
    coordinator.async_set_updated_data(snapshot())
    with pytest.raises(HomeAssistantError) as caught:
        await coordinator.async_set_sector_mode("1", 0)
    assert caught.value.translation_key == "command_unconfirmed"
    client.async_set_sector_mode.assert_awaited_once()
    assert client.async_snapshot.await_count == 3
    assert coordinator.data.sectors["1"].mode == 4
    assert coordinator.last_update_success


async def test_delayed_zone_confirmation_uses_reads_only(hass):
    client = AsyncMock()
    client.async_snapshot.side_effect = [snapshot(0), snapshot(4)]
    coordinator = AvsCoordinator(hass, make_entry(), client)
    coordinator.async_set_updated_data(snapshot(0))
    await coordinator.async_set_zone_excluded("1", True)
    client.async_set_zone_excluded.assert_awaited_once_with("1", True)
    assert client.async_snapshot.await_count == 2
    assert coordinator.data.zones["1"].bit(2)


async def test_confirmation_has_timeout_without_resubmitting(hass, monkeypatch):
    monkeypatch.setattr("custom_components.nova_alarm.coordinator.CONFIRMATION_TIMEOUT", 0.01)
    client = AsyncMock()

    async def hanging_read():
        await asyncio.Event().wait()

    client.async_snapshot.side_effect = hanging_read
    coordinator = AvsCoordinator(hass, make_entry(), client)
    coordinator.async_set_updated_data(snapshot())
    with pytest.raises(HomeAssistantError) as caught:
        await coordinator.async_set_sector_mode("1", 0)
    assert caught.value.translation_key == "command_unconfirmed"
    assert not coordinator.last_update_success
    client.async_set_sector_mode.assert_awaited_once()


async def test_opposing_commands_are_serialized_through_confirmation(hass):
    client = AsyncMock()
    started = asyncio.Event()
    proceed = asyncio.Event()
    events = []
    mode = [4]

    async def write(sector_id, requested):
        events.append(f"write-{requested}")
        mode[0] = requested

    async def read():
        if mode[0] == 0:
            started.set()
            await proceed.wait()
        events.append(f"read-{mode[0]}")
        return snapshot(mode=mode[0])

    client.async_set_sector_mode.side_effect = write
    client.async_snapshot.side_effect = read
    coordinator = AvsCoordinator(hass, make_entry(), client)
    coordinator.async_set_updated_data(snapshot())
    first = asyncio.create_task(coordinator.async_set_sector_mode("1", 0))
    await started.wait()
    second = asyncio.create_task(coordinator.async_set_sector_mode("1", 4))
    await asyncio.sleep(0)
    assert client.async_set_sector_mode.await_count == 1
    proceed.set()
    await asyncio.gather(first, second)
    assert events == ["write-0", "read-0", "write-4", "read-4"]


async def test_cancelled_queued_command_is_never_created_or_sent(hass):
    client = AsyncMock()
    started = asyncio.Event()
    proceed = asyncio.Event()

    async def read():
        started.set()
        await proceed.wait()
        return snapshot(mode=0)

    client.async_snapshot.side_effect = read
    coordinator = AvsCoordinator(hass, make_entry(), client)
    coordinator.async_set_updated_data(snapshot())
    first = asyncio.create_task(coordinator.async_set_sector_mode("1", 0))
    await started.wait()
    second = asyncio.create_task(coordinator.async_set_sector_mode("1", 4))
    await asyncio.sleep(0)
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second
    proceed.set()
    await first
    client.async_set_sector_mode.assert_awaited_once_with("1", 0)
