# Port freight ship calls from Southampton VTS (for SOT-24)

Checked Sat 17 Oct 2026 by Keanu's Claude. Code: `src/sotonship26/data/vts_freight.py`, tests in
`tests/test_vts_freight.py` (synthetic XML only). Data credit: **Southampton VTS, ABP**.

## What the feeds are

The VTS "shipping movements" pages load two public XML files (robots.txt allows them; fetched with
the same User-Agent as Edward's cruise loader):

| Feed | What one row is | Horizon |
|---|---|---|
| `https://www.southamptonvts.co.uk/xml/sotextract.xml` | One planned movement: ship, type, `eta_etd`, `voyage_type`, `origin`, `destination`, IMO (`lloyds_no.`), gt, dwt, loa, draft, agent, approach (`dir`: Nab / Needles / Southern), `abp_port` | 17 Oct 09:30 to 22 Oct 23:59 in the 17 Oct 08:56 UTC copy, so about 5 days |
| `https://www.southamptonvts.co.uk/xml/sotberthed.xml` | One ship alongside now: berth, actual arrival time, estimated departure time (blank for tugs and barges, "AM"/"PM" when not fixed), gt, type, IMO, agent | Now only |

How the extract encodes movements (128 rows on 17 Oct):

- `voyage_type` **A** = arrival from sea (54 rows; `destination` is the berth), **D** = departure to
  sea (62; `origin` is the berth), **M** = move between two places inside the port (12; `dir`
  blank). The loader calls these `arrival`, `departure`, `shift`, and puts the port end in `berth`.
- A ship calling twice (in and out) is two rows, so a "call" in the daily table is a movement.
- Times are `17-Oct-2026 09:30`, or `AM` / `PM` / `TBA` when VTS hasn't fixed them (19 of 128
  rows). Those get a stand-in (09:00 / 15:00 / 12:00) and `time_confirmed=False`. Only the day is
  used downstream.
- Movements that already happened today are gone. SIEM EDISON is alongside at berth 101 with an
  actual arrival of 03:02 on 17 Oct, yet the 17 Oct extract has no arrival row for it. So the day
  a snapshot is taken is always incomplete.
- `abp_port` is "Southampton" for 123 rows and "Solent Misc" for 5 (Esso Fawley tankers and
  anchorage moves).

## Categories

Type codes seen across both 17 Oct feeds, with the category the loader gives them:

| Category | VTS types seen (extract count) | Lorry-relevant |
|---|---|---|
| `container` | Container Carrier (UCC) 38 | yes |
| `roro` | Ro/Ro (URR) 21, Vehicle (MVE) 7, Ro/Ro/C.C. (URC) 2 | yes |
| `cruise` | Passenger (MPR) 16 | no |
| `ferry` | Ferry (OFY) 1 (Red Jet), Passenger Ro/Ro (PRR) 1 (Red Funnel) | no |
| `bulk_tanker` | Chemical Tank (TCH) 12, Tank (TTA) 7, Lpg (LPG) 6, Cement (BCE) 2, Lng (LNG) 1 | no |
| `other` | General Cargo (GGC) 5, Barge (OBA) 4, Hopper Dredger (DHD), Barge Carrier (UBG), Semi-sub HL Vessel (OHL), Research (RRE), one MPR (below). Berthed feed only: Tug (XTG), Work Ship (OWO), AUV, Fishing (FFS), Tug/Supply (XTS), Pilot Ship (OPI), Standby Safety Vessel (OSZ), Firefighting Tug (XFF), Waste Ship (OWA) | no |

Rules beyond the code lookup:

- Agent "RED FUNNEL ..." is `ferry` whatever the code. Red Funnel's ro-pax ships (RED KESTREL,
  RED OSPREY) carry Isle of Wight lorries, but through the Town Quay terminal, not the docks, so
  they are a separate flow. Any other PRR ship would count as `roro` (none seen). The Hythe ferry
  did not appear, so it isn't mapped.
- MPR under 10,000 gt is `other`: SHIELDHALL, the 1,753 gt museum steamship, is typed MPR. The
  smallest cruise ship seen is 76,152 gt.
- Unseen codes starting T or B (tankers, bulk) fall to `bulk_tanker`; anything else unseen is
  `other`. General cargo (GGC: small coasters at 109 and the KGV dock) is `other`. Those ships do
  generate some lorries, but we can't size them.

## Berth to dock area

From public berth numbering: Wikipedia "Port of Southampton", the ABP Port Master Plan 2016
(ch. 2) and the ABP Southampton Port Plan 2022 map. Berths 20–49 are the Eastern (old) Docks,
101–110 the Western Docks, and 201–207 the container terminal. The container berths are now
named SCT1–4 (old 207–204) and SCT5 (old 201/202), run by DP World Southampton.

| `area` | Berth names it covers | Seen 17 Oct |
|---|---|---|
| `container_terminal` | `SCT1`…`SCT5`, combos like `SCT1/2`, `SCT2/3`; numeric 201–207 | all 38 container movements |
| `western_docks` | 101–110 (incl. `104W`), "Western Docks", "KGV Dock West Side" (King George V dry dock) | 11 ro-ro movements (101, 102, 105, "Western Docks") |
| `eastern_docks` | 20–49 by leading number (`38/9`, `40/41`, `46 O/S`), "Eastern Docks (R.Test)" | 16 ro-ro movements (25, 31, 35, 40/41, 44, "Eastern Docks") |
| `fawley` | "Esso Berth N", "Esso Tug Berth" (Esso Fawley refinery jetty) | 20 tanker movements |
| `unknown` | everything else | see below |

