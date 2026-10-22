"""Async AVS cloud client, reconstructed from the supplied Android APK.

Commands target a single sector, with the same zone checks as the Android app.
Zone exclusion targets a single inactive zone. Device replacement is not implemented.
"""

from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from urllib.parse import quote_plus, unquote_plus, urlencode

import aiohttp

MAX_RESPONSE = 2 * 1024 * 1024
ALLOWED_ENDPOINTS = frozenset(
    {
        "/avs/felist",
        "/avs/portal_auth",
        "/avs/auth_ex",
        "/avs/get_sectors",
        "/avs/get_zones",
        "/avs/get_desc",
        "/avs/set_sectors",
        "/avs/set_zones",
        "/avs/logout",
    }
)


class AvsError(Exception):
    """A sanitized error; never include server response bodies or credentials."""

    def __init__(self, message: str = "", *, reason: str = "unknown", operation: str = "unknown"):
        super().__init__(message)
        self.reason = reason
        self.operation = operation


class CannotConnect(AvsError):
    """Transient network, server or equipment communication failure."""


class InvalidAuth(AvsError):
    """Credentials or PIN must be checked by the user."""


class AccountError(AvsError):
    """Subscription, consent or device limit requires user intervention."""


class SessionExpired(AvsError):
    """The cloud session must be renewed."""


class ProtocolError(CannotConnect):
    """The response does not match the reconstructed protocol."""


class CommandRejected(AvsError):
    """A command is not permitted or was refused by the central panel."""


@dataclass(frozen=True)
class Plant:
    id: str
    name: str


@dataclass(frozen=True)
class Sector:
    id: str
    flags: int | None
    name: str = ""
    allowed_modes: tuple[int, ...] = ()

    @property
    def mode(self) -> int | None:
        return None if self.flags is None else self.flags & 15


@dataclass(frozen=True)
class Zone:
    id: str
    flags: int | None
    name: str = ""

    def bit(self, bit: int) -> bool | None:
        return None if self.flags is None else bool(self.flags & (1 << bit))


@dataclass(frozen=True)
class Snapshot:
    sectors: dict[str, Sector]
    zones: dict[str, Zone]


def elements(root: ET.Element, name: str) -> list[ET.Element]:
    return [item for item in root.iter() if item.tag.rsplit("}", 1)[-1] == name]


def required_element(root: ET.Element, name: str, *, operation: str = "unknown") -> ET.Element:
    matches = elements(root, name)
    if len(matches) != 1:
        raise ProtocolError(
            "Unexpected XML structure", reason="unexpected_xml_structure", operation=operation
        )
    return matches[0]


def optional_int(value: str | None) -> int | None:
    try:
        number = int(value) if value is not None else None
    except ValueError:
        return None
    return number if number is None or number >= 0 else None


def parse_xml(data: bytes, *, authenticating: bool = False) -> ET.Element:
    if len(data) > MAX_RESPONSE:
        raise ProtocolError("Response exceeds size limit")
    upper = data.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ProtocolError("Unsupported XML declarations")
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise ProtocolError("Invalid XML response", reason="invalid_xml") from None
    errors = elements(root, "ERROR")
    if not errors:
        return root
    cause = errors[0].get("cause", "")
    if cause in {
        "SUBSCRIPTION-NOT-FOUND",
        "SUBSCRIPTION-NOT-ACTIVE",
        "MAX-SUBSCRIPTION-DEVICES",
        "DISCLAIMER-NOT-ACCEPTED",
        "DISCLAIMER_REQUIRED",
        "DISCLAIMER-REQUIRED",
    }:
        raise AccountError(cause, reason=cause)
    if cause in {"HTTP_UNAUTHORIZED", "SESSION_EXPIRED"} and not authenticating:
        raise SessionExpired("Cloud session expired", reason=cause)
    if cause == "BAD-ARGUMENT":
        raise ProtocolError("AVS rejected request parameters", reason="BAD-ARGUMENT")
    if cause in {
        "COMMUNICATION-ERROR",
        "EQUIPMENT-NOT-FOUND",
        "DB-ERROR",
        "SERVICE_UPDATING",
        "SERVICE-UPDATING",
        "TOO-MANY-USERS",
        "TIMEOUT",
    }:
        raise CannotConnect("AVS service or equipment unavailable", reason=cause)
    if authenticating:
        raise InvalidAuth(
            "AVS refused authentication; check account and PIN in the app",
            reason="authentication_refused",
        )
    raise ProtocolError("AVS returned an unrecognized error", reason="unrecognized_server_error")


