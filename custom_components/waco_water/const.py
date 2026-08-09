"""Constants for the City of Waco Water integration."""

from __future__ import annotations

import datetime as dt

DOMAIN = "waco_water"
MANUFACTURER = "City of Waco"

DEFAULT_BASE_URL = "https://www.mywacoaccount.com"

CONF_ACCOUNT_NUMBER = "account_number"
CONF_BASE_URL = "base_url"
CONF_METER_NUMBER = "meter_number"
CONF_DEVICE_ID = "device_id"

DEFAULT_SCAN_INTERVAL = dt.timedelta(hours=1)

# The portal reports interval data in the utility's local timezone.
PORTAL_TIMEZONE = "America/Chicago"

# Hourly interval queries are chunked; a 92-day request is known to return
# complete data, so stay under that.
FETCH_CHUNK_DAYS = 85
