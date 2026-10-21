"""HP Printer Monitor integration for Home Assistant."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
from .coordinator import HPPrintCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HP Printer from a config entry."""
    host = entry.data[CONF_HOST]
    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    coordinator = HPPrintCoordinator(hass, host, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    return True


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry updates (e.g. from reconfigure).

    Daylist_days is picked up by sensor.py on reload; only runtime
    properties (host, scan_interval) need manual updating here.
    """
    coordinator: HPPrintCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Update host
    new_host = entry.data[CONF_HOST]
    if coordinator.host != new_host:
        _LOGGER.info("HP Printer host changed: %s → %s", coordinator.host, new_host)
        coordinator.host = new_host

    # Update scan interval
    new_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator.update_interval = timedelta(seconds=new_interval)
    _LOGGER.info("HP Printer scan interval updated to %s seconds", new_interval)


class AllEntitiesSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing every entity of this printer device as attributes.

    State = number of entities found.
    Attributes: entities = [{entity_id, name, icon, state}, ...]
    """

    _attr_icon = "mdi:format-list-bulleted"
    _attr_has_entity_name = True
    _attr_name = "全部实体"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: HPPrintCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_all_entities"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "HP",
        }
        self._entities: list[dict[str, str]] = []

    async def async_added_to_hass(self) -> None:
        """Collect entity list once the entity_id is assigned."""
        await super().async_added_to_hass()
        self._refresh_entities()

    def _refresh_entities(self) -> None:
        """Rebuild the entity list from the device/entity registry."""
        device_registry = dr.async_get(self.hass)
        entity_registry = er.async_get(self.hass)

        device = device_registry.async_get_device(
            identifiers={(DOMAIN, self._entry_id)}
        )
        if device is None:
            self._entities = []
            return

        items: list[dict[str, str]] = []
        for reg_entry in er.async_entries_for_device(
            entity_registry, device.id, include_disabled_entities=False
        ):
            # Skip ourselves to avoid a self-referencing state value
            if reg_entry.entity_id == self.entity_id:
                continue

            state = self.hass.states.get(reg_entry.entity_id)
            name = None
            icon = None
            if state is not None:
                name = state.attributes.get("friendly_name")
                icon = state.attributes.get("icon")
            name = name or reg_entry.name or reg_entry.original_name or reg_entry.entity_id
            icon = icon or reg_entry.icon or ""

            items.append(
                {
                    "entity_id": reg_entry.entity_id,
                    "name": str(name),
                    "icon": str(icon),
                    "state": state.state if state is not None else "unavailable",
                }
            )

        items.sort(key=lambda x: x["entity_id"])
        self._entities = items

    @property
    def native_value(self) -> StateType:
        """State = number of entities."""
        return len(self._entities)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose the entity list."""
        return {
            "count": len(self._entities),
            "entities": self._entities,
        }

    @property
    def available(self) -> bool:
        """Always available."""
        return True

    def _handle_coordinator_update(self) -> None:
        """Refresh the entity list, then let HA write the new state."""
        self._refresh_entities()
        super()._handle_coordinator_update()
