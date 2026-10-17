# M271 15-min speed + flow (WebTRIS)

Two files for the forecast engine (Seb's lane), because the shared WebTRIS cache
(`data/cache/`, gitignored) held flow but not a committed speed series:

- `m271_speed_15min.csv.gz`, the full 15-min speed+flow series (join on
  `(site_id, bin_start)`).
- `m271_speed_profile.csv`, a small weekday × time-of-day **median-speed prior**
  (use when you want a smooth speed-by-bin baseline instead of the sparse series).
  Derived from the series by `build_profile.py` here: group by
  `(site_id, road, direction, local weekday, 15-min-of-day)` then median & 15th-pct
  mph, median flow, count. The grain/stats are a **default**, not a spec: edit
  `AGG`/keys in that script and re-run to re-cut (mean, another quantile, term split).

For the five M271 TMU sites on the Western Docks approach.

## Source & licence

- **National Highways WebTRIS** (`webtris.nationalhighways.co.uk`), reports/daily.
- **Open Government Licence v3.0**, redistribution permitted with attribution.
  WebTRIS has no licence page itself; the governing data.gov.uk record is
  "Highways England network journey time and traffic flow data"
  (data.gov.uk/dataset/9562c512-4a0b-45ee-b6ad-afc0f99b841f), licensed OGL v3.0.
- Retrieved Oct 2026 via the WebTRIS API and cached under `data/raw/webtris/`
  (gitignored); these files are the parsed extract of that cache.
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
