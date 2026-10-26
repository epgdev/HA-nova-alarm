"""Login status and recovery regressions; all responses are synthetic."""

from unittest.mock import AsyncMock

import pytest
from test_api import make_client, xml
from test_sessions import short_client

from custom_components.nova_alarm.api import (
    CannotConnect,
    InvalidAuth,
    ProtocolError,
    SessionExpired,
)


@pytest.mark.parametrize(
    "status,error,reason",
    [
        ("2", InvalidAuth, "invalid_pin"),
        ("4", CannotConnect, "user_already_connected"),
        ("5", CannotConnect, "TOO-MANY-USERS"),
        ("7", CannotConnect, "panel_access_inhibited"),
        ("100", CannotConnect, "panel_programming"),
        ("101", CannotConnect, "panel_busy"),
        ("6", ProtocolError, "invalid_login_status"),
        ("secret", ProtocolError, "invalid_login_status"),
        (None, ProtocolError, "invalid_login_status"),
    ],
)
async def test_rejected_login_never_adopts_tokens_reads_or_logs_out(status, error, reason):
    client = make_client()
    client._keep_session = False
    client._discover = AsyncMock()
    attribute = "" if status is None else f' status="{status}"'
    client._post = AsyncMock(
        return_value=xml(
            f'<AVS><AUTH_EX auth="not-owned"/><LOGIN{attribute} session="not-owned"/></AVS>'
        )
    )
    client._snapshot = AsyncMock()
    with pytest.raises(error) as caught:
        await client.async_snapshot()
    assert caught.value.reason == reason
    assert caught.value.operation == "/avs/auth_ex"
    assert "secret" not in str(caught.value)
    assert not client._auth and not client._token
    client._post.assert_awaited_once()
    client._snapshot.assert_not_awaited()


async def test_successful_login_requires_zero_status_and_tokens():
    client = make_client()
    client._discover = AsyncMock()
    client._post = AsyncMock(
        return_value=xml('<AVS><AUTH_EX auth="a"/><LOGIN status="0" session="s"/></AVS>')
    )
    await client._login()
    assert (client._auth, client._token) == ("a", "s")
    client._auth = client._token = ""
    client._post.return_value = xml('<AVS><AUTH_EX auth="a"/><LOGIN status="0"/></AVS>')
    with pytest.raises(ProtocolError) as caught:
        await client._login()
    assert caught.value.reason == "missing_session_credentials"
    assert not client._token


async def test_login_rejection_is_classified_even_without_tokens():
    client = make_client()
    client._discover = AsyncMock()
    client._post = AsyncMock(return_value=xml('<AVS><LOGIN status="4"/></AVS>'))
    with pytest.raises(CannotConnect) as caught:
        await client._login()
    assert caught.value.reason == "user_already_connected"


async def test_discovery_recovers_after_failure_without_hammering(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("custom_components.nova_alarm.api.monotonic", lambda: clock[0])
    client = make_client()
    client._post = AsyncMock(
        side_effect=[
            CannotConnect("offline"),
            xml('<AVS><SERVER hostname="fe2.myavsalarm.com"/></AVS>'),
        ]
    )
    await client._discover()
    assert not client._discovered
    assert client._server == "https://fe1.myavsalarm.com:443"
    await client._discover()
    assert client._post.await_count == 1
    clock[0] += 60
    await client._discover()
    assert client._server == "https://fe2.myavsalarm.com:443"
    assert client._discovered


async def test_invalid_discovery_host_is_never_used_and_can_be_retried(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("custom_components.nova_alarm.api.monotonic", lambda: clock[0])
    client = make_client()
    client._post = AsyncMock(
        side_effect=[
            xml('<AVS><SERVER hostname="attacker.test"/></AVS>'),
            xml('<AVS><SERVER hostname="fe3.myavsalarm.com"/></AVS>'),
        ]
    )
    await client._discover()
    assert not client._discovered
    assert "attacker" not in client._server
    clock[0] = 60
    await client._discover()
    assert client._server == "https://fe3.myavsalarm.com:443"


async def test_server_outage_invalidates_discovery_without_replaying_write():
    client = make_client()
    client._discovered = True
    client._post_request = AsyncMock(
        side_effect=[
            CannotConnect("offline", reason="timeout"),
            xml('<AVS><SERVER hostname="fe2.myavsalarm.com"/></AVS>'),
        ]
    )
    with pytest.raises(CannotConnect):
        await client._post("/avs/set_sectors", {"sectors": "1,0"})
    assert not client._discovered
    client._post_request.assert_awaited_once()
    await client._discover()
    assert client._post_request.await_count == 2
    assert client._post_request.call_args.args[0] == "/avs/felist"


async def test_pending_logout_blocks_new_signin_until_release_succeeds():
    client, events = short_client()
    normal_read = client._read.side_effect
    client._read.side_effect = CannotConnect("offline")
    await client.async_snapshot()
    assert client._logout_pending and client._token
    with pytest.raises(CannotConnect) as caught:
        await client.async_snapshot()
    assert caught.value.reason == "logout_pending"
    client._login.assert_awaited_once()
    client._snapshot.assert_awaited_once()
    client._read.side_effect = normal_read
    await client.async_snapshot()
    assert events == ["login", "read", "/avs/logout", "login", "read", "/avs/logout"]
    assert not client._logout_pending and not client._token


async def test_missing_logout_ack_retains_session_for_retry():
    client, _events = short_client()
    client._read.side_effect = None
    client._read.return_value = xml("<AVS/>")
    await client.async_snapshot()
    assert client._logout_pending and client._token
    client._read.return_value = xml("<AVS><LOGOUT/></AVS>")
    await client.async_close()
    assert not client._logout_pending and not client._token


async def test_already_expired_session_counts_as_released():
    client, _events = short_client()
    client._read.side_effect = SessionExpired("expired")
    await client.async_snapshot()
    assert not client._logout_pending and not client._token


async def test_cancelled_logout_retains_ownership_until_next_cleanup():
    import asyncio

    client, _events = short_client()
    normal_read = client._read.side_effect
    started = asyncio.Event()

    async def blocked_logout(endpoint, extra=None):
        assert endpoint == "/avs/logout"
        started.set()
        await asyncio.Event().wait()

    client._read.side_effect = blocked_logout
    task = asyncio.create_task(client.async_snapshot())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client._token and client._logout_pending
    client._login.assert_awaited_once()
    client._read.side_effect = normal_read
    await client.async_close()
    assert not client._token and not client._logout_pending


async def test_pending_logout_blocks_portal_discovery_too():
    client, _events = short_client()
    client._read.side_effect = CannotConnect("offline")
    await client.async_snapshot()
    client._discover = AsyncMock()
    client._post = AsyncMock()
    with pytest.raises(CannotConnect) as caught:
        await client.async_list_plants()
    assert caught.value.reason == "logout_pending"
    client._discover.assert_not_awaited()
    client._post.assert_not_awaited()
