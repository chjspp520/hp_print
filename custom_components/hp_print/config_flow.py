"""Config flow for HP Printer Monitor integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_DAYLIST_DAYS,
    CONF_SCAN_INTERVAL,
    DEFAULT_DAYLIST_DAYS,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=10, max=3600)
        ),
        vol.Optional(CONF_DAYLIST_DAYS, default=DEFAULT_DAYLIST_DAYS): vol.All(
            vol.Coerce(int), vol.Range(min=7, max=730)
        ),
    }
)

RECONFIGURE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=10, max=3600)
        ),
        vol.Optional(CONF_DAYLIST_DAYS, default=DEFAULT_DAYLIST_DAYS): vol.All(
            vol.Coerce(int), vol.Range(min=7, max=730)
        ),
    }
)


class HPPrintConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HP Printer Monitor."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Use the host as the unique ID
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=user_input.get(CONF_NAME, user_input[CONF_HOST]),
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        """Handle the reconfigure step (gear icon on device page)."""
        errors = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                data_updates={
                    CONF_HOST: user_input[CONF_HOST],
                    CONF_NAME: user_input.get(CONF_NAME, entry.title),
                    CONF_SCAN_INTERVAL: user_input.get(
                        CONF_SCAN_INTERVAL,
                        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ),
                    CONF_DAYLIST_DAYS: user_input.get(
                        CONF_DAYLIST_DAYS,
                        entry.data.get(CONF_DAYLIST_DAYS, DEFAULT_DAYLIST_DAYS),
                    ),
                },
                reason="reconfigure_successful",
            )

        # Pre-fill with existing values
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=entry.data.get(CONF_HOST, "")
                    ): cv.string,
                    vol.Optional(
                        CONF_NAME,
                        default=entry.data.get(CONF_NAME, entry.title),
                    ): cv.string,
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=entry.data.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
                    vol.Optional(
                        CONF_DAYLIST_DAYS,
                        default=entry.data.get(
                            CONF_DAYLIST_DAYS, DEFAULT_DAYLIST_DAYS
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=7, max=730)),
                }
            ),
            errors=errors,
        )
