# Local evidence, scale and business numbers (SOT-13)

Why cruise-day vehicle traffic is a real Southampton problem, how big it is, and what the council
could pay for a forecast. Compiled Sat 17 Oct 2026 in Edward's session, with a research
subagent reading public sources. Every fact has its source, publisher, publication date where
shown, and the access date (17 Oct 2026 unless noted). Quotes are exact unless marked as a
paraphrase. **ESTIMATE** marks our own arithmetic, with how it was done; search-engine snippets that
we could not open are marked unverified. Nothing here is from our model.

## Pitch lines (use these)

- **Problem:** Southampton's own transport manager told councillors that cruise growth "currently
  causes significant congestion, especially at weekends, by Dock Gate 4, and this is exacerbated
  when the arrival of 2 or more large cruise ships coincides with a football match" (SCC Scrutiny
  Panel C, 2011). Those are our inputs: the VTS ship list and Saints home fixtures.
- **Why a forecast and not the control room:** on 8 Nov 2010 four liners caused a back-up onto the
  public road "that we were unable to clear through our traffic control computer" (SCC Full
  Council minutes, 17 Nov 2010). Once the queue forms it is too late; the decisions that help
  (hold roadworks, book marshals, set signs) are made days ahead.
- **It is getting bigger:** about 2.7 m cruise passengers in 2024 (DfT; ABP counts 3 m), 88% of the
  UK total. The council's 2012 Dock Gate 4 road model planned for about 1.9 m by 2030.
- **The council already does this by hand:** roadworks suspended on key routes for a ten-ship
  weekend with a Saints home match (Ships Monthly, undated), free buses on a busy cruise weekend
  (SCC, 2010). NRSWA 1991 s.56 lets it set the days works may run when disruption is likely; our
  forecast is the evidence for that test.
- **Price:** a comparable council traffic-data service cost Devon County Council £29,000 a year
  (Find a Tender, Nov 2025). The capital fix, an M271 extension into the port, was "£40m … prohibitive"
  (SCC, 2011).

**One-sentence pitch (draft):** Southampton's traffic team has said for fifteen years that cruise
ships plus a home match jam Dock Gate 4, and passenger numbers have since passed the 2030 planning
case; we read the port's published ship list and the fixtures and say, a week ahead and with
honest odds, which days and hours need roadworks held, marshals booked and signs set.

## Business numbers (design.md §8)

- **Running cost:** a full rebuild of the forecast page ran in 17 minutes on 64 CPU cores on
  Iridis (Seb, SOT-22). **ESTIMATE:** one rebuild a day is about 18 core-hours, a few pounds on any
  cloud VM (no price sourced). The page is a static file, so hosting is close to free.
- **Setup per new city:** the inputs are OpenStreetMap, DfT counts, WebTRIS and the port's
  schedule, all public. Calibration is the work: days, not months, on the evidence of this weekend.
- **Cost of one bad day:** **ESTIMATE (illustrative):** 1,000 cars each delayed 15 minutes is 250
  vehicle-hours; at DfT TAG's £15.56 per car-hour (weekend, 2023 prices) that is about £3,900, and
  each 10 lorries held 30 minutes add about £515 at £102.91 per HGV-hour. The vehicle counts are made
  up for illustration; the rates are TAG's. Officer time, bus delays, missed sailings (Queen Anne
  left 4.5 hours late after gridlock on 11 May 2026) and complaints come on top.
- **Price:** **proposal, not sourced:** under £30k a year for Southampton, anchored on Devon's £29k
  analytics contract and far below the per-call value of a turnaround (£1.9–2.5 m to the region,
  ABP).
- **Scale-out, honestly:** Southampton handles about 88% of UK turnaround passengers, so a
  cruise-only product has one big UK customer. The engine generalises to other scheduled
  event traffic (stadiums, ferry peaks, port freight at Dover and Portsmouth) and to European
  turnaround ports.

---

## Source notes

**Sites we could not use (blocked or bot-challenged, so skipped). A human should check the Echo and the council's news item on temporary traffic plans for busy cruise weekends in a browser:**
- dailyecho.co.uk: our fetcher refuses it (robots/crawler block).
- bbc.co.uk / bbc.com: the same block.
- southampton.gov.uk news pages and transport.southampton.gov.uk (Connected Southampton 2040
  site): both are behind an Incapsula bot challenge. The council's **modernGov PDF papers**
  downloaded normally, without any challenge, and we used those.
