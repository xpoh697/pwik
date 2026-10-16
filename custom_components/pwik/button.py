"""Button platform for PWiK Piaseczno iBOK."""
from __future__ import annotations

import asyncio
from datetime import date
import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_SOURCE_SENSORS, DOMAIN
from .coordinator import PwikDataUpdateCoordinator
from .sensor import PwikBaseEntity, get_source_sensor

_LOGGER = logging.getLogger(__name__)


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


class PwikSubmitReadingButton(PwikBaseEntity, ButtonEntity):
    """Button to submit the reading from the linked source sensor."""

    _attr_icon = "mdi:water-pump"
    _attr_translation_key = "submit_reading"

    def __init__(
        self,
        coordinator: PwikDataUpdateCoordinator,
        entry: ConfigEntry,
        meter_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry, meter_id, "submit_reading")
        self._attr_name = "Подать показания"
        self._lock = asyncio.Lock()

    async def async_press(self) -> None:
        """Handle button press."""
        if self._lock.locked():
            _LOGGER.warning("Запрос на отправку показаний уже выполняется")
            return

        async with self._lock:
            source_entity = get_source_sensor(self._entry, self._meter_id)
            if not source_entity:
                raise HomeAssistantError(
                    f"Локальный датчик расхода воды для счетчика {self._meter_id} не настроен. "
                    "Укажите его в параметрах интеграции (Настройки -> Интеграции -> PWiK -> Настроить)."
                )

            state = self.hass.states.get(source_entity)
            if not state or state.state in ("unknown", "unavailable"):
                raise HomeAssistantError(
                    f"Локальный датчик воды '{source_entity}' недоступен (состояние: {state.state if state else 'None'})"
                )

            try:
                curr_val = float(state.state)
                uom = str(state.attributes.get("unit_of_measurement", "")).lower()
                if uom in ("l", "литр", "литра", "литров", "dm3", "dm³"):
                    curr_val = round(curr_val / 1000.0, 3)
                submit_val: float | str = curr_val
            except (ValueError, TypeError):
                submit_val = state.state

            today_str = date.today().isoformat()
            await self.coordinator.api.submit_reading(
                meter_id=self._meter_id,
                value=submit_val,
                date_str=today_str,
                comment="Подано через кнопку Home Assistant",
            )
            await self.coordinator.async_request_refresh()


class PwikCancelReadingButton(PwikBaseEntity, ButtonEntity):
    """Button to cancel a pending reading submission."""

    _attr_icon = "mdi:cancel"
    _attr_translation_key = "cancel_reading"

    def __init__(
        self,
        coordinator: PwikDataUpdateCoordinator,
        entry: ConfigEntry,
        meter_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry, meter_id, "cancel_reading")
        self._attr_name = "Отменить поданное показание"
        self._lock = asyncio.Lock()

    async def async_press(self) -> None:
        """Handle button press."""
        if self._lock.locked():
            return

        async with self._lock:
            await self.coordinator.api.cancel_reading(self._meter_id)
            await self.coordinator.async_request_refresh()
