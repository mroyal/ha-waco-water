"""Data update coordinator for City of Waco Water."""

from __future__ import annotations

from asyncio import timeout
from collections.abc import Callable
import datetime as dt
import functools
import logging
from typing import Any

from aiohttp import ClientError
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import statistics as stats
from .client import AuthenticationError, PortalError, WacoPortalClient
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, FETCH_CHUNK_DAYS, MANUFACTURER

EXCEPTIONS = (AuthenticationError, PortalError, ClientError, TimeoutError)

_LOGGER = logging.getLogger(__name__)


class _RecorderQueryFailed(Exception):
    """A recorder query raised; the statistics import is abandoned this cycle."""


class WacoWaterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch portal data and maintain the long-term statistics series."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: WacoPortalClient,
        account_number: str,
        meter_number: str,
        device_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"Waco Water {meter_number}",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client
        self.account_number = account_number
        self.meter_number = meter_number
        self.device_id = device_id
        self.device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, device_id)},
            manufacturer=MANUFACTURER,
            name=f"Water Meter {meter_number}",
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the current register read and import hourly statistics.

        Returns:
            The current-read data for sensors.

        Raises:
            UpdateFailed: On portal or connection errors.
        """
        try:
            async with timeout(60):
                current = await self.client.async_get_current_read(self.device_id)
        except EXCEPTIONS as error:
            raise UpdateFailed(error) from error

        await self._insert_statistics(current)
        return current

    async def _insert_statistics(self, current: dict[str, Any]) -> None:
        """Import hourly consumption into HA's long-term statistics.

        Cold start fetches and folds the portal's full history (chunked);
        a warm refresh re-folds only the trailing window. Recorder errors are
        logged and swallowed so they can't mask fresh sensor data.
        """
        try:
            anchor = await self._resolve_anchor()
        except _RecorderQueryFailed:
            return

        # Hours after the register's own read time haven't been reported yet;
        # anything the portal returns past it would be padding, not data.
        cutoff = dt.datetime.fromtimestamp(
            current["read_datetime"], tz=dt.UTC
        ).replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)

        try:
            records = await self._fetch_records(anchor)
        except EXCEPTIONS as error:
            _LOGGER.warning("Failed to fetch interval data: %s", error)
            return

        buckets = [
            (start, gallons)
            for start, gallons in stats.bucket_records(records)
            if start < cutoff
        ]
        rows = stats.fold_cumulative(buckets, anchor)
        if not rows:
            _LOGGER.debug("No new statistics buckets to import")
            return
        try:
            self._write_statistics(rows)
        except _RecorderQueryFailed:
            return
        _LOGGER.debug("Imported %d statistics rows", len(rows))

    async def _fetch_records(self, anchor: stats.Anchor) -> list[dict[str, Any]]:
        """Fetch the hourly records the current fold needs.

        Returns:
            Hourly records from the anchor's refold window (or, on a cold
            start, the portal's full history) through now.
        """
        now = dt.datetime.now(dt.UTC)
        if anchor.start is None:
            first_day, _ = await self.client.async_get_date_range(
                self.device_id, self.account_number
            )
            start = dt.datetime(
                first_day.year, first_day.month, first_day.day, tzinfo=dt.UTC
            )
            _LOGGER.info(
                "Cold start: importing portal history since %s", first_day
            )
        else:
            start = anchor.start - stats.ANCHOR_LOOKBACK

        records: list[dict[str, Any]] = []
        chunk = dt.timedelta(days=FETCH_CHUNK_DAYS)
        async with timeout(600):
            while start < now:
                end = min(start + chunk, now)
                records += await self.client.async_get_hourly(
                    self.account_number, self.device_id, start, end
                )
                start = end
        return records

    async def _resolve_anchor(self) -> stats.Anchor:
        """Resolve the cumulative anchor the fold continues from.

        Returns:
            A cold-start anchor when no prior statistics exist, otherwise the
            warm-refresh anchor selected from the recorder.
        """
        statistic_id = stats.statistic_id_for(self.device_id)

        # These sums are accumulated onto, so they must arrive in the stored
        # unit — no display-unit conversion.
        last = await self._recorder_query(
            "read last statistics",
            functools.partial(
                get_last_statistics,
                self.hass,
                1,
                statistic_id,
                convert_units=False,
                types={"sum"},
            ),
        )
        last_rows = last.get(statistic_id, [])
        if not last_rows:
            return stats.COLD_START

        window_start, window_end = stats.anchor_window(last_rows[0])
        window = await self._recorder_query(
            "look up anchor statistics",
            functools.partial(
                statistics_during_period,
                self.hass,
                window_start,
                window_end,
                statistic_ids={statistic_id},
                period="hour",
                units=None,
                types={"sum"},
            ),
        )
        window_rows = window.get(statistic_id, [])
        if not window_rows:
            _LOGGER.warning(
                "No anchor row in the trailing window for %s despite an "
                "existing series; re-folding the whole history this refresh",
                statistic_id,
            )
        return stats.select_anchor(window_rows)

    async def _recorder_query(
        self,
        description: str,
        query: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        """Run a recorder query off the event loop.

        Returns:
            The query result keyed by statistic id.

        Raises:
            _RecorderQueryFailed: If ``query`` raised.
        """
        try:
            return await get_instance(self.hass).async_add_executor_job(query)
        except Exception as error:
            _LOGGER.warning("Failed to %s", description, exc_info=True)
            raise _RecorderQueryFailed from error

    def _write_statistics(self, rows: list[StatisticData]) -> None:
        """Upsert statistic rows.

        Raises:
            _RecorderQueryFailed: If the recorder write failed.
        """
        metadata = stats.metadata_for(self.device_id, self.meter_number)
        try:
            async_add_external_statistics(self.hass, metadata, rows)
        except Exception as error:
            _LOGGER.warning("Failed to write statistics", exc_info=True)
            raise _RecorderQueryFailed from error
