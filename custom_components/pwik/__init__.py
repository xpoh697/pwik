"""The PWiK Piaseczno iBOK integration."""
from __future__ import annotations

import asyncio
from datetime import date
import logging
import math
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .api import PwikApiClient
from .const import CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN
from .coordinator import PwikDataUpdateCoordinator
from .sensor import get_source_sensor

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]

SERVICE_SUBMIT_READING = "submit_reading"
SERVICE_CANCEL_READING = "cancel_reading"


def validate_reading_value(value: Any) -> float:
    """Validate that value can be converted to a positive finite float."""
    if value is None:
        raise vol.Invalid("Значение показания не может быть пустым")
    cleaned = str(value).strip().split()[0].replace(",", ".")
    try:
        val = float(cleaned)
    except (ValueError, TypeError):
        raise vol.Invalid(f"Показание счетчика должно быть числом, получено: '{value}'")
    if math.isnan(val) or math.isinf(val) or val < 0:
        raise vol.Invalid(f"Показание счетчика должно быть положительным конечным числом, получено: {val}")
    return val


SUBMIT_READING_SCHEMA = vol.Schema(
    {
        vol.Optional("value"): validate_reading_value,
        vol.Optional("meter_id"): cv.string,
        vol.Optional("date"): cv.string,
        vol.Optional("comment", default=""): cv.string,
    }
)

CANCEL_READING_SCHEMA = vol.Schema(
    {
        vol.Optional("meter_id"): cv.string,
    }
)


async def _async_clean_pwik_registry_entries(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean unwanted address prefixes from entity IDs and areas."""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    area_reg = ar.async_get(hass)

    pwik_device_ids = set()
    for device in list(dev_reg.devices.values()):
        if any(ident[0] == DOMAIN for ident in device.identifiers):
            pwik_device_ids.add(device.id)
            if device.area_id and ("lidii_wysockiej" in device.area_id or "julianow" in device.area_id):
                dev_reg.async_update_device(device.id, area_id=None)

    # Clean up empty area if no other user devices are in it
    area = area_reg.async_get_area("lidii_wysockiej_35_05_500_julianow")
    if area:
        other_devices = [
            d for d in dev_reg.devices.values()
            if d.area_id == area.id and d.id not in pwik_device_ids
        ]
        if not other_devices:
            area_reg.async_delete(area.id)

    # Clean entity IDs and update names in entity registry
    for reg_entity in list(ent_reg.entities.values()):
        if reg_entity.platform == DOMAIN:
            # 1. Clean address prefix if present
            if "lidii_wysockiej" in reg_entity.entity_id or "julianow" in reg_entity.entity_id:
                clean_id = reg_entity.entity_id.replace("lidii_wysockiej_35_05_500_julianow_", "")
                if clean_id != reg_entity.entity_id and ent_reg.async_get(clean_id) is None:
                    try:
                        ent_reg.async_update_entity(reg_entity.entity_id, new_entity_id=clean_id)
                        _LOGGER.info("Migrated entity_id from %s to %s", reg_entity.entity_id, clean_id)
                    except Exception as ex:
                        _LOGGER.warning("Could not rename entity %s to %s: %s", reg_entity.entity_id, clean_id, ex)

            # 2. Update custom name if it had the old name
            if reg_entity.translation_key == "pending_reading" and reg_entity.name == "Текущая поданная заявка":
                try:
                    ent_reg.async_update_entity(reg_entity.entity_id, name="Последнее поданное показание")
                except Exception:
                    pass


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

    # Clean unwanted address prefix from registry before forwarding setups
    await _async_clean_pwik_registry_entries(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async def handle_submit_reading(call: ServiceCall) -> None:
        """Handle submit reading service call."""
        meter_id = call.data.get("meter_id")
        date_str = call.data.get("date") or date.today().isoformat()
        comment = call.data.get("comment", "")

        meters = coordinator.data.get("meters", {})
        target_meters = [meter_id] if meter_id else list(meters.keys())

        if not target_meters:
            raise HomeAssistantError("No water meters found in PWiK account")

        # Disallow ambiguous value without meter_id in multi-meter setup
        if "value" in call.data and call.data["value"] is not None and not meter_id and len(target_meters) > 1:
            raise HomeAssistantError("При указании фиксированного 'value' необходимо также указать 'meter_id'")

        success_count = 0
        errors: list[str] = []

        for idx, m_id in enumerate(target_meters):
            if "value" in call.data and call.data["value"] is not None:
                val_to_submit: float | str = call.data["value"]
            else:
                source_entity = get_source_sensor(entry, m_id)
                if not source_entity:
                    msg = f"Локальный сенсор расхода воды для счетчика {m_id} не настроен"
                    if len(target_meters) == 1:
                        raise HomeAssistantError(msg)
                    _LOGGER.warning(msg)
                    errors.append(msg)
                    continue

                state = hass.states.get(source_entity)
                if not state or state.state in ("unknown", "unavailable"):
                    msg = f"Локальный сенсор '{source_entity}' для счетчика {m_id} недоступен (состояние: {state.state if state else 'None'})"
                    if len(target_meters) == 1:
                        raise HomeAssistantError(msg)
                    _LOGGER.warning(msg)
                    errors.append(msg)
                    continue

                try:
                    clean_state = state.state.strip().split()[0].replace(",", ".")
                    curr_val = float(clean_state)
                    uom = str(state.attributes.get("unit_of_measurement", "")).lower()
                    if uom in ("l", "литр", "литра", "литров", "dm3", "dm³"):
                        curr_val = round(curr_val / 1000.0, 3)
                    if math.isnan(curr_val) or math.isinf(curr_val) or curr_val < 0:
                        raise ValueError(f"Invalid numeric value {curr_val}")
                    val_to_submit = curr_val
                except (ValueError, TypeError):
                    msg = f"Состояние локального сенсора '{source_entity}' не является числом (значение: '{state.state}')"
                    if len(target_meters) == 1:
                        raise HomeAssistantError(msg)
                    _LOGGER.warning(msg)
                    errors.append(msg)
                    continue

            try:
                await coordinator.api.submit_reading(
                    meter_id=m_id,
                    value=val_to_submit,
                    date_str=date_str,
                    comment=comment,
                )
                success_count += 1
            except Exception as err:
                _LOGGER.warning("Ошибка при отправке показаний счетчика %s: %s", m_id, err)
                errors.append(f"{m_id}: {err}")
                if len(target_meters) == 1:
                    raise HomeAssistantError(str(err)) from err

            # Delay between multiple meter submissions to prevent server session clash
            if idx < len(target_meters) - 1:
                await asyncio.sleep(2)

        await coordinator.async_request_refresh()

        if success_count == 0 and errors:
            raise HomeAssistantError(f"Не удалось передать показания счетчиков: {'; '.join(errors)}")

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

    # Listen for option changes
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