def encode_form(params: dict[str, str]) -> bytes:
    # The APK encodes credentials before joining the form, but SetSectorsJob
    # and SetZonesJob pass their numeric comma-separated arguments verbatim.
    # Preserve only that validated delimiter; keep escaping all other values.
    fields = []
    for key, raw in params.items():
        value = raw.strip()
        command_pair = (key == "sectors" and re.fullmatch(r"[0-9]+,[0-4]", value)) or (
            key == "zones" and re.fullmatch(r"[0-9]+,[01]", value)
        )
        fields.append(
            urlencode({key: value}, quote_via=quote_plus, safe="*," if command_pair else "*")
        )
    value = "&".join(fields)
    return value.replace("+", "%20").replace("~", "%7E").encode("utf-8")


def parse_snapshot(sector_xml: ET.Element, zone_xml: ET.Element) -> Snapshot:
    sectors: dict[str, Sector] = {}
    zones: dict[str, Zone] = {}
    for item in elements(
        required_element(sector_xml, "GET_SECTORS", operation="/avs/get_sectors"), "ITEM"
    ):
        item_id = item.get("id", "")
        if not item_id or item_id in sectors:
            raise ProtocolError("Invalid or duplicate sector identifier")
        sectors[item_id] = Sector(
            item_id,
            optional_int(item.get("type")),
            allowed_modes=tuple(
                mode
                for mode, field in enumerate(("on", "ho", "ar", "pe", "off"))
                if item.get(field) == "1"
            ),
        )
    for item in elements(
        required_element(zone_xml, "GET_ZONES", operation="/avs/get_zones"), "ITEM"
    ):
        item_id = item.get("id", "")
        if not item_id or item_id in zones:
            raise ProtocolError("Invalid or duplicate zone identifier")
        zones[item_id] = Zone(item_id, optional_int(item.get("flags")))
    if not sectors:
        raise ProtocolError("No sectors returned")
    return Snapshot(sectors, zones)