The area is a dock area, not a terminal function. Car carriers use cruise berths: SIEM EDISON
(URR) is at berth 101 (City Cruise Terminal), and two ro-ro ships shift to 102 (Horizon). Use
`category` for the trade and `area` for the dock gate.

**Not mapped (left `unknown`):** `SGL3`, `SGL4` (one ro-ro arrival, GRANDE TIANJIN, plus barges).
Probably ABP Solent Gateway at Marchwood, but the prefix is our guess and no source we found
spells it out. Marchwood traffic would reach the road network via the A326, not the city docks.
Also left `unknown`: Town Quay, Royal Pier, Marchwood Quay / Moorings, Burnley Wharf, Dibles Gut,
Fawley Power Station, Upper SG (Upper Swinging Ground), anchorages, and place names at the sea
end.

## Today's numbers (one live snapshot, 17 Oct 2026 08:56 UTC)

Planned container and ro-ro movements per day, from `daily_freight_calls` (arr = arrivals from
sea, dep = departures to sea, gt = summed gross tonnage of those movements):

| Date | container arr | container dep | ro-ro arr | ro-ro dep | container gt | ro-ro gt | unconfirmed times | complete |
|---|---|---|---|---|---|---|---|---|
| Sat 17 Oct | 2 | 0 | 4 | 4 | 104,967 | 432,577 | 0 | **no** (snapshot day) |
| Sun 18 Oct | 2 | 4 | 3 | 2 | 559,875 | 389,227 | 0 | yes |
| Mon 19 Oct | 3 | 2 | 1 | 3 | 407,216 | 309,270 | 0 | yes |
| Tue 20 Oct | 3 | 2 | 2 | 1 | 412,183 | 225,416 | 1 | yes |
| Wed 21 Oct | 5 | 6 | 1 | 2 | 1,078,770 | 114,275 | 1 | yes |
| Thu 22 Oct | 4 | 5 | 2 | 3 | 608,017 | 326,819 | 1 | yes |

At fetch time 4 of 47 ships alongside were container or ro-ro (2 at SCT, GLOVIS SYMPHONY at 31,
SIEM EDISON at 101). These are aggregates of ABP data; don't publish the per-ship rows.

## Honest limits

- **No history.** Nothing before 17 Oct 2026. The Wayback Machine route that worked for cruise
  pages wasn't checked for these feeds. History only builds up if we snapshot (below). A
  regression of lorry counts on ship calls needs weeks of snapshots matched to DfT or WebTRIS
  days. We don't have that, so any SOT-24 use before then is a stated assumption, not a fit.
- **Planned, not actual.** The extract is the plan as of the snapshot. Times shift and calls
  slip. The union keeps the newest snapshot's version of each (ship, direction, day). A movement
  that slips past midnight between snapshots will show on both days.
- **Horizon about 5 days**, so a forecast further out has no freight signal.
- **"complete" assumes the last listed day is whole.** The 17 Oct copy ends at 22 Oct 23:59, which
  suggests whole days, but one snapshot can't prove it.
- Ship calls are a proxy. gt is ship size, not boxes or cars handled. Container exchange per call
  varies a lot (a 141,000 gt deep-sea ship vs a 10,600 gt feeder), and much container traffic
  leaves by rail (ABP: 23 container trains a day).
- **Terms.** ABP owns the content. Its terms allow downloading extracts for personal reference,
  require acknowledging ABP, and bar commercial use without a licence. This is non-commercial
  student research (team decision). Raw XML stays in gitignored `data/raw/vts_freight/`, and only
  aggregates go in the app or pitch, credited "Southampton VTS, ABP".

## Taking snapshots (not installed; ask the human)

The extract only looks about 5 days ahead, so take a snapshot every 6 hours.

crontab (`crontab -e`):

```
0 */6 * * * cd /home/keanu/hackathons/sotonship/Sotonship26 && mkdir -p data/raw/vts_freight && uv run -q python -m sotonship26.data.vts_freight --snapshot >> data/raw/vts_freight/cron.log 2>&1
```

or a systemd user timer:

```ini
# ~/.config/systemd/user/vts-freight.service
[Unit]
Description=Snapshot Southampton VTS freight feeds
[Service]
Type=oneshot
WorkingDirectory=/home/keanu/hackathons/sotonship/Sotonship26
ExecStart=/usr/bin/env uv run -q python -m sotonship26.data.vts_freight --snapshot

# ~/.config/systemd/user/vts-freight.timer
[Unit]
Description=Snapshot Southampton VTS freight feeds every 6 h
[Timer]
OnCalendar=*-*-* 00/6:00:00
Persistent=true
[Install]
WantedBy=timers.target
```

Enable with `systemctl --user enable --now vts-freight.timer`.

`python -m sotonship26.data.vts_freight` (no flag) prints the summary and daily table from the
cached snapshots.

## How SOT-24 could use it

Seb's freight trip type is fitted to DfT HGV counts (about 5,900 HGV/day on the M271). The DfT
count is an annual average, so it carries no day-to-day ship signal. A simple, honest use:

1. Keep the DfT-fitted port-lorry total as the **average day**.
2. Scale a forecast day's port-lorry demand by `freight_moves` (or `container_*_gt + roro_*_gt`)
   for that day over its mean across complete days. With today's snapshot the complete days
   range from 8 to 14 movements (mean 11.2). The factor is an assumption to label as such until
   snapshots and observed counts can fit it.
3. Optionally split by area: container terminal and Western Docks traffic leaves by the Western
   Docks gates toward the M271; Eastern Docks car traffic leaves by the Eastern Docks gates. That
   needs the per-movement rows (`parse_extract`, `area`), not the daily table.
4. Use only days with `complete=True`. A snapshot-day row undercounts.
