"""Collect the Southampton VTS cruise schedule into data/raw/cruise_schedule.csv.

Reads the XML file behind ABP Southampton VTS's public cruise ship schedule page, maps each berth to
its terminal the way that page does, adds each ship's lower-berth capacity from the cruise line's
published ship facts (CAPACITY below) and writes the columns sotonship26.data.cruise.load_schedule
reads, plus where each value came from and when it was collected.

data/raw/ is gitignored and must stay that way: ABP's terms of use allow extracts for personal
reference only, so the CSV is never committed or shared. Synthetic_demo.py falls back to its
invented schedule when the file is missing.

    uv run --no-project --python 3.12 python demo/collect_schedule.py
"""

from __future__ import annotations

import argparse
import csv
import statistics
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "data" / "raw" / "cruise_schedule.csv"
# The feed behind https://www.southamptonvts.co.uk/live_information/
# shipping_movements_and_cruise_ship_schedule/cruise_ship_schedule/
FEED = "https://www.southamptonvts.co.uk/xml/sotcruiseship.xml"
# Berth to terminal, as listed on that page (checked 16 Oct 2026)
BERTH_TERMINAL = {"38/9": "QEII", "46": "Ocean", "101": "City", "102": "Horizon",
                  "106": "Mayflower"}
COLUMNS = ["ship", "terminal", "arrival", "departure", "passengers", "imo", "berth", "times",
           "collected", "capacity_source"]

# Passenger capacity by IMO number from each cruise line's own site, checked 16-17 Oct 2026:
# IMO -> (name, capacity, basis, source). The aim is two guests per cabin (lower berths). Where the
# line gives only cabins and a maximum (AIDA, MSC Preziosa) the figure is 2 x cabins; where it gives
# a single "guests" number (Cunard, some P&O pages, TUI) that number is used as published.
P_O = "https://www.pocruises.com/"
CAPACITY: dict[str, tuple[str, int, str, str]] = {
    "9826548": ("Iona", 5200, "normal operating capacity", P_O + "cruise-ships"),
    "9849693": ("Arvia", 5200, "normal operating capacity", P_O + "cruise-ships"),
    "9333175": ("Ventura", 3086, "guests (deck plan says 3,078 normal operating)",
                P_O + "find-a-cruise/N707/N707"),
    "9169524": ("Aurora", 1874, "normal operating capacity", P_O + "cruise-ships"),
    "9226906": ("Arcadia", 2094, "guests", P_O + "find-a-cruise/J605/J605"),
    "9614036": ("Britannia", 3647, "guests", P_O + "find-a-cruise/B624/B624"),
    "9241061": ("Queen Mary 2", 2759, "guests",
                "https://www.cunard.com/en-gb/cruise-ships/queen-mary-2"),
    "9320556": ("Queen Victoria", 2079, "guests",
                "https://www.cunard.com/en-gb/cruise-ships/queen-victoria"),
    "9839399": ("Queen Anne", 2956, "guests",
                "https://www.cunard.com/en-gb/cruise-ships/queen-anne"),
    "9838383": ("Celebrity Apex", 2910, "double occupancy",
                "https://www.celebritycruises.com/gb/cruise-ships/celebrity-apex"),
    "9803625": ("MSC Virtuosa", 4842, "double occupancy (max 6,334)",
                "https://www.mscpressarea.com/en_US/press-releases/2291/"),
    "9595321": ("MSC Preziosa", 3502, "2 x 1,751 cabins (max 4,345)",
                "https://www.msccruises.co.uk/ships/msc-preziosa"),
    "9636967": ("AIDAperla", 3286, "2 x 1,643 cabins (max 4,333)",
                "https://aida.de/willkommen/firmenreisen"),
    "9636955": ("AIDAprima", 3286, "2 x 1,643 cabins (max 4,333)",
                "https://aida.de/willkommen/firmenreisen"),
    "9781865": ("AIDAnova", 5252, "2 x 2,626 cabins (max 6,654)",
                "https://aida.de/willkommen/firmenreisen"),
    "9802396": ("Sky Princess", 3660, "lower berths",
                "https://www.princess.com/news/backgrounders-and-fact-sheets/sky-princess-fact-sheet"),
    "9122552": ("Borealis", 1299, "standard occupancy",
                "https://www.fredolsencruises.com/our-ships/borealis"),
    "9862657": ("Mein Schiff Relax", 3984, "Passagiere",
                "https://www.meinschiff.com/de/flotte/mein-schiff-relax"),
    "9156474": ("Regatta", 670, "double occupancy (Oceania's page, now withdrawn; ship on charter)",
                "https://www.oceaniacruises.com/ships/regatta"),
    "9195157": ("Norwegian Star", 2298, "double occupancy", "https://www.ncl.com/cruise-ship/star"),
}


