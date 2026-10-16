---
doc: track-brief
track: Southampton City
event: SotonShip 2026
partners: [Southampton City Council]
source: Raw/southampton-city-brief.pdf (5 pages, generated 2026-10-15)
see_also: event-rules.md
---

# Southampton City track

## Challenge
Build an **AI-powered product** that solves a real problem for someone who **lives, works or visits in Southampton**, and that you could put in front of them after the weekend. You choose the problem.

**Context:** A port city of ~250,000 with docks, a coastline and two rivers. The council runs hundreds of services on a tight budget. Everyday issues include traffic, air quality, flood risk, housing and access to services.

**Pitch sentence:**
> We help [a specific person] to [do or decide something] in [part of Southampton] using [AI and the data behind it].

*Example:* We help council street-scene officers clear fly-tipping faster across the city by classifying, merging and routing residents' photo reports.

## Who to build for
Pick **one main user**. One neighbourhood, service or kind of journey done well beats covering the whole city.

- **Residents:** student, family, older person, someone with access needs, tenant, small landlord
- **Council officers:** planning, highways, street scene, environmental health, housing, customer services
- **Local business or worker:** retail, hospitality, the port, logistics
- **Visitors:** cruise passenger, new student

## In scope
Any problem connected to life in Southampton: port and coast · transport · environment and climate · housing and planning · streets and public spaces · access to council services.

## Out of scope
- A general Southampton chatbot, or a map or prediction that doesn't lead to a decision
- An existing product with an AI feature added on top
- Anything needing **restricted council systems, real personal data, access to port facilities or physical hardware**, unless an organiser agreed it in advance

## Must show
1. **A real local problem:** who has it, how often, what they do today. Back it with **local** evidence (data, a council document, a conversation). Putting "Southampton" on a generic app doesn't count.
2. **AI the product depends on:** if the product still does its main job without the AI, rethink it. Where the AI classifies, predicts or extracts, beat a simple baseline.
3. **Works on real data:** the main task runs end to end, live, on **genuine Southampton data** with the source and date visible. Synthetic data is OK for testing if labelled.
4. **Business case:** who pays (council, service provider, local businesses, residents), rough cost per user including AI, and what it takes to work in a **second city**.
5. **Honesty about limits:** what it doesn't know, data age, and behaviour when data is missing or stale or **a location is outside coverage**. **Demo at least one failure.**

## Example directions (optional)

### 1. Triage for street reports
- **Problem:** Residents report fly-tipping, potholes and broken street lights as photos and free text, often several times for the same issue.
- **Product:** Classifies each report, merges duplicates, estimates urgency and routes it to the right team. Saves officers hours every week.
- **Buyer:** The council. Every UK council handles the same reports, so there's an obvious path to other cities.
- **Data:** Public **FixMyStreet** reports for Southampton.

### 2. Pre-check for planning applications
- **Problem:** Many householder planning applications are returned as **invalid** because a document or detail is missing. This delays the applicant and costs council staff time.
- **Product:** Reads a draft application and checks it against the council's **validation checklist** and **Local Plan** policies before it is submitted.
- **Buyer:** Sold per check to homeowners and small architects, or licensed by the council to reduce invalid submissions.
- **Data:** The council's public planning register and published policies.

### 3. Licensing support for HMO landlords
- **Problem:** Southampton runs a licensing scheme for **houses in multiple occupation** (HMOs), which matters with a large student population.
- **Product:** Reads a landlord's property details and documents, checks them against the published licence conditions and lists what's missing before an inspection.
- **Buyer:** Letting agents and small landlords. It also reduces failed inspections for the council. Many UK councils run similar schemes.

### 4. Cruise-day planning for local businesses
- **Problem:** Cruise calls bring large numbers of visitors on specific days, but cafés, shops and taxi firms staff by guesswork.
- **Product:** Forecasts demand for a specific business from the cruise schedule, the weather and local events, then turns that into staffing and stock advice.
- **Buyer:** A subscription for businesses, or for the city-centre BID on their behalf. Later, other cruise ports.
- **Baseline:** Assume the same demand as the last comparable cruise day.

## Data sources
None compulsory. Any permitted source is fine if credited. Check Southampton coverage and usage rights early.

| Source | What it offers | Access and limits |
|---|---|---|
| [Environment Agency flood monitoring](https://environment.data.gov.uk/flood-monitoring/doc/reference) | Flood warnings, warning areas, river and tide gauge readings | Open API, no registration; check coverage and timestamps |
| [UKHO Admiralty Tidal API](https://admiraltyapi.portal.azure-api.net/) | Predicted high and low tides | Free registration and key; check tier, forecast horizon, quota |
| [Bus Open Data Service](https://data.bus-data.dft.gov.uk/) | Bus timetables, vehicle locations, fares | Free registration and key; check which local operators and fields are available |
| [Defra UK-AIR](https://uk-air.defra.gov.uk/) | Air-quality measurements from Southampton monitoring sites | Public downloads; check which pollutants are covered and whether data is provisional or ratified |
| [DfT road traffic statistics](https://roadtraffic.dft.gov.uk/) | Traffic counts, annual average flows at Southampton count points | Public downloads; historical averages, **not live traffic** |
| [Met Office Weather DataHub](https://datahub.metoffice.gov.uk/) | Site forecasts, incl. wind | Free account and key; check current products and allowances |
| [Southampton VTS](https://www.southamptonvts.co.uk/) | Cruise schedules, vessel movements | Public web pages; **don't assume an API or permission to redistribute** |
| [Southampton Data Observatory](https://data.southampton.gov.uk/) | Council statistics and reports on population, economy, services | Public; check dates and level of geographic detail |
| [Southampton City Council](https://www.southampton.gov.uk/) | Planning register, Local Plan, HMO licensing conditions, service info | Public pages and documents; check terms before reusing content |

## Track-specific rules (in addition to event-rules.md)
- **Don't collect personal data you don't need.**
- **Don't send non-public council information to an external AI service.**
- For safety, health or emergencies, **link to official guidance** rather than writing your own instructions.

## Pitch must clearly answer
1. What **local evidence** shows the problem is real in Southampton?
2. Who would **own and pay** for the product?
3. What would it take to run it in a **second city**?
