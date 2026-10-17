# M271 15-min speed + flow (WebTRIS)

`m271_speed_15min.csv.gz`, 15-minute average speed and flow for the five M271
TMU sites on the Western Docks approach. Built for the forecast engine (Seb's
lane) because the shared WebTRIS cache (`data/cache/`, gitignored) held flow but
not a committed speed series.

## Source & licence

- **National Highways WebTRIS** (`webtris.nationalhighways.co.uk`), reports/daily.
- **Open Government Licence v3.0**, redistribution permitted with attribution.
- Retrieved Oct 2026 via the WebTRIS API and cached under `data/raw/webtris/`
  (gitignored); this file is the parsed extract of that cache.
- Parsed by `src/sotonship26/data/observed.py::rows_to_frame` (same code the
  flow pipeline uses), so `mph`/`flow_veh` match the live loader exactly.

## Schema

| column | meaning |
|---|---|
| `site_id` | WebTRIS site id |
| `road` | always `M271` |
| `direction` | northbound / southbound |
| `name` | TMU site name |
| `bin_start` | 15-min bin start, tz-aware `Europe/London` (handles BST/GMT) |
| `mph` | WebTRIS `Avg mph` for the bin (empty where the loop reported no speed) |
| `flow_veh` | `Total Volume` (all vehicles) for the bin |

## Sites

| site_id | direction | where |
|---|---|---|
| 19974 | northbound | A35 Redbridge to J1 |
| 19796 | southbound | J1 to A35 Redbridge |
| 20313 | southbound | M27 J3 to A3057 |
| 20605 | northbound | A3057 to M27 J3 |
| 7588  | northbound | J1 to M27 |

## Coverage caveat

400,896 rows span **2023-07 to 2026-06**, but only **~32% carry a speed value**
(`mph` is blank on the rest, overnight low-flow bins and loop-quality gaps).
Treat `mph` as present-when-reported, not a complete series; join on
`(site_id, bin_start)` and expect NaN. Flow (`flow_veh`) is far more complete.

Read: `pd.read_csv("data/webtris/m271_speed_15min.csv.gz", parse_dates=["bin_start"])`.