- seatrade-cruise.com, afloat.ie, find-tender HTML notices, the Contracts Finder attachment and
  lancashiretelegraph.co.uk: HTTP 403 or blocked. For one find-tender notice we used the
  government's open OCDS API instead.
- The southamptonvts.co.uk passenger-direction PDFs and the Master Plan 2016 PDF now return 404.

---

## 1. Local evidence that cruise turnaround days cause vehicle traffic problems

### Council documents (primary sources)

- **The council's own transport manager: cruise growth is the cause of congestion at Dock Gate 4,
  and it gets worse when ships coincide with football.** Evidence from Frank Baxter (Travel and
  Transport Manager, SCC) to Scrutiny Panel C on 31 Mar 2011: "it is the growth in cruise
  passengers that currently causes significant congestion, especially at weekends, by Dock Gate 4,
  and this is exacerbated when the arrival of 2 or more large cruise ships coincides with a
  football match or IOW regatta." The same evidence says the Transport Assessment "concluded that
  2 key locations are the cause of most congestion problems": **Dock Gate 10** and **Dock Gate 4**.
  It also records that extending the M271 into the port was "of benefit but £40m cost is
  prohibitive" (p.21–22).
  [Southampton City Council, Scrutiny Panel C "Cruise Industry Inquiry" final report, Jan–May 2011](https://southampton.gov.uk/modernGov/documents/s6047/Cruise%20Inquiry%20-App%202%20-%20Final%20report.pdf). Accessed 17 Oct 2026.
- **The same inquiry's findings table:** "Traffic congestion, both current and forecast is limiting
  the competitiveness of the City and poses a significant threat to the expansion of the cruise
  industry" (Table 2, p.8). Same source as above.
- **ABP's Port Director to the same panel:** "congestion on roads is a big issue, especially
  Eastern Docks, and likely to increase as cruise industry grows … Traffic may limit growth of
  cruise industry in City" (Doug Morrison, ABP Southampton, 24 Feb 2011, p.19). Same source.
- **Carnival UK's hourly traffic profile for a turnaround day** (Appendix 3, "Passenger Flow
  (Carnival UK)", p.18). This is the shape our hourly forecast should reproduce:
  06:00 ship arrives (Low) · 08:00 disembarkation starts (Low) · **09:30 disembarkation peak
  (High)** · 10:30 disembarkation ends (Med) · **12:00 embarkation starts (High)** ·
  **13:00 embarkation peak (High)** · 14:00–16:00 slack (Low) · 16:00 end of embarkation (Low) ·
  16:45 ship sails. Same source.
- **Carnival UK said "Saturday busiest day for turnaround"** (David Pickett, Head of Fleet Shore
  Operations, p.20). Same source.
- **A specific bad day, 8 Nov 2010.** A councillor asked how to stop "traffic coming to an almost
  complete standstill across the Itchen Bridge and into the City Centre for hours on end, as
  happened on 8th November, when cruise liners are visiting the City". The Cabinet Member's
  answer: "there were four liners in the port of which three are amongst the worlds biggest …
  Queen Mary located in the wrong berth … ABP having to stop and direct each vehicle to the
  correct Dock gate … This created a back up onto the public highway that we were unable to clear
  through our traffic control computer". It adds that liners "traditionally discharge passengers
  between 09:00 and 11:00 … during the week, these vehicles can extend the peak hour".
  [Southampton City Council, printed minutes of Full Council, 17 Nov 2010, p.44–45](https://www.southampton.gov.uk/moderngov/documents/g1862/Printed%20minutes%2017th-Nov-2010%2014.00%20Council.pdf?T=1). Accessed 17 Oct 2026.
- **A precedent for a paid intervention on a busy cruise weekend.** Same answer: "Last year when
  there was a particularly busy cruise weekend the City Council paid for all buses in the city to
  be free. As a result 60,000 additional trips were made by local resident by bus over that weekend
  alone. The result was that the network was able to cope." Same source (Nov 2010, so "last year"
  means 2009).
- **The council modelled a forecast that roughly doubles travel time at Dock Gate 4.** ROMANSE
  built Aimsun models of the roads around Dock Gates 4 and 10 with Halcrow, using Mott MacDonald
  flow matrices for port growth to 2030. "by expanding the traffic capacity in the locality of
  Platform Road, the prospective increase in travel time from Town Quay to Dock Gate 4 could be
  reduced by around 50%". The paper also says "A component of the traffic growth arises from the
  growth in Cruise Passenger numbers". Graph 1, read off the chart (approximate, **my reading**):
  with the existing layout, travel time Town Quay→DG4 was about 270 s in 2010, about 490 s
  forecast for 2016 and about 545 s for 2030.
  [Southampton City Council, Platform Road Cabinet papers, Appendix 5 (author G. Muir), file dated 27 Nov 2012](https://southampton.gov.uk/modernGov/documents/s14950/Platform%20Road%20-App%205.pdf). Accessed 17 Oct 2026.
- **The 2012 model was planned for about 1.9 m cruise passengers a year by 2030** (Graph 2, from the
  ABP Port Master Plan 2009–2030; the 2011 inquiry also says "approximately 2 million … by 2030").
  ABP reported 3 m in 2024 (see section 2), so **actual cruise volume has already passed the 2030
  figure the road model was built for**. That is my comparison; ABP and the 2011 inquiry both count
  embarking and disembarking passengers separately. Sources: Appendix 5 above and the 2011 inquiry
  report, p.4.
- **Mott MacDonald Transport Assessment (commissioned by SCC in March 2010):** "Dock Gate 4 would
  experience a considerable increase in cruise traffic demand, which would exacerbate the current
  congestion problem", and the "Queen's Park gyratory" was the key issue.
  [Southampton City Council, Platform Road Cabinet papers, Appendix 3 (Interim Team Leader, Traffic Management), 27 Nov 2012](https://southampton.gov.uk/modernGov/documents/s14948/Platform%20Road%20-App%203.pdf). Accessed 17 Oct 2026.
- **The Platform for Prosperity scheme leaflet:** "the gyratory system around Queen's Park becomes
  extremely congested during busy travel periods … It also impedes the possibility of future
  economic growth for key local employers, such as the Port of Southampton". The plan was to dual
  Platform Road and make Dock Gate 4 "inbound traffic only". The scheme was funded by the Regional
  Growth Fund, SCC and ABP.
  [Southampton City Council / Balfour Beatty Living Places / ABP, "Platform for Prosperity" consultation leaflet, file dated 9 Aug 2011](https://southampton.gov.uk/modernGov/documents/s12499/Platform%20for%20Prosperity%20Leaflet.pdf). Accessed 17 Oct 2026.

### News and other reports

- **11 May 2026: a gas scare near Dock Gates 4 and 5.** Access roads were closed. "Congestion
  spread across the city center and dock areas as embarking and disembarking passengers, taxis,
  buses, and cruise transfers all used the same roads" (paraphrase by the fetch tool). Queen Anne
  (about 3,000 passengers) had its departure "pushed back to 8:30 p.m." from 4:00 p.m. "because of
  gridlock around the Ocean Cruise Terminal"; Costa Diadema was delayed by more than an hour.
  Cruise Hive says the Daily Echo called the scene "chaos"; I could not check that directly
  because the Echo is blocked.
  [Cruise Hive (Lissa Poirot), 11 May 2026](https://www.cruisehive.com/port-gas-scare-forces-evacuation-and-delays-ahead-of-southampton-sailing/209096). Accessed 17 Oct 2026.
- **A ten-ship weekend when the council suspended roadworks.** "no fewer than ten cruise ships
  arrived and departed Southampton" over a weekend, with about 55,000 passengers through the port
  on the Saturday and Sunday. The city council "suspended roadworks on key routes" because of
  "additional traffic expected for Southampton FC's home match on Saturday afternoon". **The page
  shows no date** (it is probably about 2017, judging from fleet references).
  [Ships Monthly, "Bumper cruise visit weekend in Southampton", undated](https://shipsmonthly.com/news/bumper-cruise-visit-weekend-in-southampton/). Accessed 17 Oct 2026.
  *This is the exact action our product recommends (hold roadworks, watch for Saints at home).*
- **16 Jul 2011: a six-ship day.** "The facilities were stretched to the limit on 16 July, with
  severe congestion reported on the roads" (search-engine snippet; I did not fetch the full page).
  [Ships Monthly, "Cruise sailings record-breaking Solent sailaway"](https://shipsmonthly.com/news/cruise-sailings-record-breaking-solent-sailaway). Accessed 17 Oct 2026. Unverified beyond the snippet.
- **A resident's complaint (2016).** A letter from Brockenhurst, Hants: passengers said "it took
  them over an hour to exit the dock gates"; "During the football season Southampton FC playing at
  home puts an additional burden on the infrastructure"; "there is only one main route into town".
  [Majorca Daily Bulletin, Letters to the Editor (Nina Ball), 9 Jun 2016](https://www.majorcadailybulletin.com/holiday/life-style/2016/06/09/44230/letters-the-editor-144.html). Accessed 17 Oct 2026.
- **Typical busy weekends: four ships a day.** Fri 21 to Sun 23 June, 12 ships at four a day
  (Anthem of the Seas, Britannia, Seven Seas Splendor, Mein Schiff; Aurora, MSC Virtuosa, Iona,
  Silver Spirit; Norwegian Prima, Arvia, Queen Anne, Queen Mary 2).
  [Isle of Wight County Press, "All the cruise ships in Southampton and The Solent this weekend", no year shown](https://countypress.co.uk/news/24401619.southampton-traffic-cruise-ships-city-weekend). Accessed 17 Oct 2026.
  The year is not printed. 21 June fell on a Friday in 2024 and Queen Anne entered service in 2024,
  so this is **probably 2024 (my inference)**. A second County Press list covers 10 ships on
  Fri 26 to Sun 28 July, also probably 2024 for the same reason:
  [County Press](https://countypress.co.uk/news/24478470.thousands-southampton-cruise-ships-arrive-weekend).
- **ABP: a record number of days when all five terminals were busy at once in 2025.** "a record
  number of days when all five of the Port's cruise terminals where utilised simultaneously"
  (sic). ABP gives no count.
  [ABP, "More cruise records broken for sector leader Southampton in 2025", 23 Dec 2025](https://www.abports.co.uk/news-and-media/latest-news/2025/more-cruise-records-broken-for-sector-leader-southampton-in-2025). Accessed 17 Oct 2026.
- **Council temporary traffic plans for a busy cruise weekend (probably Sept 2021).** I only
  have a search snippet because the page is bot-challenged. It describes a signed city-centre
  diversion "away from the Waterfront", extra lane signs on West Quay Road for "Ikea, the cruise
  terminals and Red Funnel", and staff adjusting signals.
  [Southampton City Council news](https://southampton.gov.uk/news/article/southampton-city-council-announces-temporary-traffic-management-plans-ahead-of-busy-weekend). **Not fetched (Incapsula). Worth a human check in a browser.** It shows the council already does manual, ad-hoc cruise-weekend traffic plans.

---

## 2. Scale numbers

- **2024: 3 million cruise passengers at Southampton**, "surpassing the record set in 2023", and
  "over £1 billion" for the local and regional economy. Southampton "supports 85% of the UK cruise
  market" (ABP's own claim).
  [ABP, "Over £1 billion generated for Southampton from its booming cruise industry", 15 Jan 2025](https://www.abports.co.uk/news-and-media/latest-news/2025/over-1-billion-generated-for-southampton-from-its-booming-cruise-industry). Accessed 17 Oct 2026.
- **2025: "over three million cruise passengers" for the second year running, and "its highest
  ever number of cruise calls".** Solent Stevedores handled **449 ships**, 2.5 m passengers and
  3.3 m items of luggage. Each turnaround call is worth "between £1.9 million and £2.5 million" to
  the region, or "over £1 billion of value" in total (ABP citing Carnival UK's report).
  [ABP, 23 Dec 2025](https://www.abports.co.uk/news-and-media/latest-news/2025/more-cruise-records-broken-for-sector-leader-southampton-in-2025). Accessed 17 Oct 2026.
- **2023: 2.75 m passengers. May 2024: a record 71 calls by 26 ships and over 400,000 guests in
  one month.**
  [ABP, "Record May reaffirms Southampton's leading cruise position", 10 Jun 2024](https://abports.co.uk/news-and-media/latest-news/2024/record-may-reaffirms-southamptons-leading-cruise-position). Accessed 17 Oct 2026.
- **Official statistics (DfT): 2,694,352 cruise passengers at Southampton in 2024**, out of
  3,065,546 for all UK ports, so **87.9 %** of UK cruise passengers (my division). DfT counts
  passengers who start or end a cruise, at both departure and arrival, and excludes transit calls
  (notes 6–7). Southampton's 2019, 2022 and 2023 figures were revised down for "an over-estimation
  of passengers at Southampton" (the table gives values in thousands: 2,694.352).
  [Department for Transport, Sea passenger statistics, all routes 2024, table SPAS0101, published 30 Jul 2025](https://www.gov.uk/government/statistics/sea-passenger-statistics-all-routes-2024) ([data ZIP](https://assets.publishing.service.gov.uk/media/68878f1b741b74390ff0e4bc/sea-passenger-statistics-all-routes-2024.zip)). Accessed 17 Oct 2026.
- **How ABP counts:** "ABP Southampton count, in the figure of 1.4 million passengers, embarking
  and disembarking passengers separately, even if it is the same individual" (2011 inquiry,
  footnote 1, p.3). So 3 m passenger *movements* is **ESTIMATE ≈ 1.5 m individual cruisers**,
  because each turnaround passenger is counted once arriving and once leaving.
- **How passengers reach the port (Carnival UK, 2011):** "In port parking (28% - probably
  higher)", "Coach (25% - probably higher)", "Drop off and other – Train, air etc (remainder)".
  "Transporting luggage is a reason for car usage being high". Carnival then ran 225 turnarounds
  with 497,362 passengers embarking, about 60 % of the port's passengers.
  [SCC Scrutiny Panel C, Cruise Industry Inquiry, 2011, p.20](https://southampton.gov.uk/modernGov/documents/s6047/Cruise%20Inquiry%20-App%202%20-%20Final%20report.pdf). Accessed 17 Oct 2026.
  The figure is 15 years old and covers one operator only. It is the only published mode split I
  found.
  - **ESTIMATE (illustrative, not sourced):** for a 3,000-passenger turnaround, 28 % parking in
    port is about 840 passengers. At an *assumed* 2 passengers per car that is about 420 cars in
    and 420 cars out, before counting drop-offs (each drop-off is two trips), taxis and coaches.
- **Unverified secondary claim:** The Business Magazine (feature on Paris Smith, undated) is quoted
  in search snippets as saying "around two thirds of cruise liner passengers embarking on a cruise
  arrive either in their own vehicles or are dropped off". The page now redirects to the
  magazine's home page, so I could not verify it. [URL](https://www.businessmag.co.uk/features/paris-smith-committed-vibrant-future-port-city-southampton/)
- **Economic value per call:** each large-ship turnaround in the UK "contributes up to £2.5 million
  to the economy", and "This turnaround value equates to £505 million per year". Carnival UK's
  Southampton HQ is worth "£351 million in Gross Value Added" and employs 1,650 full-time staff.
  (Carnival UK's report was produced by WPI Economics.)
  [Cruise Industry News, 17 Jun 2025](https://cruiseindustrynews.com/cruise-news/2025/06/study-shows-carnival-uk-drives-significant-contribution-to-uk-economy). Accessed 17 Oct 2026.
- **Busiest days:** six-ship days happened on 16 Jul 2011 (Ships Monthly snippet above) and were
  scheduled for 31 Aug 2018 (search snippet citing Cruisemapper, not verified). For 2025, ABP says
  only "record number of days" with all five terminals in use. **I found no official
  record-day passenger count for 2024–2026.**

---

## 3. Business numbers for the council as buyer

- **The legal duty: Traffic Management Act 2004, s.16(1)**, the network management duty. The
  authority must manage its network to achieve "(a) securing the expeditious movement of traffic
  on the authority's road network" and "(b) facilitating the expeditious movement of traffic on
  road networks for which another authority is the traffic authority". s.16(2) covers action that
  contributes to "the avoidance, elimination or reduction of road congestion or other disruption
  to the movement of traffic".
  [legislation.gov.uk, Traffic Management Act 2004 s.16](https://www.legislation.gov.uk/ukpga/2004/18/section/16). Accessed 17 Oct 2026.
- **The power to hold roadworks on cruise days: New Roads and Street Works Act 1991, s.56**,
  "Power to give directions as to timing of street works". If works "are likely to cause serious
  disruption to traffic" and "the disruption would be avoided or reduced if the works were carried
  out only at certain times … or on certain days", the authority "may give the undertaker such
  directions as may be appropriate as to the times or days".
  [legislation.gov.uk, NRSWA 1991 s.56](https://www.legislation.gov.uk/ukpga/1991/22/section/56). Accessed 17 Oct 2026.
  *Our forecast supplies the evidence for that "likely to cause serious disruption" test, for
  specific days.*
- **ROMANSE is a small team.** In 2012 ROMANSE provided "Oversight and management of the road
  network via the control room", traffic modelling and all ITS (signals, electronic signs). "The
  service has a current establishment of 9 FTE … due to be reduced to 5.5 FTE by the commencement
  of the contract, in order to achieve required savings." CCTV had 12 FTE, falling to 9.
  [Southampton City Council, "ROMTV" Cabinet paper, Appendix 1, file dated 4 Apr 2012](https://southampton.gov.uk/modernGov/documents/s8327/ROMTV%20-App%201.pdf). Accessed 17 Oct 2026.
  **I found no current (2024–26) ROMANSE budget or headcount.**
- **Value of time (DfT TAG data book v2.03, May 2026), Table A1.3.5, market-price value of time
  per vehicle, £/hour, 2023 prices:** average car on a weekend **£15.56/h**, average car all week
  £15.65/h, car on work trips £30.54/h on weekdays, average LGV £28.54/h weekdays,
  **OGV £102.91/h**. The tables also say "should be used for modelling purposes only".
  [DfT, TAG data book v2.03, page updated 28 May 2026](https://www.gov.uk/government/publications/tag-data-book) ([xlsm](https://assets.publishing.service.gov.uk/media/6a576e102f6185941a9a6569/tag-data-book-v2-03.xlsm)). Accessed 17 Oct 2026.
  - **ESTIMATE (illustrative):** 1,000 cars each delayed 15 min is 250 vehicle-hours,
    × £15.56 = **about £3,900 of delay per event**, before freight. Each 10 HGVs held for 30 min
    add about £515 (5 vehicle-hours × £102.91). The car and HGV counts are made up for
    illustration; the rates are TAG's.
- **The national cost of congestion (INRIX 2024 Scorecard):** the average UK driver lost 62 hours
  in 2024, "equating £581 per driver per year"; the UK as a whole lost £7.7 bn. **Southampton is
  not in INRIX's UK top 10**, and I found no Southampton figure.
  [INRIX, 2024 Global Traffic Scorecard UK, 6 Jan 2025](https://inrix.com/press-releases/2024-global-traffic-scorecard-uk/). Accessed 17 Oct 2026.
- **TomTom Traffic Index, Southampton:** a search snippet gave an average congestion level of
  50.2 %, 24 min 12 s per 10 km, 88 h lost in rush hour, and 2 Dec as the worst day. The page did
  not render for my fetcher, so **this is unverified**. [TomTom](https://www.tomtom.com/traffic-index/southampton-traffic)
- **Traffic marshal cost:** I found **no published client day rate**. The only figures are worker
  pay rates from job adverts (about £16.50–£21/h, 2025–26), which search snippets show on
  findajob.dwp.gov.uk. One 2022 public-sector "Pricing Schedule for Marshal Services" is quoted in
  snippets at £13.50/h for traffic-management marshals, but Contracts Finder returned 403, so it is
  unverified. **ESTIMATE:** one marshal on a 10-hour shift at an assumed £25–35/h charge-out rate
  costs about £250–350 a day. The charge-out rate is my assumption, not sourced.
- **A comparable council purchase of traffic analytics:** Devon County Council bought "Devon Wide
  Traffic Data Journey Time & Travel Patterns" from Compass IoT Ltd for **£29,000 ex VAT**
  (£34,800 inc VAT), awarded 28 Nov 2025, running 11 Dec 2025–10 Dec 2026 with an optional
  12-month extension. It drew 5 tenders, all from SMEs.
  [Find a Tender OCDS record ocds-h6vhtk-05cc4d (award notice 078271-2025, 28 Nov 2025)](https://www.find-tender.service.gov.uk/api/1.0/ocdsRecordPackages/ocds-h6vhtk-05cc4d). Accessed 17 Oct 2026.
  This is the best public anchor for pricing: **roughly £30k a year for a single council analytics
  data service.**
- **G-Cloud 14 benchmark (not traffic-specific):** search snippets show Xantura OneView, a general
  council data platform, at £100k a year licence for councils up to 500k residents. I did not
  fetch the pricing PDF, so this is unverified.
  [Digital Marketplace pricing doc](https://assets.applytosupply.digitalmarketplace.service.gov.uk/g-cloud-14/documents/700637/682099285208128-pricing-document-2026-03-18-1447.pdf)
- **Capital alternatives are far more expensive:** extending the M271 into the port was "£40m cost
  is prohibitive" (2011 inquiry, p.22, above). Platform Road was dualled with Regional Growth
  Fund, SCC and ABP money (leaflet above). A search snippet gives RGF £5.595m plus a £1.445m
  council match, but I did not fetch that document.

---

## 4. Second city / scale-out

Official DfT 2024 cruise passengers (thousands; embarking plus disembarking, transit calls
excluded), from table SPAS0101
([DfT, 30 Jul 2025](https://www.gov.uk/government/statistics/sea-passenger-statistics-all-routes-2024), accessed 17 Oct 2026):

| Port | 2023 | 2024 |
|---|---|---|
| Southampton | 2,344.4 | **2,694.4** |
| London (Tilbury etc.) | 70.8 | 101.9 |
| Dover | 72.7 | 74.5 |
| Portsmouth | 46.4 | 53.6 |
| Liverpool | 51.2 | 50.1 |
| Tyne | 32.4 | 46.8 |
| Forth | 22.3 | 18.3 |
| All UK | 2,645.8 | 3,065.5 |

Belfast and Greenock are mostly transit (port-of-call) ports, so they do not appear separately in
this turnaround-focused table.

- **Portsmouth:** a record "94 cruise ships will sail into Portsmouth harbour" in 2025. The new
  terminal "has now welcomed over 168,000 cruise passengers" (2024), and each call generates "up to
  £1.5million for the city's economy".
  [Cruise Britain, 3 Jan 2025](https://www.cruisebritain.org/news/portsmouth-international-port-cruises-into-2025-with-another-record-breaking-year/). Accessed 17 Oct 2026.
  (168k is a terminal headcount; DfT's 53.6k excludes transit passengers, so the two figures
  measure different things.) **I found no Portsmouth cruise-day traffic reporting.**
- **Dover:** 91 calls booked for 2025, about half of them turnarounds. It "typically welcomes about
  200,000 cruise guests" a year and can berth three ships at once (search snippets from Seatrade
  and Cruise Hive; Seatrade returned 403, so these are unverified). Kent's traffic problems are
  ferry and freight (Operation Brock on the M20), not cruise: Dover District Council's residents'
  letter for summer 2026 describes the M20 contraflow from 14 July to 24 August.
  [Dover District Council, "Letter to residents Summer Brock 2026"](https://www.dover.gov.uk/Community/Emergency-Planning-CCTV/Letter-to-residents-Summer-Brock-2026-FINAL.pdf) (search snippet; not fetched).
  Dover suits a multi-cause port-traffic product rather than a cruise-only one.
- **Liverpool:** DfT gives 50.1k turnaround passengers in 2024. Global Ports Holding took over
  operations with up to £25m of planned investment, and a March 2026 Cruisemapper piece projects
  118 calls and about 350k passengers and crew for 2026 (search snippets, unverified).
  **No cruise-day traffic reporting found.**
- **London Tilbury:** DfT gives 101.9k (the "London" row) in 2024. It is the home port of
  Ambassador Cruise Line. **No traffic reporting found.**
- **Greenock (Clyde):** "145,166 passengers across 82 ship calls" in 2025, and "75 calls and an
  estimated 145,000 passengers already forecast for 2026". It is mostly a port of call; passengers
  leave by coach.
  [Cruise Britain, 24 Nov 2025](https://www.cruisebritain.org/news/greenock-cruise-port-celebrates-record-breaking-2025-season/). Accessed 17 Oct 2026.
- **Belfast:** the 2025 pre-season plan was "146 calls by 57 ships from 31 different cruise lines",
  about 225,000 passengers and "over 100,000 crew members", eight turnarounds and "£20m-£25m to the
  local economy".
  [Belfast Harbour, 2025 season release, undated](https://www.belfast-harbour.co.uk/?p=19295). Accessed 17 Oct 2026.
  An Afloat.ie piece (403, so search snippet only) reports that the season ended with 147 visits
  and a £90m terminal plan.
- **Cruise-day traffic news at the other ports:** I found **none** for Portsmouth, Dover,
  Liverpool, Tilbury, Greenock or Belfast. The nearest UK example is Orkney, where the council is
  capping cruise passengers at 5,000 at a time, partly over pressure on roads (search snippet,
  travelgossip.co.uk, unverified). **The honest scale-out story:** Southampton is about 88 % of UK
  turnaround volume, so the UK market for a cruise-only product is essentially one city. The
  scale-out is either (a) the same engine applied to other scheduled-event drivers at other
  councils (ferry peaks, stadiums, freight at Dover and Portsmouth), or (b) European turnaround
  ports. I did not research (b).

---

## Strongest five facts

1. **The council's own transport manager said it:** cruise growth "currently causes significant
   congestion, especially at weekends, by Dock Gate 4, and this is exacerbated when the arrival of
   2 or more large cruise ships coincides with a football match". These are exactly our inputs:
   ships plus Saints.
   ([SCC Scrutiny Panel C, 2011, p.21](https://southampton.gov.uk/modernGov/documents/s6047/Cruise%20Inquiry%20-App%202%20-%20Final%20report.pdf))
2. **8 Nov 2010:** four liners and one ship in the wrong berth produced a back-up onto the public
   highway "that we were unable to clear through our traffic control computer". Traffic on the
   Itchen Bridge was at an "almost complete standstill … for hours". The control room cannot fix
   this live; it needs warning in advance.
   ([SCC Council minutes, 17 Nov 2010](https://www.southampton.gov.uk/moderngov/documents/g1862/Printed%20minutes%2017th-Nov-2010%2014.00%20Council.pdf?T=1))
3. **The scale is now about 2.7 m official (DfT) or 3 m (ABP) cruise passengers a year, 88 % of
   the UK total**, with a record number of five-terminal days in 2025. The council's 2012 road
   model planned for about 1.9 m by 2030, so volume has already passed the planning case.
   ([DfT SPAS0101, 2025](https://www.gov.uk/government/statistics/sea-passenger-statistics-all-routes-2024); [ABP, 23 Dec 2025](https://www.abports.co.uk/news-and-media/latest-news/2025/more-cruise-records-broken-for-sector-leader-southampton-in-2025); [SCC App 5, 2012](https://southampton.gov.uk/modernGov/documents/s14950/Platform%20Road%20-App%205.pdf))
4. **The council already takes these actions by hand:** it has suspended roadworks on key routes
   for a ten-ship weekend with a Saints home match, paid for free buses on a busy cruise weekend
   (60,000 extra trips, "the network was able to cope"), and run Waterfront diversions. NRSWA s.56
   gives it the power to time roadworks around predicted disruption. We turn a reactive habit
   into a planned forecast.
   ([Ships Monthly, undated](https://shipsmonthly.com/news/bumper-cruise-visit-weekend-in-southampton/); [SCC minutes 2010](https://www.southampton.gov.uk/moderngov/documents/g1862/Printed%20minutes%2017th-Nov-2010%2014.00%20Council.pdf?T=1); [NRSWA s.56](https://www.legislation.gov.uk/ukpga/1991/22/section/56))
5. **The price fits the budget:** each turnaround is worth £1.9–2.5 m to the region (ABP), the
   capital fix (M271 extension) was £40 m and "prohibitive", ROMANSE was cut to 5.5 FTE, and a
   comparable council traffic-data service cost Devon £29k a year (2025).
   ([ABP 2025](https://www.abports.co.uk/news-and-media/latest-news/2025/more-cruise-records-broken-for-sector-leader-southampton-in-2025); [SCC 2011 inquiry](https://southampton.gov.uk/modernGov/documents/s6047/Cruise%20Inquiry%20-App%202%20-%20Final%20report.pdf); [SCC ROMTV App 1, 2012](https://southampton.gov.uk/modernGov/documents/s8327/ROMTV%20-App%201.pdf); [Find a Tender OCDS](https://www.find-tender.service.gov.uk/api/1.0/ocdsRecordPackages/ocds-h6vhtk-05cc4d))

## Gaps

- **No recent (2022–26) council paper** on cruise traffic. The Connected Southampton 2040 site and
  the council's news pages are bot-challenged. Someone should open them in a browser, especially
  the LTP4 text on the port and the "temporary traffic management plans ahead of busy weekend"
  news item.
- **No Daily Echo or BBC coverage was usable** (both blocked). The Echo is the most likely source
  of dated bad-day stories; a human should search it by hand.
- **The mode-share figure is from 2011 and covers one operator** (Carnival: 28 % park, 25 % coach).
  I found no current ABP figure for car, taxi or coach share. The "two thirds by car or drop-off"
  claim is unverified.
- **No record-day passenger count** for 2024–26, and ABP gives no count of five-terminal days.
- **No current ROMANSE budget or headcount** (only 2012 figures), and no published client day rate
  for traffic marshals or VMS deployment.
- **No Southampton-specific congestion cost** from INRIX (not in its UK top 10); the TomTom figures
  are unverified.
- **The final ABP Master Plan 2016–2035** has no fetchable copy (404), so its cruise road-traffic
  forecasts are missing.
- **No cruise-day traffic news found for any other UK port.** Full-year 2025 figures for Dover,
  Liverpool, Tilbury and Portsmouth are also missing.
- **The Ships Monthly ten-ship weekend story is undated**, and the County Press weekend lists give
  no year (2024 is inferred).
