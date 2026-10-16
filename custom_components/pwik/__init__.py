"""The PWiK Piaseczno iBOK integration."""
from __future__ import annotations

from datetime import date
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .api import PwikApiClient
from .const import CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN
from .coordinator import PwikDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]

SERVICE_SUBMIT_READING = "submit_reading"
SERVICE_CANCEL_READING = "cancel_reading"

SUBMIT_READING_SCHEMA = vol.Schema(
    {
        vol.Required("value"): vol.Any(cv.positive_float, cv.string),
        vol.Optional("meter_id"): cv.string,
        vol.Optional("date"): cv.string,
        vol.Optional("comment", default="Podano przez Home Assistant"): cv.string,
    }
)

CANCEL_READING_SCHEMA = vol.Schema(
    {
        vol.Optional("meter_id"): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PWiK Piaseczno from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    session = async_get_clientsession(hass)
    api = PwikApiClient(
        session=session,
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
    )

    update_interval = entry.options.get(
        CONF_UPDATE_INTERVAL,
        entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
    )

    coordinator = PwikDataUpdateCoordinator(
        hass,
        api=api,
        update_interval=update_interval,
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async def handle_submit_reading(call: ServiceCall) -> None:
        """Handle submit reading service call."""
        value = call.data["value"]
        meter_id = call.data.get("meter_id")
        date_str = call.data.get("date") or date.today().isoformat()
        comment = call.data.get("comment", "Podano przez Home Assistant")

        meters = coordinator.data.get("meters", {})
        if not meter_id:
            if len(meters) == 1:
                meter_id = next(iter(meters.keys()))
            else:
                raise HomeAssistantError(
                    f"Multiple meters found ({list(meters.keys())}). Please specify meter_id."
                )

        await coordinator.api.submit_reading(
            meter_id=meter_id,
            value=value,
            date_str=date_str,
            comment=comment,
        )
        await coordinator.async_request_refresh()

    async def handle_cancel_reading(call: ServiceCall) -> None:
        """Handle cancel reading service call."""
        meter_id = call.data.get("meter_id")
        meters = coordinator.data.get("meters", {})
        if not meter_id:
            if len(meters) == 1:
                meter_id = next(iter(meters.keys()))
            else:
                raise HomeAssistantError(
                    f"Multiple meters found ({list(meters.keys())}). Please specify meter_id."
                )

        await coordinator.api.cancel_reading(meter_id=meter_id)
        await coordinator.async_request_refresh()

    if not hass.services.has_service(DOMAIN, SERVICE_SUBMIT_READING):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SUBMIT_READING,
            handle_submit_reading,
            schema=SUBMIT_READING_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_CANCEL_READING):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CANCEL_READING,
            handle_cancel_reading,
            schema=CANCEL_READING_SCHEMA,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
