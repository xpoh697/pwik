"""Sensor platform for PWiK Piaseczno iBOK."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    BASE_URL,
    CONF_SOURCE_SENSORS,
    DOMAIN,
    STATUS_APPROVED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from .coordinator import PwikDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PWiK sensors based on a config entry."""
    coordinator: PwikDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    meters = coordinator.data.get("meters", {})

    entities: list[SensorEntity] = []
    for meter_num in meters:
        entities.extend(
            [
                PwikLastReadingSensor(coordinator, entry, meter_num),
                PwikLastReadingDateSensor(coordinator, entry, meter_num),
                PwikSubmissionStatusSensor(coordinator, entry, meter_num),
                PwikPendingReadingSensor(coordinator, entry, meter_num),
                PwikConsumptionSinceLastSensor(coordinator, entry, meter_num),
            ]
        )

    async_add_entities(entities)


class PwikBaseEntity(CoordinatorEntity[PwikDataUpdateCoordinator]):
    """Base entity for PWiK water meter."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PwikDataUpdateCoordinator,
        entry: ConfigEntry,
        meter_id: str,
        entity_type: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._entry = entry
        self._meter_id = meter_id
        self._entity_type = entity_type
        self._attr_unique_id = f"{DOMAIN}_{meter_id}_{entity_type}"

    @property
    def meter_data(self) -> dict[str, Any]:
        """Get latest data for this meter."""
        return self.coordinator.data.get("meters", {}).get(self._meter_id, {})

    @property
    def device_info(self) -> DeviceInfo:
        """Return unified device information."""
        meter_type = "Główny" if self.meter_data.get("fl_podl") == "N" else "Podlicznik"
        return DeviceInfo(
            identifiers={(DOMAIN, self._meter_id)},
            name=f"Wodomierz {self._meter_id} ({meter_type})",
            manufacturer="PWiK Piaseczno",
            model=f"Wodomierz {meter_type}",
            serial_number=self._meter_id,
            configuration_url=BASE_URL,
        )


class PwikLastReadingSensor(PwikBaseEntity, SensorEntity):
    """Sensor for the last confirmed water reading."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_icon = "mdi:counter"
    _attr_translation_key = "last_reading"

    def __init__(
        self, coordinator: PwikDataUpdateCoordinator, entry: ConfigEntry, meter_id: str
    ) -> None:
        super().__init__(coordinator, entry, meter_id, "last_reading")
        self._attr_name = "Последнее показание"

    @property
    def native_value(self) -> float | None:
        """Return last confirmed reading."""
        val = self.meter_data.get("sl")
        return float(val) if val is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes."""
        return {
            "meter_number": self._meter_id,
            "meter_id_wodom": self.meter_data.get("id_wodom"),
            "reading_id": self.meter_data.get("io"),
            "address": self.meter_data.get("adres"),
        }


class PwikLastReadingDateSensor(PwikBaseEntity, SensorEntity):
    """Sensor for the date of the last confirmed reading."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:calendar-clock"
    _attr_translation_key = "last_reading_date"

    def __init__(
        self, coordinator: PwikDataUpdateCoordinator, entry: ConfigEntry, meter_id: str
    ) -> None:
        super().__init__(coordinator, entry, meter_id, "last_reading_date")
        self._attr_name = "Дата последнего показания"

    @property
    def native_value(self) -> str | None:
        """Return the date string."""
        return self.meter_data.get("do")


class PwikSubmissionStatusSensor(PwikBaseEntity, SensorEntity):
    """Sensor for the submission status of the meter."""

    _attr_icon = "mdi:cloud-upload-outline"
    _attr_translation_key = "submission_status"

    def __init__(
        self, coordinator: PwikDataUpdateCoordinator, entry: ConfigEntry, meter_id: str
    ) -> None:
        super().__init__(coordinator, entry, meter_id, "submission_status")
        self._attr_name = "Статус передачи показаний"

    @property
    def native_value(self) -> str:
        """Return status string."""
        ist = str(self.meter_data.get("ist", ""))
        mapping = {
            "1": STATUS_PENDING,
            "2": STATUS_IN_PROGRESS,
            "3": STATUS_REJECTED,
            "4": STATUS_APPROVED,
        }
        return mapping.get(ist, "allowed")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed attributes."""
        return {
            "meter_type": "Główny (N)" if self.meter_data.get("fl_podl") == "N" else "Podlicznik (P)",
            "legalization_valid_to": self.meter_data.get("leg_do"),
            "address": self.meter_data.get("adres"),
            "admin_comment": self.meter_data.get("tkom"),
            "client_comment": self.meter_data.get("kkom"),
            "raw_status_code": self.meter_data.get("ist"),
        }


class PwikPendingReadingSensor(PwikBaseEntity, SensorEntity):
    """Sensor for current pending reading awaiting confirmation."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_icon = "mdi:clock-outline"
    _attr_translation_key = "pending_reading"

    def __init__(
        self, coordinator: PwikDataUpdateCoordinator, entry: ConfigEntry, meter_id: str
    ) -> None:
        super().__init__(coordinator, entry, meter_id, "pending_reading")
        self._attr_name = "Текущая поданная заявка"

    @property
    def native_value(self) -> float | None:
        """Return pending reading value."""
        val = self.meter_data.get("isl")
        return float(val) if val is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return submission details."""
        return {
            "submission_date": self.meter_data.get("ido"),
            "submission_id": self.meter_data.get("id"),
        }


class PwikConsumptionSinceLastSensor(PwikBaseEntity, SensorEntity):
    """Sensor calculating real-time water consumption since last billing reading."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_icon = "mdi:water-sync"
    _attr_translation_key = "consumption_since_last_reading"

    def __init__(
        self, coordinator: PwikDataUpdateCoordinator, entry: ConfigEntry, meter_id: str
    ) -> None:
        super().__init__(coordinator, entry, meter_id, "consumption_since_last_reading")
        self._attr_name = "Расход с момента последнего показания"

    @property
    def native_value(self) -> float | None:
        """Calculate consumption based on linked HA source sensor."""
        source_sensors = self._entry.options.get(
            CONF_SOURCE_SENSORS,
            self._entry.data.get(CONF_SOURCE_SENSORS, {}),
        )
        source_entity = source_sensors.get(self._meter_id)
        if not source_entity:
            return None

        state = self.hass.states.get(source_entity)
        if not state or state.state in ("unknown", "unavailable"):
            return None

        try:
            curr_val = float(state.state)
            last_billing_val = float(self.meter_data.get("sl", 0))
            return max(0.0, round(curr_val - last_billing_val, 3))
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return linked source sensor."""
        source_sensors = self._entry.options.get(
            CONF_SOURCE_SENSORS,
            self._entry.data.get(CONF_SOURCE_SENSORS, {}),
        )
        return {
            "source_sensor": source_sensors.get(self._meter_id),
        }
