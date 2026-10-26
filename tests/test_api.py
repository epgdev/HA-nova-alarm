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
    CommandRejected,
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
        MagicMock(),
        "user",
        "pass",
        "1234567890abcdef",
        pin="01234",
        plant=Plant("plant", "Casa"),
        keep_session=True,
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
        "/avs/auth_ex": xml('<AVS><AUTH_EX auth="a"/><LOGIN status="0" session="s"/></AVS>'),
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


async def test_client_does_not_allow_user_code_changes():
    client = make_client()
    with pytest.raises(ProtocolError):
        await client._post("/avs/set_user_code", {"mode": "4"})


@pytest.mark.parametrize("mode", range(5))
async def test_sector_command_wire_format(mode):
    client = make_client()
    client._token, client._auth = "session", "auth"
    response = MagicMock()
    response.status = 200

    async def chunks(size):
        yield b'<AVS><SET_SECTORS status="0"/></AVS>'

    response.content.iter_chunked = chunks
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    client._session.post.return_value = context
    client._snapshot = AsyncMock(
        return_value=parse_snapshot(
            xml(
                '<AVS><GET_SECTORS><ITEM id="1" type="4" on="1" ho="1" ar="1" pe="1" off="1"/></GET_SECTORS></AVS>'
            ),
            xml("<AVS><GET_ZONES/></AVS>"),
        )
    )
    await client.async_set_sector_mode("1", mode)
    call = client._session.post.call_args
    assert call.args == ("https://fe1.myavsalarm.com:443/avs/set_sectors",)
    assert call.kwargs["data"] == (
        f"auth=auth&session=session&sectors=1,{mode}&check=1&checkzone=1".encode()
    )
    assert parse_qs(call.kwargs["data"].decode()) == {
        "auth": ["auth"],
        "session": ["session"],
        "sectors": [f"1,{mode}"],
        "check": ["1"],
        "checkzone": ["1"],
    }
    assert call.kwargs["allow_redirects"] is False
    client._session.post.assert_called_once()


def test_sector_permissions_are_explicit_and_preserved():
    data = parse_snapshot(
        xml(
            '<AVS><GET_SECTORS><ITEM id="1" type="4" on="1" ho="0" ar="2" pe="bad" off="1"/></GET_SECTORS></AVS>'
        ),
        xml("<AVS><GET_ZONES/></AVS>"),
    )
    assert data.sectors["1"].allowed_modes == (0, 4)


@pytest.mark.parametrize("sector,mode", [("1,2", 0), ("0", 4), ("-1", 0), ("1", 5), ("1", True)])
async def test_invalid_command_never_connects(sector, mode):
    client = make_client()
    client._login = AsyncMock()
    with pytest.raises(CommandRejected):
        await client.async_set_sector_mode(sector, mode)
    client._login.assert_not_awaited()


@pytest.mark.parametrize("sector", ["1", "2"])
async def test_command_checks_fresh_sector_permissions(sector):
    client = make_client()
    client._snapshot_with_renewal = AsyncMock(
        return_value=parse_snapshot(
            xml('<AVS><GET_SECTORS><ITEM id="1" type="4" off="1"/></GET_SECTORS></AVS>'),
            xml("<AVS><GET_ZONES/></AVS>"),
        )
    )
    client._post = AsyncMock()
    with pytest.raises(CommandRejected):
        await client.async_set_sector_mode(sector, 0)
    client._post.assert_not_awaited()


@pytest.mark.parametrize("status", ["1", "2", "3", "-1", "bad", None])
async def test_command_rejection_never_forces_or_retries(status):
    client = make_client()
    client._snapshot_with_renewal = AsyncMock(
        return_value=parse_snapshot(
            xml('<AVS><GET_SECTORS><ITEM id="1" type="4" on="1"/></GET_SECTORS></AVS>'),
            xml("<AVS><GET_ZONES/></AVS>"),
        )
    )
    element = ET.Element("SET_SECTORS", {"errstr": "secret", "idzone": "1"})
    if status is not None:
        element.set("status", status)
    client._post = AsyncMock(return_value=element)
    with pytest.raises(CommandRejected) as caught:
        await client.async_set_sector_mode("1", 0)
    assert "secret" not in str(caught.value)
    client._post.assert_awaited_once()
    assert client._post.call_args.args[1]["checkzone"] == "1"