def parse_time(text: str):
    """'17-Oct-26 05:45' -> (date, time); 'TBA', 'AM' and 'PM' keep the date and no time."""
    day, _, clock = text.strip().partition(" ")
    d = datetime.strptime(day, "%d-%b-%y").date()
    try:
        return d, datetime.strptime(clock, "%H:%M").time(), clock
    except ValueError:
        return d, None, clock or "TBA"


def typical(times: list[time], fallback: time) -> time:
    """Median of the exact times in the same feed, to the nearest 15 minutes."""
    if not times:
        return fallback
    m = statistics.median(t.hour * 60 + t.minute for t in times)
    m = int(round(m / 15) * 15)
    return time(m // 60, m % 60)


def collect(start: date, end: date, out: Path) -> None:
    req = urllib.request.Request(FEED, headers={"User-Agent": "Mozilla/5.0 (sotonship26)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
        modified = r.headers.get("Last-Modified", "")
    collected = datetime.now().astimezone().replace(microsecond=0)
    rows = []
    for row in ET.fromstring(body).iter("row"):
        def get(tag, row=row):
            el = row.find(tag)
            return (el.text or "").strip() if el is not None else ""

        rows.append({"ship": get("ship_name"), "imo": get("lloyds_no."), "berth": get("berth"),
                     "arr": parse_time(get("arrival")), "dep": parse_time(get("departure"))})
    arr_typ = typical([r["arr"][1] for r in rows if r["arr"][1]], time(6, 0))
    dep_typ = typical([r["dep"][1] for r in rows if r["dep"][1]], time(17, 0))
    written, missing = [], set()
    for r in rows:
        (ad, at, araw), (dd, dt, draw) = r["arr"], r["dep"]
        if not start <= ad <= end:
            continue
        terminal = BERTH_TERMINAL.get(r["berth"])
        if terminal is None:
            print(f"skipping {r['ship']} on {ad}: berth {r['berth']} is not a cruise terminal")
            continue
        exact = at is not None and dt is not None
        at = at or (time(12, 0) if araw == "PM" else arr_typ)
        dt = dt or (time(11, 0) if draw == "AM" else dep_typ)
        name, pax, basis, url = CAPACITY.get(r["imo"], (r["ship"].title(), None, "", ""))
        if pax is None:
            missing.add(r["ship"])
        written.append({
            "ship": name, "terminal": terminal,
            "arrival": datetime.combine(ad, at).isoformat(timespec="minutes"),
            "departure": datetime.combine(dd, dt).isoformat(timespec="minutes"),
            "passengers": "" if pax is None else pax, "imo": r["imo"], "berth": r["berth"],
            "times": "exact" if exact else f"typical (VTS lists {araw}/{draw})",
            "collected": collected.isoformat(),
            "capacity_source": f"{basis}, {url}, checked 16-17 Oct 2026" if url else ""})
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(written)
    n_exact = sum(r["times"] == "exact" for r in written)
    print(f"{FEED} (Last-Modified {modified}), collected {collected.isoformat()}")
    print(f"wrote {len(written)} calls {start} to {end} to {out} ({n_exact} with exact times; "
          f"typical arrival {arr_typ:%H:%M}, departure {dep_typ:%H:%M} for the rest)")
    if missing:
        print("no capacity for: " + ", ".join(sorted(missing)))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 10, 17))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 11, 29))
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    collect(args.start, args.end, args.out)


if __name__ == "__main__":
    main()
