# Data spike: observed traffic for cruise-day uplift (SOT-5)

Checked Fri 16 Oct 2026, 23:00–23:30 BST, by Keanu's Claude. Every number below came from a live
API call or page fetch made at that time.

## Recommendation

**Use National Highways WebTRIS 15-minute counts on the M271 between M27 J3 and Redbridge
roundabout (A35) as the observed signal.** It is the only free source with 15-minute history
covering 2024–2026 on a road that cruise traffic for the **Western Docks** (City 101, Horizon
102, Mayflower 106) must use when it comes from the M27 west, the M3/M27 east or London via
M3→M27→M271. It needs no key and is open data. Add **M3 J14 (site 20025)** as a second signal for the
Eastern Docks (Ocean 46, QEII 38/39) approach via the A33, which has the best coverage of any
nearby site.

Sites to pull (combine both directions; coverage = days with ≥90 % data quality):

| WebTRIS Id | Name | Where | Direction | Lat, Lon | Cruise-season coverage |
|---|---|---|---|---|---|
| **19974** | TMU 5120/1 | M271 between A35 (Redbridge) and J1 | Northbound (out of docks) | 50.92695, -1.47221 | Oct 2024 – Mar 2025, Sep 2025 – Jun 2026 (410 good days) |
| **19796** | TMU 9997/1 | M271 between J1 and A35 (Redbridge) | Southbound (into docks) | 50.92686, -1.47135 | Jul–Nov 2024, Aug–Oct 2025, Feb–May 2026 (184 good days) |
| **20313** / **20605** | TMU 5493/1, 5493/2 | M271 between M27 J3 and A3057 | SB / NB | 50.95205, -1.47471 | Oct 2024 – Jun 2025 (280 / 209 good days) |
| **7588** | TMU 5550/1 | M271 between J1 and M27 | Northbound | 50.93924, -1.47329 | Jan 2022 – Jul 2024 (910 good days; dead since) |
| **20025** (+ 20026–20028) | MIDAS M3/2161A | M3 at J14 (start of A33 to the Eastern Docks) | Westbound | 50.96785, -1.38021 | Nov 2023 – Jun 2026 (937 good days, near-continuous) |

Put together, the M271 sites give at least one direction for cruise season 2024 (Apr–Nov), Apr–Jun
2025, Sep–Oct 2025 and Feb–Jun 2026. That is enough for a time-split backtest (train 2024–spring
2025, test Sep 2025 – Jun 2026).

**Biggest risk:** WebTRIS lags about 3.5 months (latest good day on every site is 29 Jun 2026),
so **there is no observed data for this weekend or summer 2026**. The demo can't compare
tonight's forecast with live counts. Say so on screen and in the pitch. The second risk is that
M271/M3 are motorways 5–7 km from the gates, so the cruise uplift is a small share of the flow
(the M271 NB carried ~26,900 vehicles on Sat 13 Sep 2025). We need the baselines to show the
uplift can be detected at all before relying on it.

## Sample pull (works, no key)

`GET https://webtris.nationalhighways.co.uk/api/v1.0/reports/Daily?sites=19974&start_date=13092025&end_date=13092025&page=1&page_size=100`
returns 96 rows (one per 15 min). Columns: `Site Name, Report Date, Time Period Ending,
Time Interval, 0 - 520 cm, 521 - 660 cm, 661 - 1160 cm, 1160+ cm, <speed bins>, Avg mph,
Total Volume`. Length bins let us separate cars (0–520 cm) from coaches/HGVs (1160+ cm).

| Site | Date | Period ending | Interval | Total volume | Avg mph | 0–520 cm | 1160+ cm |
|---|---|---|---|---|---|---|---|
| 5120/1 | 2025-09-13 | 07:14 | 28 | 185 | 50 | 151 | 4 |
| 5120/1 | 2025-09-13 | 07:29 | 29 | 240 | 51 | 192 | 12 |
| 5120/1 | 2025-09-13 | 07:44 | 30 | 311 | 51 | 237 | 19 |
| 5120/1 | 2025-09-13 | 07:59 | 31 | 322 | 49 | 259 | 16 |
| 5120/1 | 2025-09-13 | 08:14 | 32 | 375 | 49 | 284 | 17 |

Day total 26,896 vehicles. The same day on 19796 (southbound) returns rows with empty volumes,
which matches its quality gap. **Always check `/quality/daily?siteId=…` first** and drop days
under 90 %.

Other endpoints used: `/sites` (20,076 sites; filtered to 276 within 8 km of 50.900, -1.410),
`/quality/overall?sites=…`, `/quality/daily?siteId=…`. Dates are `DDMMYYYY`. Reports need
`page` and `page_size`.

## Licence

