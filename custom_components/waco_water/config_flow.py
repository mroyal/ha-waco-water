"""Config flow for the City of Waco Water integration."""

from __future__ import annotations

from asyncio import timeout
import logging
from typing import Any

from aiohttp import ClientError
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .client import AuthenticationError, PortalError, WacoPortalClient
from .const import (
    CONF_ACCOUNT_NUMBER,
    CONF_BASE_URL,
    CONF_DEVICE_ID,
    CONF_METER_NUMBER,
    DEFAULT_BASE_URL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_ACCOUNT_NUMBER): str,
        vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
    }
)


class NoMeterFound(Exception):
    """The account has no water smart meter."""


async def _validate_input(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, str]:
    """Check the credentials and discover the account's meter.

    Returns:
        ``{"meter_number": ..., "device_id": ...}``.

    Raises:
        AuthenticationError: If the portal rejects the credentials.
        NoMeterFound: If the account has no water smart meter.
    """
    session = async_create_clientsession(hass)
    client = WacoPortalClient(
        session, data[CONF_BASE_URL], data[CONF_EMAIL], data[CONF_PASSWORD]
    )
    async with timeout(30):
        await client.async_authenticate()
        meters = await client.async_get_meter_numbers(data[CONF_ACCOUNT_NUMBER])
        if not meters:
            raise NoMeterFound
        devices = await client.async_get_device_ids(meters[0])
        if not devices:
            raise NoMeterFound
    return {CONF_METER_NUMBER: meters[0], CONF_DEVICE_ID: devices[0]}


class WacoWaterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for City of Waco Water."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step.

        Returns:
            The flow result.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                discovered = await _validate_input(self.hass, user_input)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except NoMeterFound:
                errors["base"] = "no_meter"
            except (PortalError, ClientError, TimeoutError):
                _LOGGER.exception("Could not reach the portal")
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    f"{user_input[CONF_ACCOUNT_NUMBER]}-{discovered[CONF_DEVICE_ID]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Waco Water (meter {discovered[CONF_METER_NUMBER]})",
                    data={**user_input, **discovered},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