class AvsClient:
    """One account/plant session, with serialized requests and bounded renewal."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        device_id: str,
        *,
        pin: str = "",
        plant: Plant | None = None,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._pin = pin
        self._device_id = device_id
        self.plant = plant
        self._server = "https://fe1.myavsalarm.com:443"
        self._discovered = False
        self._auth = ""
        self._token = ""
        self._lock = asyncio.Lock()
        self._names: dict[tuple[str, str], str] = {}

    def _common(self) -> dict[str, str]:
        return {"devtype": "3", "appfev": "43", "mac": self._device_id, "systype": "1"}

    async def _post(
        self,
        endpoint: str,
        params: dict[str, str],
        *,
        server: str | None = None,
        authenticating: bool = False,
    ) -> ET.Element:
        try:
            return await self._post_request(
                endpoint, params, server=server, authenticating=authenticating
            )
        except AvsError as error:
            # Record only the allowlisted endpoint, never URLs, bodies or form fields.
            error.operation = endpoint if endpoint in ALLOWED_ENDPOINTS else "unsupported_endpoint"
            raise

    async def _post_request(
        self,
        endpoint: str,
        params: dict[str, str],
        *,
        server: str | None = None,
        authenticating: bool = False,
    ) -> ET.Element:
        if endpoint not in ALLOWED_ENDPOINTS:
            raise ProtocolError("Endpoint is not supported by this client")
        try:
            async with self._session.post(
                (server or self._server) + endpoint,
                data=encode_form(params),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=45),
                allow_redirects=False,
            ) as response:
                if response.status in (401, 403):
                    if authenticating:
                        raise InvalidAuth(
                            "Account or PIN refused", reason=f"http_{response.status}"
                        )
                    raise SessionExpired("Cloud session expired", reason=f"http_{response.status}")
                if response.status == 429:
                    raise CannotConnect("AVS request rate exceeded", reason="http_429")
                if response.status not in (200, 412):
                    raise CannotConnect("AVS HTTP request failed", reason=f"http_{response.status}")
                chunks = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    chunks.extend(chunk)
                    if len(chunks) > MAX_RESPONSE:
                        raise ProtocolError("Response exceeds size limit")
                root = parse_xml(bytes(chunks), authenticating=authenticating)
                if response.status != 200:
                    raise ProtocolError("Unexpected AVS HTTP response")
                return root
        except TimeoutError:
            raise CannotConnect("Connection to AVS timed out", reason="timeout") from None
        except aiohttp.ClientSSLError:
            raise CannotConnect("TLS connection to AVS failed", reason="tls_error") from None
        except aiohttp.ClientConnectorError:
            raise CannotConnect("Connection to AVS failed", reason="connection_error") from None
        except aiohttp.ClientError:
            raise CannotConnect("Connection to AVS failed", reason="transport_error") from None

    async def _discover(self) -> None:
        if self._discovered:
            return
        try:
            root = await self._post(
                "/avs/felist", self._common(), server="https://dr.myavsalarm.com:443"
            )
            hosts = [e.get("hostname", "") for e in elements(root, "SERVER")]
            hosts = [h for h in hosts if re.fullmatch(r"fe\d+\.myavsalarm\.com", h)]
            if hosts:
                self._server = "https://" + hosts[0] + ":443"
        except AvsError:
            pass  # APK fallback: fe1. Never send secrets to arbitrary hosts.
        self._discovered = True

    async def async_list_plants(self) -> list[Plant]:
        async with self._lock:
            await self._discover()
            root = await self._post(
                "/avs/portal_auth",
                {
                    **self._common(),
                    "username": self._username,
                    "password": self._password,
                    "lang": "IT",
                },
                authenticating=True,
            )
            plants = [
                Plant(unquote_plus(e.get("idavs", "")), unquote_plus(e.get("name", "")))
                for e in elements(root, "PLANT")
                if e.get("idavs")
            ]
            if not plants:
                raise AccountError("No plants are associated with this account")
            return plants

    async def _login(self) -> None:
        if self.plant is None:
            raise ProtocolError("No plant selected")
        await self._discover()
        root = await self._post(
            "/avs/auth_ex",
            {
                **self._common(),
                "username": self._username,
                "password": self._password,
                "aid": self.plant.id,
                "tokenid": self._device_id,
                "aux": "",
                "name": self.plant.name,
                "devicename": "Home Assistant AVS",
                "pin": self._pin,
                "localaid": self.plant.id,
            },
            authenticating=True,
        )
        auth = required_element(root, "AUTH_EX", operation="/avs/auth_ex").get("auth", "")
        token = required_element(root, "LOGIN", operation="/avs/auth_ex").get("session", "")
        if not auth or not token:
            raise ProtocolError(
                "Missing session credentials",
                reason="missing_session_credentials",
                operation="/avs/auth_ex",
            )
        self._auth, self._token = auth, token

    async def _read(self, endpoint: str, extra: dict[str, str] | None = None) -> ET.Element:
        return await self._post(
            endpoint,
            {
                "auth": self._auth,
                "session": self._token,
                **(extra or {}),
            },
        )

    async def _description(self, item_id: str, kind: str) -> str:
        key = (kind, item_id)
        if key not in self._names:
            try:
                root = await self._read(
                    "/avs/get_desc",
                    {
                        "id": item_id,
                        "type": kind,
                        "appfev": "43",
                    },
                )
                name = unquote_plus(required_element(root, "GET_DESC").get("desc", ""))
            except CannotConnect, AccountError:
                name = ""  # Optional metadata; don't retry for every poll.
            self._names[key] = name
        return self._names[key]

    async def _snapshot(self) -> Snapshot:
        # No parallel requests to a central alarm session.
        sector_xml = await self._read("/avs/get_sectors")
        zone_xml = await self._read("/avs/get_zones")
        snapshot = parse_snapshot(sector_xml, zone_xml)
        sectors = {}
        for item_id, sector in snapshot.sectors.items():
            sectors[item_id] = replace(sector, name=await self._description(item_id, "4"))
        zones = {}
        for item_id, zone in snapshot.zones.items():
            zones[item_id] = replace(zone, name=await self._description(item_id, "1"))
        return Snapshot(sectors, zones)

    async def async_snapshot(self) -> Snapshot:
        async with self._lock:
            return await self._snapshot_with_renewal()

    async def _snapshot_with_renewal(self) -> Snapshot:
        """Read under the caller's lock; only reads may be retried automatically."""
        if not self._token:
            await self._login()
        try:
            return await self._snapshot()
        except SessionExpired:
            self._auth = self._token = ""
            await self._login()
            try:
                return await self._snapshot()
            except SessionExpired:
                self._auth = self._token = ""
                raise CannotConnect(
                    "Session was rejected after renewal", reason="session_rejected_after_renewal"
                ) from None

    async def async_set_sector_mode(self, sector_id: str, mode: int) -> None:
        """Send one checked command, never automatically replay a write."""
        if not re.fullmatch(r"[0-9]+", sector_id) or int(sector_id) == 0:
            raise CommandRejected("A single nonzero sector is required")
        if type(mode) is not int or mode not in range(5):
            raise CommandRejected("Unsupported AVS mode")
        async with self._lock:
            snapshot = await self._snapshot_with_renewal()
            sector = snapshot.sectors.get(sector_id)
            if sector is None or mode not in sector.allowed_modes:
                raise CommandRejected("This mode is not permitted for the sector")
            try:
                root = await self._read(
                    "/avs/set_sectors",
                    {"sectors": f"{sector_id},{mode}", "check": "1", "checkzone": "1"},
                )
            except SessionExpired:
                self._auth = self._token = ""
                raise CannotConnect(
                    "Command session expired; refresh before trying again",
                    reason="command_session_expired",
                    operation="/avs/set_sectors",
                ) from None
            result = required_element(root, "SET_SECTORS", operation="/avs/set_sectors")
            if result.get("status") != "0":
                # Never expose errstr, bypass checks or retry with checkzone=0.
                raise CommandRejected("Panel refused the command; check zones in the official app")

    async def async_set_zone_excluded(self, zone_id: str, excluded: bool) -> None:
        """Exclude/include a single inactive zone, as in the Android zone detail page."""
        if not re.fullmatch(r"[0-9]+", zone_id) or int(zone_id) == 0:
            raise CommandRejected("A single nonzero zone is required")
        if type(excluded) is not bool:
            raise CommandRejected("Exclusion must be a boolean")
        async with self._lock:
            snapshot = await self._snapshot_with_renewal()
            zone = snapshot.zones.get(zone_id)
            if zone is None or zone.flags is None:
                raise CommandRejected("Zone state is unavailable")
            if zone.bit(3):
                raise CommandRejected("An active zone cannot be excluded or included")
            if zone.bit(2) == excluded:
                return
            try:
                root = await self._read("/avs/set_zones", {"zones": f"{zone_id},{int(excluded)}"})
            except SessionExpired:
                self._auth = self._token = ""
                raise CannotConnect(
                    "Command session expired; refresh before trying again",
                    reason="command_session_expired",
                    operation="/avs/set_zones",
                ) from None
            if required_element(root, "SET_ZONES", operation="/avs/set_zones").get("status") != "0":
                raise CommandRejected("Panel refused the zone command")

    async def async_close(self) -> None:
        async with self._lock:
            try:
                if self._token:
                    async with asyncio.timeout(10):
                        await self._read("/avs/logout")
            except AvsError, TimeoutError:
                pass
            finally:
                self._auth = self._token = ""