| Source | Licence | Evidence |
|---|---|---|
| WebTRIS API | Open data, no registration. Listed on DfT's *Find transport data* as "Free, Other (Open)". National Highways says its web content is reusable under OGL v3.0. | webtris.nationalhighways.co.uk/api/swagger/ui/index; findtransportdata.dft.gov.uk/dataset/webtris-traffic-flow-api; nationalhighways.co.uk terms page |
| Attribution to use | "Contains National Highways data © Crown copyright and database right 2026, licensed under the Open Government Licence v3.0" | Standard OGL wording. **Don't** use the Developer Portal licence (that covers the NTIS feeds, not WebTRIS, and bans automated extraction). |
| DfT road traffic statistics | OGL v3.0 | roadtraffic.dft.gov.uk footer |

## Alternatives checked

| Source | What it gives | Verdict |
|---|---|---|
| **DfT count points, Southampton (LA 137)** | 129 count points; raw counts are **one manual 12-hour count day per year** (07:00–19:00, hourly), plus AADF | Use for **background load** (Seb, SOT-10), not for uplift. Dock-area points: **75251** A33 Mountbatten Way→Southern Rd (counted 2024), **56347** A33 A35→West Quay Rd (2023), **57672** A33 West Quay Rd→A3024 (2022), **75252** A33 Southern Rd→B3039 (2020), **38212** A33 B3039→A33 split (2022), **86003** A33 Town Quay→Terminus Terrace (2024), **90217** A33 M271→A3024 / Millbrook Rd (2025), **26371** A35 A33→A3057 Redbridge Rd (2025), **26062** M271 A35→LA boundary (2024), **6933** A33 Kingsway roundabout (2025), **17532** A33 Threefield Lane→A3024 (2025). CSVs: `storage.googleapis.com/dft-statistics/road-traffic/downloads/{countpoints,rawcount,aadfbydirection}/local_authority_id/…_137.csv` |
| Southampton City Council / ROMANSE | ROMANSE runs the control room and "road travel data collection and distribution" (council transparency reports, Oct 2023, Apr 2025). **No public 15-minute feed or download found.** | Ask council staff on Saturday (SOT-15) whether they would share dock-road loop or ANPR counts. That would be the best possible signal, but don't plan on it. |
| Southampton Data Observatory | Annual statistics and reports | No traffic time series |
| TomTom / Google typical traffic | Speeds and typical congestion, near the gates | Commercial terms; you can't store or redistribute the data, and you can't backtest without paying for history. Skip. |
| Bus Open Data (BODS) AVL | Live bus positions, which could give a delay proxy on Western Esplanade / Town Quay | Has history only if we archive it ourselves (none before tonight). Possible live demo signal, not usable for training. |
| GB Traffic Data Explorer (trg-apps.soton.ac.uk/gbtraffic) | A Southampton University visualiser of DfT data, 2000–2023 | Same data as DfT; useful for the local-evidence story |

## Historic cruise calls (for SOT-6)

| Source | Past calls? | Fields | Terms |
|---|---|---|---|
| **cruisetimetables.com**, `southampton-england-cruise-ship-schedule-2025.html` (per-day pages like `southamptonenglandschedule-14jun2025.html`; a `-2024` page is likely but **not checked**) | **Yes**: the 2025 page lists past calls (Nov–Dec 2025 confirmed) | Date, line, ship, passenger capacity, some arrival/departure times. **No terminal.** | "Terms of Content Use" link (Raptive ad site). Treat as copyrighted: scrape for internal training only, keep raw HTML/CSV out of git, cite in the README. |
| cruisemapper.com `ports/southampton-port-115?month=YYYY-MM` | The month parameter seemed to serve only current/future months (`2025-06` returned the general page) | Ship, arrival, departure | Terms of use page; same caution |
| crew-center.com Southampton schedule | Per-day pages for 2024–2025 (Google snippets: "Schedule for 19 May 2024 with call dates, ship names, passenger numbers") | Ship, line, passengers, times | No licence; same caution |
| Southampton VTS (ABP) | **Forward only** (provisional schedule plus 5-day planned movements). Gives the **berth/terminal**. | Ship, berth, times | "© ABP, all rights reserved". Use for the live forecast; no redistribution (already in design.md) |

**Terminal for historic calls** has to be inferred. Line-to-terminal habits are fairly stable
(Cunard → QEII/Ocean, MSC → Horizon, Royal Caribbean/NCL → City/Ocean, P&O → Ocean/Mayflower),
but **this is an assumption**. Mark it `calibrate`, and check a few 2025 dates against archived
VTS pages on web.archive.org if time allows.

## Suggested next steps for SOT-7

1. Pull 15-min data for 19974, 19796, 20313, 20605, 7588 and 20025 from 1 Jan 2024 to 29 Jun 2026
   (about 30 calls per site per month of `page_size=…` paging). Cache under `data/raw/webtris/`,
   which is git-ignored.
2. Scrape the cruisetimetables 2024/2025/2026 year pages → `ship, date, line, capacity`.
3. Uplift = flow − median(flow) for the same site, weekday and 15-min bin on **non-cruise** days
   within ±6 weeks.
4. First check: are Saturday turnaround days visibly above non-cruise Saturdays at 07:00–11:00
   (inbound) and 09:00–13:00 (outbound)? If not, the signal is too weak, and the pitch must lead
   with the simulation, not the learned calibration.
