"""UI setup, installation selection, reauthentication and options."""

import logging
import re
import secrets

try:
    import probatio as vol
except ImportError:
    import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import AccountError, AvsClient, AvsError, CannotConnect, InvalidAuth, Plant, ProtocolError
from .const import (
    CONF_DEVICE_ID,
    CONF_ENABLED_MODES,
    CONF_PIN,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_SCAN_INTERVAL,
    DEFAULT_ENABLED_MODES,
    DEFAULT_MODE_MAP,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

SECRET = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
LOGGER = logging.getLogger(__name__)


def credentials_schema(*, username: str = "", pin: bool = False) -> vol.Schema:
    schema = {
        vol.Required(CONF_USERNAME, default=username): str,
        vol.Required(CONF_PASSWORD): SECRET,
    }
    if pin:
        schema[vol.Required(CONF_PIN)] = SECRET
    else:
        schema[vol.Optional(CONF_DEVICE_ID)] = str
    return vol.Schema(schema)


def error_key(error: AvsError) -> str:
    LOGGER.warning(
        "AVS setup failed: operation=%s category=%s reason=%s",
        error.operation,
        type(error).__name__,
        error.reason,
    )
    if isinstance(error, InvalidAuth):
        return "invalid_auth"
    if isinstance(error, AccountError):
        return "account_error"
    if isinstance(error, ProtocolError):
        return "protocol_error"
    specific = {
        "TOO-MANY-USERS": "too_many_users",
        "http_429": "rate_limited",
        "timeout": "timeout",
        "tls_error": "tls_error",
        "COMMUNICATION-ERROR": "panel_unreachable",
        "EQUIPMENT-NOT-FOUND": "panel_unreachable",
        "session_rejected_after_renewal": "session_error",
    }
    if error.reason in specific:
        return specific[error.reason]
    if isinstance(error, CannotConnect):
        return "cannot_connect"
    return "unknown"


class AvsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict = {}
        self._device_id = secrets.token_hex(8)
        self._plants: list[Plant] = []

    def _client(
        self,
        credentials: dict,
        *,
        plant: Plant | None = None,
        pin: str = "",
        device_id: str | None = None,
    ) -> AvsClient:
        return AvsClient(
            async_get_clientsession(self.hass),
            credentials[CONF_USERNAME],
            credentials[CONF_PASSWORD],
            device_id or self._device_id,
            pin=pin,
            plant=plant,
        )

    async def async_step_user(self, user_input: dict | None = None):
        errors = {}
        if user_input is not None:
            entered_id = user_input.get(CONF_DEVICE_ID, "").strip()
            if entered_id and not re.fullmatch(r"[a-f0-9]{16}", entered_id):
                errors[CONF_DEVICE_ID] = "invalid_device_id"
            elif not user_input[CONF_USERNAME].strip() or not user_input[CONF_PASSWORD].strip():
                errors["base"] = "invalid_auth"
            else:
                if entered_id:
                    self._device_id = entered_id
                self._credentials = {
                    CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                    CONF_PASSWORD: user_input[CONF_PASSWORD].strip(),
                }
                client = self._client(self._credentials)
                try:
                    self._plants = await client.async_list_plants()
                except AvsError as error:
                    errors["base"] = error_key(error)
                else:
                    return await self.async_step_plant()
        return self.async_show_form(step_id="user", data_schema=credentials_schema(), errors=errors)

    async def async_step_plant(self, user_input: dict | None = None):
        errors = {}
        if user_input is not None:
            plant = next((p for p in self._plants if p.id == user_input[CONF_PLANT_ID]), None)
            pin = user_input[CONF_PIN].strip()
            if plant is None:
                errors["base"] = "cannot_connect"
            elif not pin or not pin.isascii() or not pin.isdigit():
                errors[CONF_PIN] = "invalid_pin"
            else:
                # Abort duplicates before opening or registering another alarm session.
                await self.async_set_unique_id(plant.id)
                self._abort_if_unique_id_configured()
                client = self._client(self._credentials, plant=plant, pin=pin)
                try:
                    await client.async_snapshot()
                except AvsError as error:
                    errors["base"] = error_key(error)
                else:
                    return self.async_create_entry(
                        title=plant.name or "AVS",
                        data={
                            **self._credentials,
                            CONF_PIN: pin,
                            CONF_PLANT_ID: plant.id,
                            CONF_PLANT_NAME: plant.name,
                            CONF_DEVICE_ID: self._device_id,
                        },
                    )
                finally:
                    await client.async_close()
        choices = [
            {"value": plant.id, "label": plant.name or f"Plant {index}"}
            for index, plant in enumerate(self._plants, 1)
        ]
        return self.async_show_form(
            step_id="plant",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PLANT_ID, default=self._plants[0].id): SelectSelector(
                        SelectSelectorConfig(options=choices)
                    ),
                    vol.Required(CONF_PIN): SECRET,
                }
            ),
        )

    async def async_step_reauth(self, entry_data: dict):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict | None = None):
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            pin = user_input[CONF_PIN].strip()
            if not pin or not pin.isascii() or not pin.isdigit():
                errors[CONF_PIN] = "invalid_pin"
            else:
                credentials = {
                    key: user_input[key].strip() for key in (CONF_USERNAME, CONF_PASSWORD)
                }
                client = self._client(credentials, pin=pin, device_id=entry.data[CONF_DEVICE_ID])
                try:
                    plants = await client.async_list_plants()
                    plant = next((p for p in plants if p.id == entry.data[CONF_PLANT_ID]), None)
                    if plant is None:
                        return self.async_abort(reason="plant_not_found")
                    client.plant = plant
                    await client.async_snapshot()
                except AvsError as error:
                    errors["base"] = error_key(error)
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={
                            **credentials,
                            CONF_PIN: pin,
                            CONF_PLANT_NAME: plant.name,
                        },
                    )
                finally:
                    await client.async_close()
        return self.async_show_form(
            step_id="reauth_confirm",
            errors=errors,
            data_schema=credentials_schema(username=entry.data[CONF_USERNAME], pin=True),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AvsOptionsFlow()


class AvsOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict | None = None):
        errors = {}
        if user_input is not None:
            enabled = user_input.get(CONF_ENABLED_MODES, DEFAULT_ENABLED_MODES)
            modes = [user_input["mode_" + mode.lower()] for mode in enabled]
            if len(set(modes)) == len(modes):
                return self.async_create_entry(title="", data=user_input)
            errors["base"] = "duplicate_modes"
        current = user_input if user_input is not None else self.config_entry.options
        fields = {
            vol.Required(
                CONF_ENABLED_MODES,
                default=current.get(CONF_ENABLED_MODES, DEFAULT_ENABLED_MODES),
            ): SelectSelector(SelectSelectorConfig(options=DEFAULT_ENABLED_MODES, multiple=True)),
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)),
        }
        states = [
            "armed_away",
            "armed_home",
            "armed_night",
            "armed_custom_bypass",
            "armed_vacation",
        ]
        for key, default in DEFAULT_MODE_MAP.items():
            fields[vol.Required(key, default=current.get(key, default))] = SelectSelector(
                SelectSelectorConfig(options=states, translation_key="alarm_mode")
            )
        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields), errors=errors)
