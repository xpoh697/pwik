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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
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


class PwikBaseSensor(CoordinatorEntity[PwikDataUpdateCoordinator], SensorEntity):
    """Base sensor for PWiK."""

    def __init__(
        self,
        coordinator: PwikDataUpdateCoordinator,
        entry: ConfigEntry,
        meter_id: str,
        sensor_type: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._entry = entry
        self._meter_id = meter_id
        self._sensor_type = sensor_type
        self._attr_unique_id = f"{DOMAIN}_{meter_id}_{sensor_type}"
        self._attr_has_entity_name = True

    @property
    def meter_data(self) -> dict[str, Any]:
        """Get latest data for this meter."""
        return self.coordinator.data.get("meters", {}).get(self._meter_id, {})

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        meter_type = "Główny" if self.meter_data.get("fl_podl") == "N" else "Podlicznik"
        return DeviceInfo(
            identifiers={(DOMAIN, self._meter_id)},
            name=f"Wodomierz {self._meter_id} ({meter_type})",
            manufacturer="PWiK Piaseczno",
            model=f"Wodomierz {meter_type}",
            suggested_area=self.meter_data.get("adres", "Dom"),
        )


class PwikLastReadingSensor(PwikBaseSensor):
    """Sensor for the last confirmed water reading."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_translation_key = "last_reading"

    def __init__(self, coordinator: PwikDataUpdateCoordinator, entry: ConfigEntry, meter_id: str) -> None:
        super().__init__(coordinator, entry, meter_id, "last_reading")

    @property
    def native_value(self) -> float | None:
        """Return last confirmed reading."""
        val = self.meter_data.get("sl")
        return float(val) if val is not None else None


class PwikLastReadingDateSensor(PwikBaseSensor):
    """Sensor for the date of the last confirmed reading."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_translation_key = "last_reading_date"

    def __init__(self, coordinator: PwikDataUpdateCoordinator, entry: ConfigEntry, meter_id: str) -> None:
        super().__init__(coordinator, entry, meter_id, "last_reading_date")

    @property
    def native_value(self) -> str | None:
        """Return the date string."""
        return self.meter_data.get("do")


class PwikSubmissionStatusSensor(PwikBaseSensor):
    """Sensor for the submission status of the meter."""

    _attr_translation_key = "submission_status"

    def __init__(self, coordinator: PwikDataUpdateCoordinator, entry: ConfigEntry, meter_id: str) -> None:
        super().__init__(coordinator, entry, meter_id, "submission_status")

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
            "meter_type": self.meter_data.get("fl_podl"),
            "legalization_valid_to": self.meter_data.get("leg_do"),
            "address": self.meter_data.get("adres"),
            "admin_comment": self.meter_data.get("tkom"),
        }


class PwikPendingReadingSensor(PwikBaseSensor):
    """Sensor for current pending reading awaiting confirmation."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_translation_key = "pending_reading"

    def __init__(self, coordinator: PwikDataUpdateCoordinator, entry: ConfigEntry, meter_id: str) -> None:
        super().__init__(coordinator, entry, meter_id, "pending_reading")

    @property
    def native_value(self) -> float | None:
        """Return pending reading value."""
        val = self.meter_data.get("isl")
        return float(val) if val is not None else None


class PwikConsumptionSinceLastSensor(PwikBaseSensor):
    """Sensor calculating real-time water consumption since last billing reading."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_translation_key = "consumption_since_last_reading"

    def __init__(self, coordinator: PwikDataUpdateCoordinator, entry: ConfigEntry, meter_id: str) -> None:
        super().__init__(coordinator, entry, meter_id, "consumption_since_last_reading")

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
