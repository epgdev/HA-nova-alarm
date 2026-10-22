"""Session release and optional polling, using only simulated AVS operations."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from test_api import xml
from test_homeassistant import make_entry

from custom_components.nova_alarm.api import (
    AvsClient,
    CannotConnect,
    CommandRejected,
    Plant,
    Sector,
    Snapshot,
    Zone,
)
from custom_components.nova_alarm.coordinator import AvsCoordinator


def short_client():
    client = AvsClient(MagicMock(), "user", "pass", "device", pin="01234", plant=Plant("p", "Casa"))
    events = []

    async def login():
        events.append("login")
        client._auth, client._token = "auth", "session"

    async def snapshot():
        events.append("read")
        return Snapshot({"1": Sector("1", 4, allowed_modes=(0, 4))}, {"1": Zone("1", 0)})

    async def read(endpoint, extra=None):
        events.append(endpoint)
        if endpoint == "/avs/logout":
            return xml("<AVS><LOGOUT/></AVS>")
        if endpoint == "/avs/set_sectors":
            return xml('<AVS><SET_SECTORS status="0"/></AVS>')
        if endpoint == "/avs/set_zones":
            return xml('<AVS><SET_ZONES status="0"/></AVS>')
        raise AssertionError(endpoint)

    client._login = AsyncMock(side_effect=login)
    client._snapshot = AsyncMock(side_effect=snapshot)
    client._read = AsyncMock(side_effect=read)
    return client, events


async def test_default_logs_out_between_reads():
    client, events = short_client()
    await client.async_snapshot()
    assert not client._auth and not client._token
    await client.async_snapshot()
    assert events == ["login", "read", "/avs/logout"] * 2
    await client.async_close()
    assert events == ["login", "read", "/avs/logout"] * 2


@pytest.mark.parametrize("kind", ["sector", "zone"])
async def test_command_and_preflight_use_one_session_then_logout(kind):
    client, events = short_client()
    if kind == "sector":
        await client.async_set_sector_mode("1", 0)
        endpoint = "/avs/set_sectors"
    else:
        await client.async_set_zone_excluded("1", True)
        endpoint = "/avs/set_zones"
    assert events == ["login", "read", endpoint, "/avs/logout"]
    assert not client._auth and not client._token


async def test_failed_preflight_releases_session_without_write():
    client, events = short_client()
    client._snapshot.side_effect = CannotConnect("offline")
    with pytest.raises(CannotConnect):
        await client.async_set_sector_mode("1", 0)
    assert events == ["login", "/avs/logout"]
    assert not client._token


async def test_rejected_command_releases_session():
    client, events = short_client()
    with pytest.raises(CommandRejected):
        await client.async_set_sector_mode("1", 2)
    assert events == ["login", "read", "/avs/logout"]


async def test_logout_failure_does_not_mask_read_or_expose_secrets(caplog):
    client, _events = short_client()
    client._read.side_effect = CannotConnect("secret-password", reason="timeout")
    result = await client.async_snapshot()
    assert result.sectors["1"].mode == 4
    assert not client._token
    assert "AVS logout unconfirmed" in caplog.text
    assert "secret-password" not in caplog.text


async def test_logout_failure_does_not_mask_original_command_error():
    client, _events = short_client()
    client._read.side_effect = [CommandRejected("refused"), CannotConnect("logout failed")]
    with pytest.raises(CommandRejected, match="refused"):
        await client.async_set_sector_mode("1", 0)
    assert client._read.call_args_list[0].args[0] == "/avs/set_sectors"
    assert client._read.call_args_list[1].args[0] == "/avs/logout"
    assert client._read.await_count == 2
    assert not client._token


async def test_cancelled_read_releases_session():
    client, events = short_client()
    started = asyncio.Event()

    async def waiting():
        started.set()
        await asyncio.Event().wait()

    client._snapshot.side_effect = waiting
    task = asyncio.create_task(client.async_snapshot())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["login", "/avs/logout"]
    assert not client._token


async def test_logout_remains_inside_shared_operation_lock():
    client, events = short_client()
    read = client._read.side_effect

    async def slow_logout(endpoint, extra=None):
        result = await read(endpoint, extra)
        await asyncio.sleep(0)
        events.append("logout-done")
        return result

    client._read.side_effect = slow_logout
    await asyncio.gather(client.async_snapshot(), client.async_snapshot())
    assert events == ["login", "read", "/avs/logout", "logout-done"] * 2


async def test_persistent_session_is_explicit_opt_in():
    client, events = short_client()
    client._keep_session = True
    await client.async_snapshot()
    await client.async_snapshot()
    assert events == ["login", "read", "read"]
    await client.async_close()
    assert events[-1] == "/avs/logout"
    assert not client._token


def test_automatic_updates_default_on_and_can_be_disabled(hass):
    default = AvsCoordinator(hass, make_entry(), AsyncMock())
    manual = AvsCoordinator(hass, make_entry({"automatic_updates": False}), AsyncMock())
    assert default.update_interval == timedelta(seconds=60)
    assert manual.update_interval is None


async def test_manual_mode_still_reads_on_request_and_after_commands(hass):
    client = AsyncMock()
    client.async_snapshot.return_value = Snapshot({"1": Sector("1", 4)}, {})
    coordinator = AvsCoordinator(hass, make_entry({"automatic_updates": False}), client)
    await coordinator.async_refresh()
    await coordinator.async_set_sector_mode("1", 0)
    assert client.async_snapshot.await_count == 2
    client.async_set_sector_mode.assert_awaited_once_with("1", 0)
    assert coordinator.update_interval is None


async def test_busy_account_does_not_retry_or_close_another_session():
    client, events = short_client()
    client._login.side_effect = CannotConnect("busy", reason="TOO-MANY-USERS")
    with pytest.raises(CannotConnect) as caught:
        await client.async_snapshot()
    assert caught.value.reason == "TOO-MANY-USERS"
    client._login.assert_awaited_once()
    client._read.assert_not_awaited()
    assert not client._token
    assert events == []