@pytest.mark.parametrize(
    "error", [CannotConnect("timeout"), SessionExpired("expired"), ProtocolError("bad XML")]
)
async def test_uncertain_command_is_not_replayed(error):
    client = make_client()
    client._snapshot_with_renewal = AsyncMock(
        return_value=parse_snapshot(
            xml('<AVS><GET_SECTORS><ITEM id="1" type="4" off="1"/></GET_SECTORS></AVS>'),
            xml("<AVS><GET_ZONES/></AVS>"),
        )
    )
    client._post = AsyncMock(side_effect=error)
    with pytest.raises(CannotConnect):
        await client.async_set_sector_mode("1", 4)
    client._post.assert_awaited_once()


async def test_poll_and_command_share_one_lock():
    client = make_client()
    client._token = "session"
    data = parse_snapshot(
        xml('<AVS><GET_SECTORS><ITEM id="1" type="4" off="1"/></GET_SECTORS></AVS>'),
        xml("<AVS><GET_ZONES/></AVS>"),
    )
    order = []

    async def snapshot():
        order.append("read-start")
        await asyncio.sleep(0)
        order.append("read-end")
        return data

    async def post(*args):
        order.append("write-start")
        await asyncio.sleep(0)
        order.append("write-end")
        return xml('<AVS><SET_SECTORS status="0"/></AVS>')

    client._snapshot = snapshot
    client._post = post
    await asyncio.gather(client.async_set_sector_mode("1", 4), client.async_snapshot())
    assert order == ["read-start", "read-end", "write-start", "write-end", "read-start", "read-end"]


@pytest.mark.parametrize("excluded,flags", [(True, 0), (False, 4)])
async def test_zone_command_wire_format(excluded, flags):
    client = make_client()
    client._auth, client._token = "auth", "session"
    data = parse_snapshot(
        xml('<AVS><GET_SECTORS><ITEM id="1" type="4"/></GET_SECTORS></AVS>'),
        xml(f'<AVS><GET_ZONES><ITEM id="6" flags="{flags}"/></GET_ZONES></AVS>'),
    )
    client._snapshot_with_renewal = AsyncMock(return_value=data)
    response = MagicMock()
    response.status = 200

    async def chunks(size):
        yield b'<AVS><SET_ZONES status="0"/></AVS>'

    response.content.iter_chunked = chunks
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    client._session.post.return_value = context
    await client.async_set_zone_excluded("6", excluded)
    call = client._session.post.call_args
    assert call.args == ("https://fe1.myavsalarm.com:443/avs/set_zones",)
    assert call.kwargs["data"] == f"auth=auth&session=session&zones=6,{int(excluded)}".encode()
    assert parse_qs(call.kwargs["data"].decode()) == {
        "auth": ["auth"],
        "session": ["session"],
        "zones": [f"6,{int(excluded)}"],
    }
    client._session.post.assert_called_once()


@pytest.mark.parametrize("zone_id,flags", [("6", 8), ("6", 12), ("6", None), ("7", 0)])
@pytest.mark.parametrize("excluded", [True, False])
async def test_active_unknown_or_missing_zone_never_written(zone_id, flags, excluded):
    client = make_client()
    data = parse_snapshot(
        xml('<AVS><GET_SECTORS><ITEM id="1" type="4"/></GET_SECTORS></AVS>'),
        xml("<AVS><GET_ZONES/></AVS>"),
    )
    from custom_components.nova_alarm.api import Zone

    data.zones["6"] = Zone("6", flags)
    client._snapshot_with_renewal = AsyncMock(return_value=data)
    client._post = AsyncMock()
    with pytest.raises(CommandRejected):
        await client.async_set_zone_excluded(zone_id, excluded)
    client._post.assert_not_awaited()


@pytest.mark.parametrize("zone_id,excluded", [("0", True), ("1,2", True), ("-1", True), ("1", 1)])
async def test_invalid_zone_command_never_connects(zone_id, excluded):
    client = make_client()
    client._login = AsyncMock()
    with pytest.raises(CommandRejected):
        await client.async_set_zone_excluded(zone_id, excluded)
    client._login.assert_not_awaited()


@pytest.mark.parametrize("excluded,flags", [(True, 4), (False, 0)])
async def test_zone_already_matches_does_not_write(excluded, flags):
    client = make_client()
    client._snapshot_with_renewal = AsyncMock(
        return_value=parse_snapshot(
            xml('<AVS><GET_SECTORS><ITEM id="1" type="4"/></GET_SECTORS></AVS>'),
            xml(f'<AVS><GET_ZONES><ITEM id="6" flags="{flags}"/></GET_ZONES></AVS>'),
        )
    )
    client._post = AsyncMock()
    await client.async_set_zone_excluded("6", excluded)
    client._post.assert_not_awaited()


