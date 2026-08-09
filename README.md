# City of Waco Water for Home Assistant

A Home Assistant custom integration for the City of Waco utility portal
([mywacoaccount.com](https://www.mywacoaccount.com)). It brings your water
smart-meter data into the Energy dashboard:

- **Hourly consumption history** imported into Home Assistant long-term
  statistics — including a one-time backfill of everything the portal retains
  (roughly the last 13 months), so your Energy dashboard's water tab starts
  with a year of hourly data instead of starting from zero.
- **A meter reading sensor** with the meter's cumulative register (gallons)
  and the time it was last read.

Data in the portal lags real time by up to a day; the integration polls
hourly and re-folds recent hours, so late corrections from the city are
absorbed automatically.

> This is an independent project, not affiliated with or endorsed by the
> City of Waco.

## Installation

### HACS (custom repository)

1. HACS → three-dot menu → *Custom repositories*
2. Add `https://github.com/mroyal/ha-waco-water` with type *Integration*
3. Install **City of Waco Water**, then restart Home Assistant

### Manual

Copy `custom_components/waco_water/` into your config's
`custom_components/` directory and restart Home Assistant.

## Configuration

*Settings → Devices & Services → Add Integration → City of Waco Water*

You'll need:

- the **email and password** for your mywacoaccount.com login
- your **account number** (shown at the top right of the portal)

The integration discovers your water smart meter automatically. The first
refresh performs the full history backfill and may take a minute.

Then add the **"Water consumption (meter …)"** statistic under
*Settings → Dashboards → Energy → Water tab → Add water source*.

## Other cities

The portal is white-label software, so other utilities may run the same
platform under a different domain. If your city's account portal looks like
Waco's (a "Smart Meters" section with a "Water Interval Profile" chart), try
pointing the integration's *Portal URL* field at it — reports of it working
or failing elsewhere are welcome in the issue tracker.

## Caveats

- This uses the portal's **unofficial** browser API. The city can change or
  break it at any time. In particular, the portal's login form has hCaptcha
  support that is currently disabled server-side; if it is ever enabled,
  authentication will stop working.
- Only the first water meter on an account is set up today.
- Usage data is delayed roughly a day by the utility — the integration
  cannot see water use in real time, so it is not a leak detector. (The
  portal itself offers leak/continuous-use email alerts; configure those on
  the portal.)

## Credits

The long-term-statistics fold/anchor logic is adapted from
[wbyoung/watersmart](https://github.com/wbyoung/watersmart) (Apache-2.0).
See `NOTICE`.

## License

[Apache-2.0](LICENSE)
