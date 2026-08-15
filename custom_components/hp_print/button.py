"""Button platform for HP Printer Monitor — trigger history backfill and reload."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HPPrintCoordinator
from .period_usage import _backfill_from_history, PeriodUsageStore

_LOGGER = logging.getLogger(__name__)


def _get_sensor(hass: HomeAssistant, entry_id: str):
    """Get the PeriodUsageSensor reference from hass.data."""
    return hass.data[DOMAIN].get(f"{entry_id}_period_sensor")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HP Printer buttons."""
    coordinator: HPPrintCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        BackfillHistoryButton(coordinator, entry),
        ReloadStorageButton(coordinator, entry),
    ])


class BackfillHistoryButton(ButtonEntity):
    """Button to trigger history data backfill for period usage."""

    _attr_icon = "mdi:database-import"
    _attr_has_entity_name = True
    _attr_name = "补齐历史用量"

    def __init__(
        self,
        coordinator: HPPrintCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize."""
        self._entry = entry
        self._entry_id = entry.entry_id
        self._store = PeriodUsageStore(coordinator.hass, entry.entry_id)
        self._attr_unique_id = f"{entry.entry_id}_backfill_history"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "HP",
        }

    async def async_press(self) -> None:
        """Handle button press — backfill history and update sensor."""
        _LOGGER.info("BackfillHistory: starting history backfill for %s", self._entry_id)

        stored = await self._store.load()
        daylist_days = self._entry.data.get("daylist_days", 90)

        daylist, monthlist, yearlist, baselines = await _backfill_from_history(
            self.hass, self._entry_id, daylist_days
        )

        if not daylist and not monthlist and not yearlist:
            _LOGGER.warning("BackfillHistory: backfill returned empty results")
            return

        # Save to storage
        stored["daylist"] = daylist
        stored["monthlist"] = monthlist
        stored["yearlist"] = yearlist
        stored["baselines"] = baselines
        await self._store.save(stored)

        # Notify period usage sensor to reload from storage
        sensor = _get_sensor(self.hass, self._entry_id)
        if sensor is not None:
            sensor.reload_from_stored(stored)
            sensor.schedule_update_ha_state(force_refresh=True)
            _LOGGER.info(
                "BackfillHistory: sensor updated — daylist=%d, monthlist=%d, yearlist=%d",
                len(daylist), len(monthlist), len(yearlist),
            )
        else:
            _LOGGER.warning("BackfillHistory: period usage sensor not found")


class ReloadStorageButton(ButtonEntity):
    """Button to reload period usage data from the storage JSON file.

    Use this after manually editing the JSON file so the sensor picks up changes immediately.
    """

    _attr_icon = "mdi:file-reload"
    _attr_has_entity_name = True
    _attr_name = "重新加载用量数据"

    def __init__(
        self,
        coordinator: HPPrintCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize."""
        self._entry_id = entry.entry_id
        self._store = PeriodUsageStore(coordinator.hass, entry.entry_id)
        self._attr_unique_id = f"{entry.entry_id}_reload_storage"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "HP",
        }

    async def async_press(self) -> None:
        """Reload storage JSON and push to sensor."""
        _LOGGER.info("ReloadStorage: reloading storage for %s", self._entry_id)

        stored = await self._store.load()
        _LOGGER.info(
            "ReloadStorage: loaded daylist=%d, monthlist=%d, yearlist=%d",
            len(stored.get("daylist", [])),
            len(stored.get("monthlist", [])),
            len(stored.get("yearlist", [])),
        )

        sensor = _get_sensor(self.hass, self._entry_id)
        if sensor is not None:
            sensor.reload_from_stored(stored)
            sensor.schedule_update_ha_state(force_refresh=True)
            _LOGGER.info("ReloadStorage: sensor updated")
        else:
            _LOGGER.warning("ReloadStorage: period usage sensor not found")
