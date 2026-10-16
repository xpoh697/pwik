"""Button platform for PWiK Piaseczno iBOK."""
from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_SOURCE_SENSORS, DOMAIN
from .coordinator import PwikDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PWiK buttons based on a config entry."""
    coordinator: PwikDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    meters = coordinator.data.get("meters", {})

    buttons: list[ButtonEntity] = []
    for meter_num in meters:
        buttons.extend(
            [
                PwikSubmitReadingButton(coordinator, entry, meter_num),
                PwikCancelReadingButton(coordinator, entry, meter_num),
            ]
        )

    async_add_entities(buttons)


class PwikSubmitReadingButton(ButtonEntity):
    """Button to submit the reading from the linked source sensor."""

    _attr_has_entity_name = True
    _attr_translation_key = "submit_reading"

    def __init__(
        self,
        coordinator: PwikDataUpdateCoordinator,
        entry: ConfigEntry,
        meter_id: str,
    ) -> None:
        """Initialize."""
        self._coordinator = coordinator
        self._entry = entry
        self._meter_id = meter_id
        self._attr_unique_id = f"{DOMAIN}_{meter_id}_submit_reading"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._meter_id)},
            name=f"Wodomierz {self._meter_id}",
        )

    async def async_press(self) -> None:
        """Handle button press."""
        source_sensors = self._entry.options.get(
            CONF_SOURCE_SENSORS,
            self._entry.data.get(CONF_SOURCE_SENSORS, {}),
        )
        source_entity = source_sensors.get(self._meter_id)
        if not source_entity:
            raise HomeAssistantError(
                f"No source sensor configured for meter {self._meter_id}. Please configure it in options."
            )

        state = self.hass.states.get(source_entity)
        if not state or state.state in ("unknown", "unavailable"):
            raise HomeAssistantError(f"Source sensor {source_entity} is unavailable")

        today_str = date.today().isoformat()
        await self._coordinator.api.submit_reading(
            meter_id=self._meter_id,
            value=state.state,
            date_str=today_str,
            comment="Submitted via Home Assistant Button",
        )
        await self._coordinator.async_request_refresh()


class PwikCancelReadingButton(ButtonEntity):
    """Button to cancel a pending reading submission."""

    _attr_has_entity_name = True
    _attr_translation_key = "cancel_reading"

    def __init__(
        self,
        coordinator: PwikDataUpdateCoordinator,
        entry: ConfigEntry,
        meter_id: str,
    ) -> None:
        """Initialize."""
        self._coordinator = coordinator
        self._entry = entry
        self._meter_id = meter_id
        self._attr_unique_id = f"{DOMAIN}_{meter_id}_cancel_reading"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._meter_id)},
            name=f"Wodomierz {self._meter_id}",
        )

    async def async_press(self) -> None:
        """Handle button press."""
        await self._coordinator.api.cancel_reading(self._meter_id)
        await self._coordinator.async_request_refresh()
