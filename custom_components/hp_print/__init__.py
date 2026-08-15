"""HP Printer Monitor integration for Home Assistant."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant

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
