"""The City of Waco Water integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from . import statistics as stats
from .client import WacoPortalClient
from .const import (
    CONF_ACCOUNT_NUMBER,
    CONF_BASE_URL,
    CONF_DEVICE_ID,
    CONF_METER_NUMBER,
)
from .coordinator import WacoWaterCoordinator

PLATFORMS = [Platform.SENSOR]

type WacoWaterConfigEntry = ConfigEntry[WacoWaterCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: WacoWaterConfigEntry
) -> bool:
    """Set up City of Waco Water from a config entry.

    Returns:
        Whether setup succeeded.
    """
    # A dedicated session keeps the portal's auth cookie out of the shared jar.
    session = async_create_clientsession(hass)
    client = WacoPortalClient(
        session,
        entry.data[CONF_BASE_URL],
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
    )
    coordinator = WacoWaterCoordinator(
        hass,
        entry,
        client,
        entry.data[CONF_ACCOUNT_NUMBER],
        entry.data[CONF_METER_NUMBER],
        entry.data[CONF_DEVICE_ID],
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: WacoWaterConfigEntry
) -> bool:
    """Unload a config entry.

    Returns:
        Whether unload succeeded.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: WacoWaterConfigEntry
) -> None:
    """Clean up the statistics series when the entry is removed."""
    stats.clear(hass, entry.data[CONF_DEVICE_ID])
