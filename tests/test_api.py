"""Protocol behavior and bounded session handling, without cloud access."""

import asyncio
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs

import pytest

from custom_components.nova_alarm.api import (
    AccountError,
    AvsClient,
    CannotConnect,
    InvalidAuth,
    Plant,
    ProtocolError,
    SessionExpired,
    encode_form,
    parse_snapshot,
    parse_xml,
)


def xml(text):
    return ET.fromstring(text)


def make_client():
    return AvsClient(
        MagicMock(), "user", "pass", "1234567890abcdef", pin="01234", plant=Plant("plant", "Casa")
    )


def test_observed_snapshot_and_missing_data():
    sectors = xml(
        '<AVS><GET_SECTORS><ITEM id="1" type="16777236" on="1" off="1"/></GET_SECTORS></AVS>'
    )
    zones = xml(
        '<AVS><GET_ZONES><ITEM id="1" flags="1"/><ITEM id="2" flags="0"/><ITEM id="3"/><ITEM id="4" flags="bad"/></GET_ZONES></AVS>'
    )
    data = parse_snapshot(sectors, zones)
    assert data.sectors["1"].mode == 4
    assert data.zones["1"].bit(0) is True
    assert data.zones["2"].bit(0) is False
    assert data.zones["3"].bit(0) is None
    assert data.zones["4"].bit(0) is None


@pytest.mark.parametrize(
    "body,error",
    [
        (b'<AVS><ERROR cause="SESSION_EXPIRED"/></AVS>', SessionExpired),
        (b'<AVS><ERROR cause="MAX-SUBSCRIPTION-DEVICES"/></AVS>', AccountError),
        (b'<AVS><ERROR cause="COMMUNICATION-ERROR"/></AVS>', CannotConnect),
        (b'<!DOCTYPE a [<!ENTITY x "test">]><a>&x;</a>', ProtocolError),
        (b"<AVS>", ProtocolError),
    ],
)
def test_errors_and_untrusted_xml(body, error):
    with pytest.raises(error):
        parse_xml(body)


def test_unknown_auth_error_is_redacted():
    with pytest.raises(InvalidAuth) as caught:
        parse_xml(b'<AVS><ERROR cause="SECRET-PASSWORD" what="secret"/></AVS>', authenticating=True)
    assert "SECRET" not in str(caught.value)
    assert "secret" not in str(caught.value)


def test_credentials_encoded_once_and_leading_zero_pin_preserved():
    secret = "p a+ss&=%é*~"
    body = encode_form({"password": secret, "pin": "01234"})
    assert parse_qs(body.decode()) == {"password": [secret], "pin": ["01234"]}
    assert b"%20" in body and b"%7E" in body


async def test_success_metadata_cache_and_logout():
    client = make_client()
    responses = {
        "/avs/felist": xml(
            '<AVS><SERVER hostname="attacker.test"/><SERVER hostname="fe2.myavsalarm.com"/></AVS>'
        ),
        "/avs/auth_ex": xml('<AVS><AUTH_EX auth="a"/><LOGIN session="s"/></AVS>'),
        "/avs/get_sectors": xml(
            '<AVS><GET_SECTORS><ITEM id="1" type="16777236"/></GET_SECTORS></AVS>'
        ),
        "/avs/get_zones": xml('<AVS><GET_ZONES><ITEM id="1" flags="1"/></GET_ZONES></AVS>'),
        "/avs/get_desc": xml('<AVS><GET_DESC desc="Finestra%20cucina"/></AVS>'),
        "/avs/logout": xml("<AVS><LOGOUT/></AVS>"),
    }
    client._post = AsyncMock(side_effect=lambda endpoint, *a, **k: responses[endpoint])
    first = await client.async_snapshot()
    second = await client.async_snapshot()
    assert first == second
    assert first.zones["1"].name == "Finestra cucina"
    assert client._server == "https://fe2.myavsalarm.com:443"
    calls = client._post.call_args_list
    assert sum(call.args[0] == "/avs/auth_ex" for call in calls) == 1
    assert sum(call.args[0] == "/avs/get_desc" for call in calls) == 2
    assert next(call.args[1] for call in calls if call.args[0] == "/avs/auth_ex")["pin"] == "01234"
    await client.async_close()
    assert client._post.call_args_list[-1].args[0] == "/avs/logout"
    assert not client._token and not client._auth


async def test_session_renewal_is_bounded():
    client = make_client()
    client._token = "old"
    client._login = AsyncMock()
    client._snapshot = AsyncMock(side_effect=[SessionExpired(), SessionExpired()])
    with pytest.raises(CannotConnect):
        await client.async_snapshot()
    assert client._login.await_count == 1
    assert client._snapshot.await_count == 2
    assert not client._token


async def test_invalid_pin_is_not_retried():
    client = make_client()
    client._login = AsyncMock(side_effect=InvalidAuth())
    with pytest.raises(InvalidAuth):
        await client.async_snapshot()
    assert client._login.await_count == 1


async def test_parallel_updates_are_serialized():
    client = make_client()
    client._token = "valid"
    active = 0
    maximum = 0

    async def snapshot():
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        return "snapshot"

    client._snapshot = snapshot
    await asyncio.gather(client.async_snapshot(), client.async_snapshot())
    assert maximum == 1


async def test_client_does_not_allow_commands():
    client = make_client()
    with pytest.raises(ProtocolError):
        await client._post("/avs/set_sectors", {"mode": "4"})
