"""Sensor platform for HP Printer Monitor integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ALL_SUBUNIT_SENSORS,
    CONF_DAYLIST_DAYS,
    DEFAULT_DAYLIST_DAYS,
    INK_COLORS,
    DOMAIN,
)
from .coordinator import HPPrintCoordinator
from .period_usage import PeriodUsageSensor
from .today_jobs import TodayJobsSensor


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HP Printer sensors from a config entry."""
    coordinator: HPPrintCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []

    # Subunit-level numeric sensors
    for key, cfg in ALL_SUBUNIT_SENSORS.items():
        entities.append(
            HPPrintSensor(
                coordinator=coordinator,
                entry=entry,
                key=key,
                name=cfg["name"],
                unit=cfg["unit"],
                icon=cfg["icon"],
            )
        )

    # Consumable sensors per ink color
    for station, color in INK_COLORS.items():
        cl = color.lower()
        pfx = f"ink_{cl}"

        entities.append(
            HPPrintSensor(
                coordinator=coordinator, entry=entry,
                key=f"{pfx}_level_remaining",
                name=f"{color} 墨水剩余", unit="%", icon="mdi:water-percent",
            )
        )
        entities.append(
            HPPrintSensor(
                coordinator=coordinator, entry=entry,
                key=f"{pfx}_ink_used_ml",
                name=f"{color} 累计用墨量", unit=UnitOfVolume.MILLILITERS, icon="mdi:water",
            )
        )
        entities.append(
            HPPrintSensor(
                coordinator=coordinator, entry=entry,
                key=f"{pfx}_hp_ink_used_ml",
                name=f"{color} HP原装墨量", unit=UnitOfVolume.MILLILITERS, icon="mdi:water-check",
            )
        )
        entities.append(
            HPPrintSensor(
                coordinator=coordinator, entry=entry,
                key=f"{pfx}_cartridge_count",
                name=f"{color} 更换墨盒次数", unit="次", icon="mdi:cartridge",
            )
        )
        entities.append(
            HPPrintTextSensor(
                coordinator=coordinator, entry=entry,
                key=f"{pfx}_state",
                name=f"{color} 墨盒状态", icon="mdi:information",
            )
        )
        entities.append(
            HPPrintTextSensor(
                coordinator=coordinator, entry=entry,
                key=f"{pfx}_serial",
                name=f"{color} 序列号", icon="mdi:barcode",
            )
        )

    # Period usage sensor (daily/monthly/yearly + daylist)
    daylist_days = entry.data.get(CONF_DAYLIST_DAYS, DEFAULT_DAYLIST_DAYS)
    period_sensor = PeriodUsageSensor(
        coordinator=coordinator, entry=entry, daylist_days=daylist_days
    )
    entities.append(period_sensor)

    # Store reference so button can trigger refresh after backfill
    hass.data[DOMAIN][f"{entry.entry_id}_period_sensor"] = period_sensor

    # Device status sensors (SNMP)
    entities.append(
        HPPrintTextSensor(
            coordinator=coordinator, entry=entry,
            key="device_status",
            name="设备状态", icon="mdi:printer",
        )
    )
    entities.append(
        HPPrintTextSensor(
            coordinator=coordinator, entry=entry,
            key="printer_status",
            name="打印机状态", icon="mdi:printer-check",
        )
    )
    entities.append(
        HPPrintTextSensor(
            coordinator=coordinator, entry=entry,
            key="error_state",
            name="错误状态", icon="mdi:alert-circle",
        )
    )

    # Event log sensor (merged: all events in state attributes)
    entities.append(
        HPPrintEventLogSensor(
            coordinator=coordinator, entry=entry,
            key="event_log_total_count",
            name="事件日志", icon="mdi:format-list-bulleted",
        )
    )

    # Today's job detail sensor (inferred from counter deltas + jam events)
    entities.append(
        TodayJobsSensor(
            coordinator=coordinator, entry=entry,
        )
    )

    async_add_entities(entities)


class HPPrintSensor(CoordinatorEntity, SensorEntity):
    """Numeric sensor for HP Printer data."""

    def __init__(
        self,
        coordinator: HPPrintCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        unit: str,
        icon: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "HP",
        }

    @property
    def native_value(self) -> StateType:
        """Return the state."""
        data = self.coordinator.data
        if data is None:
            return None
        return data.get(self._key)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None


class HPPrintTextSensor(CoordinatorEntity, SensorEntity):
    """Text sensor for HP Printer data (e.g. consumable state, serial)."""

    def __init__(
        self,
        coordinator: HPPrintCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        icon: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "HP",
        }

    @property
    def native_value(self) -> StateType:
        """Return the state."""
        data = self.coordinator.data
        if data is None:
            return None
        return data.get(self._key)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None


class HPPrintEventLogSensor(CoordinatorEntity, SensorEntity):
    """Merged event log sensor — state = total count, attributes = all events.

    Attributes keyed by event time (ISO format), sorted newest-first.
    """

    _attr_icon = "mdi:format-list-bulleted"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: HPPrintCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        icon: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "HP",
        }

    @property
    def native_value(self) -> StateType:
        """State = total event count."""
        data = self.coordinator.data
        if data is None:
            return None
        return data.get(self._key, 0)

    @property
    def extra_state_attributes(self) -> dict:
        """Attributes keyed by event time, each = {code, description, seq, occurrences, pages}."""
        data = self.coordinator.data
        if data is None:
            return {}
        events = data.get("event_log_data", [])
        if not events:
            return {"count": 0}
        result = {"count": len(events)}
        for evt in events:
            t = evt.get("time", "")
            if t:
                result[t] = {
                    "seq": evt.get("seq", 0),
                    "code": evt.get("code", ""),
                    "description": evt.get("description", ""),
                    "occurrences": evt.get("occurrences", 0),
                    "pages": evt.get("pages", 0),
                }
        return result

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.data is not None
