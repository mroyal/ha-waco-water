"""Async client for the City of Waco utility portal (mywacoaccount.com).

The portal authenticates with ``POST /api/authenticate`` carrying an HTTP
Basic header (email:password) plus an ``h-captcha-response`` form field that is
empty while the portal has hCaptcha disabled. Success establishes a session
cookie which the JSON APIs under ``/api/`` then accept; an expired or missing
session yields a JSON 401, which the request wrapper answers with one
re-authentication and retry.
"""

from __future__ import annotations

import base64
import datetime as dt
import logging
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from .const import PORTAL_TIMEZONE

_LOGGER = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """The portal rejected the credentials."""


class PortalError(Exception):
    """The portal returned an unexpected response."""


class WacoPortalClient:
    """Minimal client for the endpoints this integration needs."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        email: str,
        password: str,
    ) -> None:
        """Initialize."""
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._email = email
        self._password = password
        self._timezone = ZoneInfo(PORTAL_TIMEZONE)

    async def async_authenticate(self) -> None:
        """Log in and establish a session cookie.

        Raises:
            AuthenticationError: If the portal rejects the credentials.
            PortalError: On any other non-success response.
        """
        token = base64.b64encode(
            f"{self._email}:{self._password}".encode()
        ).decode()
        resp = await self._session.post(
            f"{self._base_url}/api/authenticate",
            headers={"Authorization": f"Basic {token}"},
            data={"h-captcha-response": ""},
        )
        if resp.status in (401, 403):
            raise AuthenticationError("Portal rejected credentials")
        if resp.status >= 400:
            raise PortalError(f"Authentication failed with HTTP {resp.status}")

    async def _get_json(self, path: str, **kwargs: Any) -> Any:
        """GET a JSON endpoint, re-authenticating once on a 401.

        Returns:
            The decoded JSON payload.

        Raises:
            AuthenticationError: If re-authentication also fails.
            PortalError: On any other non-success response.
        """
        url = f"{self._base_url}{path}"
        for attempt in (1, 2):
            resp = await self._session.get(url, **kwargs)
            if resp.status == 401 and attempt == 1:
                await self.async_authenticate()
                continue
            if resp.status >= 400:
                raise PortalError(f"GET {path} failed with HTTP {resp.status}")
            return await resp.json()
        raise PortalError(f"GET {path} still unauthorized after login")

    async def async_get_meter_numbers(self, account_number: str) -> list[str]:
        """Return the water smart-meter numbers on the account.

        Returns:
            Display meter numbers, e.g. ``["12345678"]``.
        """
        payload = await self._get_json(
            f"/api/admin/meters/water-smart-meters-for-account/{account_number}"
        )
        return list(payload.get("data") or [])

    async def async_get_device_ids(self, meter_number: str) -> list[str]:
        """Return the device ids behind a display meter number.

        Returns:
            Device ids, e.g. ``["0150000000"]``.
        """
        payload = await self._get_json(
            "/api/customer/meter-devices", params={"meterNumber": meter_number}
        )
        return list(payload or [])

    async def async_get_date_range(
        self, device_id: str, account_number: str
    ) -> tuple[dt.date, dt.date]:
        """Return the span of interval history the portal holds for a meter.

        Returns:
            ``(start_date, end_date)``.
        """
        payload = await self._get_json(
            f"/api/admin/meters/getDateRangeForMeter/{device_id}/{account_number}"
        )
        data = payload["data"]
        return (
            dt.date.fromisoformat(data["startDate"]),
            dt.date.fromisoformat(data["endDate"]),
        )

    async def async_get_current_read(self, device_id: str) -> dict[str, Any]:
        """Return the meter's latest cumulative register reading.

        Returns:
            ``{"reading": float, "read_datetime": float}`` with the read time
            as epoch seconds.
        """
        payload = await self._get_json(
            "/api/customer/meter-reads-and-thresholds-data",
            params={"meterNumber": device_id},
        )
        reads = payload["data"]["lastMeterReadsData"]
        read_at = dt.datetime.fromisoformat(reads["date"])
        return {
            "reading": float(reads["reading"]),
            "read_datetime": read_at.timestamp(),
        }

    async def async_get_hourly(
        self,
        account_number: str,
        device_id: str,
        start: dt.datetime,
        end: dt.datetime,
    ) -> list[dict[str, Any]]:
        """Return hourly consumption records for a UTC time span.

        Returns:
            ``{"read_datetime": float, "gallons": float}`` records, with the
            hour start as epoch seconds, in the order the portal sent them.
        """
        payload = await self._get_json(
            "/api/shared/interval",
            params={
                "account_number": account_number,
                "start_date": self._format_local(start),
                "end_date": self._format_local(end),
                "service_category": "WATER",
                "format": "json",
                "meter_id": device_id,
                "period": "Hourly",
            },
        )
        # Spans predating the portal's hourly retention come back without a
        # Consumption series (or as an empty list); that's absence of data,
        # not an error.
        series = next(
            (
                s
                for s in payload or []
                if s.get("measurementType") == "Consumption"
            ),
            None,
        )
        if series is None:
            _LOGGER.debug(
                "No Consumption series for %s..%s; treating as empty",
                start,
                end,
            )
            return []
        records: list[dict[str, Any]] = []
        for point in series.get("dataPoints") or []:
            value = point.get("value")
            if value is None:
                continue
            # Timestamps arrive naive in the utility's local timezone.
            local = dt.datetime.fromisoformat(point["date"]).replace(
                tzinfo=self._timezone
            )
            records.append(
                {"read_datetime": local.timestamp(), "gallons": float(value)}
            )
        return records

    def _format_local(self, moment: dt.datetime) -> str:
        """Render a datetime the way the portal expects query bounds.

        Returns:
            e.g. ``2026-08-04T00:00-05:00``.
        """
        local = moment.astimezone(self._timezone)
        offset = local.strftime("%z")
        return local.strftime("%Y-%m-%dT%H:%M") + f"{offset[:3]}:{offset[3:]}"
