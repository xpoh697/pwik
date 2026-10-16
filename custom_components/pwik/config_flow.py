"""Config flow for PWiK Piaseczno iBOK integration."""
from __future__ import annotations

from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .api import PwikApiClient, PwikApiError, PwikAuthError
from .const import (
    CONF_SOURCE_SENSORS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)


class PwikConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PWiK iBOK."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._username: str | None = None
        self._password: str | None = None
        self._meters: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: Authenticate with username and password."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD].strip()

            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            client = PwikApiClient(session, username, password)

            try:
                await client.login(force_kill=True)
                data = await client.get_data()
                self._meters = list(data["meters"].values())
                self._username = username
                self._password = password

                if self._meters:
                    return await self.async_step_sensors()

                return self.async_create_entry(
                    title=f"PWiK ({username})",
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                    },
                )
            except PwikAuthError:
                errors["base"] = "invalid_auth"
            except PwikApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): cv.string,
                    vol.Required(CONF_PASSWORD): cv.string,
                }
            ),
            errors=errors,
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: Link local water sensors to discovered meters."""
        if user_input is not None:
            source_sensors = {
                m["numer_fabryczny"]: user_input.get(f"sensor_{m['numer_fabryczny']}")
                for m in self._meters
                if user_input.get(f"sensor_{m['numer_fabryczny']}")
            }

            return self.async_create_entry(
                title=f"PWiK ({self._username})",
                data={
                    CONF_USERNAME: self._username,
                    CONF_PASSWORD: self._password,
                    CONF_SOURCE_SENSORS: source_sensors,
                },
            )

        fields: dict[Any, Any] = {}
        for m in self._meters:
            meter_num = m["numer_fabryczny"]
            meter_type = "Główny" if m.get("fl_podl") == "N" else "Podlicznik"
            fields[vol.Optional(f"sensor_{meter_num}", description={"suggested_value": ""})] = cv.string

        return self.async_show_form(
            step_id="sensors",
            data_schema=vol.Schema(fields),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return PwikOptionsFlowHandler(config_entry)


class PwikOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for PWiK."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]
        meters = coordinator.data.get("meters", {})

        fields: dict[Any, Any] = {
            vol.Optional(
                CONF_UPDATE_INTERVAL,
                default=self._config_entry.options.get(
                    CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                ),
            ): cv.positive_int,
        }

        saved_sensors = self._config_entry.options.get(
            CONF_SOURCE_SENSORS,
            self._config_entry.data.get(CONF_SOURCE_SENSORS, {}),
        )

        for meter_num in meters:
            fields[
                vol.Optional(
                    f"sensor_{meter_num}",
                    default=saved_sensors.get(meter_num, ""),
                )
            ] = cv.string

        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields))