@pytest.mark.parametrize(
    "result,error",
    [
        ('<AVS><SET_ZONES status="1"/></AVS>', CommandRejected),
        ("<AVS><SET_ZONES/></AVS>", CommandRejected),
        ("<AVS/>", ProtocolError),
        (CannotConnect("timeout"), CannotConnect),
        (SessionExpired("expired"), CannotConnect),
    ],
)
async def test_zone_failure_is_never_retried(result, error):
    client = make_client()
    client._snapshot_with_renewal = AsyncMock(
        return_value=parse_snapshot(
            xml('<AVS><GET_SECTORS><ITEM id="1" type="4"/></GET_SECTORS></AVS>'),
            xml('<AVS><GET_ZONES><ITEM id="6" flags="0"/></GET_ZONES></AVS>'),
        )
    )
    client._post = AsyncMock()
    if isinstance(result, Exception):
        client._post.side_effect = result
    else:
        client._post.return_value = xml(result)
    with pytest.raises(error):
        await client.async_set_zone_excluded("6", True)
    client._post.assert_awaited_once()


@pytest.mark.parametrize(
    "body,reason",
    [
        (b'<AVS><ERROR cause="TOO-MANY-USERS" what="secret"/></AVS>', "TOO-MANY-USERS"),
        (b'<AVS><ERROR cause="COMMUNICATION-ERROR" what="secret"/></AVS>', "COMMUNICATION-ERROR"),
        (b'<AVS><ERROR cause="SECRET-PASSWORD" what="secret"/></AVS>', "unrecognized_server_error"),
        (b"not xml with secret", "invalid_xml"),
    ],
)
def test_diagnostic_reasons_never_include_remote_details(body, reason):
    from custom_components.nova_alarm.api import AvsError

    with pytest.raises(AvsError) as caught:
        parse_xml(body)
    assert caught.value.reason == reason
    assert "secret" not in str(caught.value).lower()
    assert "secret" not in caught.value.reason.lower()


@pytest.mark.parametrize(
    "failure,reason",
    [
        (TimeoutError("secret"), "timeout"),
        (CannotConnect("secret", reason="connection_error"), "connection_error"),
    ],
)
async def test_request_records_only_safe_operation(failure, reason):
    client = make_client()
    if isinstance(failure, TimeoutError):
        client._session.post.side_effect = failure
    else:
        client._post_request = AsyncMock(side_effect=failure)
    with pytest.raises(CannotConnect) as caught:
        await client._post("/avs/auth_ex", {"password": "secret"})
    assert caught.value.operation == "/avs/auth_ex"
    assert caught.value.reason == reason


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_http_diagnostic_status(status):
    client = make_client()
    response = MagicMock()
    response.status = status
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    client._session.post.return_value = context
    from custom_components.nova_alarm.api import AvsError

    with pytest.raises(AvsError) as caught:
        await client._post("/avs/auth_ex", {"password": "secret"}, authenticating=True)
    assert caught.value.reason == f"http_{status}"
    assert caught.value.operation == "/avs/auth_ex"


def test_literal_command_delimiter_does_not_change_credential_encoding():
    body = encode_form(
        {
            "username": "user,name",
            "password": "p,a+ss&=%",
            "auth": "a,b+&",
            "session": "s,e+&",
            "sectors": "1,0",
            "zones": "6,1",
        }
    )
    assert body == (
        b"username=user%2Cname&password=p%2Ca%2Bss%26%3D%25&auth=a%2Cb%2B%26"
        b"&session=s%2Ce%2B%26&sectors=1,0&zones=6,1"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("sectors", "1,0&check=0"),
        ("zones", "6,1&other=1"),
        ("sectors", "1,0,2,4"),
        ("other", "1,0"),
    ],
)
def test_only_single_valid_command_pair_retains_literal_comma(field, value):
    body = encode_form({field: value})
    assert b"," not in body
    assert parse_qs(body.decode()) == {field: [value]}


@pytest.mark.parametrize(
    "body,kind",
    [
        (b"", "empty"),
        (b"<html>secret-password", "html"),
        (b'{"password":"secret-password"}', "json_like"),
        (b'<AVS secret="secret-password">', "xml_like"),
        (b"secret-password", "other"),
    ],
)
async def test_invalid_xml_response_metadata_without_content(body, kind, caplog):
    client = make_client()
    response = MagicMock()
    response.status = 200

    async def chunks(size):
        yield body

    response.content.iter_chunked = chunks
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    client._session.post.return_value = context
    with pytest.raises(ProtocolError) as caught:
        await client._post("/avs/auth_ex", {"password": "secret-password"}, authenticating=True)
    assert caught.value.reason == "invalid_xml"
    assert f"response_kind={kind}" in caplog.text
    assert f"response_bytes={len(body)}" in caplog.text
    assert "http_status=200" in caplog.text
    assert "secret-password" not in caplog.text
