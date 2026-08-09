"""Long-term-statistics import for City of Waco water data.

Home Assistant records a consumption series as a running total: each hourly
row carries that hour's own usage in ``state`` and the cumulative total of
every hour up to and including it in ``sum``. The portal reports each hour on
its own, so hourly values are accumulated ("folded") onto an *anchor* — a
previously recorded row identified by its hour and running total.

A cold start folds the whole history from zero. A warm refresh anchors on an
already-recorded hour far enough back to be settled and folds only the hours
after it, so recent hours the portal may still restate are recomputed while
older rows are left alone. (Pattern adapted from the wbyoung/watersmart
integration.)
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import datetime as dt
from operator import itemgetter
from typing import Any, cast

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_conversion import VolumeConverter

from .const import DOMAIN

# A warm refresh re-folds the trailing window of buckets so late upstream
# corrections are absorbed without rewriting the whole series. The portal's
# data lags roughly a day, so 72h comfortably covers restatements.
REFOLD_WINDOW = dt.timedelta(hours=72)
# The anchor lookup spans an extra day so a bucket landing exactly on the
# cutoff is still found.
ANCHOR_LOOKBACK = dt.timedelta(hours=24)
# ``unit_class`` joined StatisticMetaData in HA 2025.11; probe rather than pin.
_SUPPORTS_UNIT_CLASS = "unit_class" in StatisticMetaData.__annotations__


def _utc_from_epoch(timestamp: float) -> dt.datetime:
    """Interpret an epoch timestamp as a UTC datetime.

    Returns:
        The timestamp as a timezone-aware UTC datetime.
    """
    return dt.datetime.fromtimestamp(timestamp, tz=dt.UTC)


def statistic_id_for(device_id: str) -> str:
    """Return the external statistic id for a meter device.

    Returns:
        e.g. ``waco_water:consumption_0150000000``.
    """
    return f"{DOMAIN}:consumption_{device_id.lower()}"


def metadata_for(device_id: str, meter_number: str) -> StatisticMetaData:
    """Build the external-statistics metadata for a meter device.

    Returns:
        Metadata describing the consumption series.
    """
    # Assembled as a plain mapping because the accepted keys vary by HA version.
    metadata: dict[str, Any] = {
        "mean_type": StatisticMeanType.NONE,
        "has_sum": True,
        "name": f"Water consumption (meter {meter_number})",
        "source": DOMAIN,
        "statistic_id": statistic_id_for(device_id),
        "unit_of_measurement": UnitOfVolume.GALLONS,
    }
    if _SUPPORTS_UNIT_CLASS:
        metadata["unit_class"] = VolumeConverter.UNIT_CLASS
    return cast("StatisticMetaData", metadata)


def bucket_records(
    records: Iterable[Mapping[str, Any]],
) -> list[tuple[dt.datetime, float]]:
    """Group records by UTC hour.

    Sums multiple records that fall within the same UTC hour (the DST
    fall-back hour arrives twice under a naive local clock) and returns the
    result sorted chronologically.

    Returns:
        ``(hour_start_utc, gallons)`` pairs sorted chronologically.
    """
    buckets: dict[dt.datetime, float] = {}
    for record in records:
        gallons = record["gallons"]
        if gallons is None:
            continue
        start = _utc_from_epoch(record["read_datetime"]).replace(
            minute=0, second=0, microsecond=0
        )
        buckets[start] = buckets.get(start, 0.0) + gallons
    return sorted(buckets.items())


@dataclass(frozen=True)
class Anchor:
    """The cumulative state a fold continues from.

    ``start`` is ``None`` on a cold start, meaning every bucket is folded;
    otherwise only buckets strictly after ``start`` are folded onto ``sum``.
    """

    start: dt.datetime | None
    sum: float


# A cold start (no prior statistics row) folds the whole series from zero.
COLD_START = Anchor(start=None, sum=0.0)


def fold_cumulative(
    buckets: Iterable[tuple[dt.datetime, float]],
    anchor: Anchor,
) -> list[StatisticData]:
    """Fold per-hour gallons after ``anchor`` into cumulative-sum rows.

    Each row's ``state`` is that hour's own gallons and ``sum`` the running
    total — HA's external-statistics convention.

    Returns:
        Cumulative-sum statistic rows in chronological order.
    """
    rows: list[StatisticData] = []
    running = anchor.sum
    for start, gallons in buckets:
        if anchor.start is not None and start <= anchor.start:
            continue
        running += gallons
        rows.append(StatisticData(start=start, state=gallons, sum=running))
    return rows


def anchor_window(last_row: Mapping[str, Any]) -> tuple[dt.datetime, dt.datetime]:
    """Return the time span to search for a warm-refresh anchor row.

    Returns:
        ``(window_start, window_end)`` for ``statistics_during_period``.
    """
    cutoff = _utc_from_epoch(last_row["start"]) - REFOLD_WINDOW
    return cutoff - ANCHOR_LOOKBACK, cutoff + dt.timedelta(hours=1)


def select_anchor(window_rows: Sequence[Mapping[str, Any]]) -> Anchor:
    """Choose the anchor a warm refresh folds the trailing window onto.

    An empty window (series shorter than the refold window, or a recording
    gap) has no row supplying a matched start/sum pair, so the whole series is
    re-folded from zero rather than risking a skewed running total.

    Returns:
        The anchor to fold onto.
    """
    if not window_rows:
        return COLD_START
    row = max(window_rows, key=itemgetter("start"))
    return Anchor(start=_utc_from_epoch(row["start"]), sum=row["sum"] or 0.0)


def clear(hass: HomeAssistant, device_id: str) -> None:
    """Clear the external statistics series for a meter device."""
    get_instance(hass).async_clear_statistics([statistic_id_for(device_id)])
