"""Real data for traffic to, from and through the study area.

Everything is downloaded once into data/cache (gitignored) and reduced to two small files there:

* ``census/commute_flows.json``: Census 2021 commuters (ONS, Open Government Licence v3.0) who
  live in the study area and work outside it, or the other way round, at MSOA level, with the share
  driving a car or van.
  - ODWP01EW, location of usual residence and place of work (Nomis bulk download).
  - Method used to travel to work by distance travelled to work, per local authority (ONS census
    observations API). Used for the car-driver share of each flow, from its home district and its
    straight-line distance band.
  - MSOA (December 2021) population-weighted centroids V2 (ONS Open Geography Portal).
* ``dft/count_points.json``: DfT road traffic statistics (Open Government Licence v3.0), annual
  average daily flow (AADF), latest year, at the count points listed in DFT_SITES (fitted to) and at
  every count point near the edge of the area (traffic crossing each gateway).

Census day was 21 March 2021, during lockdown: about half of workers worked mainly at home, so the
flows show where commuters come from and go to better than how many there are today.

    uv run --no-project --python 3.12 --with pyproj python demo/external_data.py   # once
"""

from __future__ import annotations

import csv
import io
import json
import math
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CENSUS = ROOT / "data" / "cache" / "census"
DFT = ROOT / "data" / "cache" / "dft"
BBOX = (-1.53, 50.855, -1.29, 50.975)  # same frame as osm_base.py
MAX_KM = 60.0  # commuters living or working further than this from the area are not daily drivers
ISLAND = "Isle of Wight"

URLS = {
    CENSUS / "odwp01ew.zip": "https://www.nomisweb.co.uk/output/census/2021/odwp01ew.zip",
    CENSUS / "ons_method_by_distance_ltla.json":
        "https://api.beta.ons.gov.uk/v1/population-types/UR/census-observations"
        "?area-type=ltla&dimensions=transport_to_workplace_12a,workplace_travel_10a",
    DFT / "dft_traffic_counts_aadf.zip":
        "https://storage.googleapis.com/dft-statistics/road-traffic/downloads/data-gov-uk/"
        "dft_traffic_counts_aadf.zip",
}
MSOA_PWC = ("https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
            "MSOA_December_2021_EW_PWC_V2/FeatureServer/0/query?where=1%3D1&outFields=MSOA21CD"
            "&outSR=4326&returnGeometry=true&f=json&resultRecordCount=2000&resultOffset={}")

CENSUS_SOURCE = ("ONS Census 2021 (21 March 2021): ODWP01EW location of usual residence and place "
                 "of work (MSOA), method of travel to work by distance (local authority), MSOA "
                 "population-weighted centroids. Open Government Licence v3.0")
DFT_SOURCE = ("DfT road traffic statistics, annual average daily flow per count point "
              "(dft_traffic_counts_aadf, published June 2026). Open Government Licence v3.0")

# DfT count points the external traffic is checked against: (count point id, label, model road
# names, fitted). With no names the count point's road number is matched to OSM refs near the point.
# Itchen Bridge is tolled and the model has no tolls, so its traffic shifts to Northam Bridge in the
# model; both are reported but not fitted.
DFT_SITES = [
    (26062, "M271 (A35 Redbridge to junction 1)", None, True),
    (90217, "A33 Redbridge Road and Millbrook Flyover", None, True),
    (36375, "A35 Redbridge Causeway", None, True),
    (56347, "A33 Millbrook Road West", None, True),
    (57434, "A33 The Avenue", None, True),
    (37658, "A3025 Itchen Bridge", ["Itchen Bridge"], False),
    (46963, "A3024 Northam Bridge", ["Northam Bridge"], False),
    (18312, "A335 Thomas Lewis Way", None, True),
    (17793, "M27 junction 3 to 4", None, True),
    (48091, "M27 junction 4 to 5", None, True),
    (38083, "M27 junction 7 to 8", None, True),
    (16321, "M3 junction 13 to 14", None, True),
]

CORDON_M = 6000  # count points this close to the study area are candidates for gateway counts
CORDON_SINCE = 2015  # ignore count points not counted or estimated since
BANDS_KM = [2, 5, 10, 20, 30, 40, 60]  # census distance travelled to work, bands 1-8
# Southampton Water and the Solent east of Calshot (lat, lon): no road crosses it, so a commuter's
# straight-line approach to a gateway may not either.
WATER_BARRIER = [(50.74, -1.20), (50.818, -1.307), (50.875, -1.37), (50.895, -1.395)]


def frame_origin():
    """British National Grid origin of the page grid (x = easting - x0, y = y1 - northing)."""
    from pyproj import Transformer

    t = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
    w, s, e, n = BBOX
    xs, ys = zip(*[t.transform(x, y) for x, y in [(w, s), (e, s), (e, n), (w, n)]], strict=True)
    return min(xs), max(ys), max(xs) - min(xs), max(ys) - min(ys), t


def water_barrier() -> list[tuple[int, int]]:
    """WATER_BARRIER on the page grid."""
    x0, y1, *_, t = frame_origin()
    out = []
    for lat, lon in WATER_BARRIER:
        e, n = t.transform(lon, lat)
        out.append((round(e - x0), round(y1 - n)))
    return out


def download(url: str, path: Path, log=print) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    log(f"downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "sotonship26-demo"})
    with urllib.request.urlopen(req, timeout=300) as r, open(path, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)


def fetch(log=print) -> None:
    for path, url in URLS.items():
        if not path.exists():
            download(url, path, log)
    for off in range(0, 8000, 2000):
        path = CENSUS / f"msoa_pwc_{off}.json"
        if not path.exists():
            download(MSOA_PWC.format(off), path, log)


def band(km: float) -> int:
    """Census distance band (1-8) of a straight-line distance."""
    for i, edge in enumerate(BANDS_KM):
        if km < edge:
            return i + 1
    return 8


def car_driver_share() -> dict[tuple[str, int], float]:
    """(local authority name, distance band) -> share of commuters driving a car or van."""
    obs = json.loads((CENSUS / "ons_method_by_distance_ltla.json").read_text(encoding="utf-8"))
    tot: dict[tuple[str, int], float] = {}
    drv: dict[tuple[str, int], float] = {}
    for o in obs["observations"]:
        la, method, dist = (d["option"] for d in o["dimensions"])
        b = int(o["dimensions"][2]["option_id"])
        if not 1 <= b <= 8:
            continue
        tot[(la, b)] = tot.get((la, b), 0.0) + o["observation"]
        if method.startswith("Driving a car or van"):
            drv[(la, b)] = drv.get((la, b), 0.0) + o["observation"]
    return {k: drv.get(k, 0.0) / v for k, v in tot.items() if v > 0}


def commute_flows(log=print) -> dict:
    """Census commuters crossing the edge of the study area, one row per MSOA pair."""
    out = CENSUS / "commute_flows.json"
    if out.exists():
        return json.loads(out.read_text(encoding="utf-8"))
    fetch(log)
    x0, y1, W, H, t = frame_origin()
    xy = {}
    for off in range(0, 8000, 2000):
        for f in json.loads((CENSUS / f"msoa_pwc_{off}.json").read_text())["features"]:
            e, n = t.transform(f["geometry"]["x"], f["geometry"]["y"])
            xy[f["attributes"]["MSOA21CD"]] = (round(e - x0), round(y1 - n))

    def inside(p) -> bool:
        return 0 <= p[0] <= W and 0 <= p[1] <= H

    def from_area_km(p) -> float:
        dx = max(0 - p[0], 0, p[0] - W)
        dy = max(0 - p[1], 0, p[1] - H)
        return math.hypot(dx, dy) / 1000

    share = car_driver_share()
    rows, missing, island = [], set(), 0
    with zipfile.ZipFile(CENSUS / "odwp01ew.zip") as z:
        f = io.TextIOWrapper(z.open("ODWP01EW_MSOA.csv"), encoding="utf-8-sig")
        r = csv.reader(f)
        next(r)
        for home, home_nm, work, work_nm, kind, _, count in r:
            if kind != "3" or home == work:  # 3: working in the UK, not mainly at or from home
                continue
            ph, pw = xy.get(home), xy.get(work)
            if ph is None or pw is None:
                continue
            ih, iw = inside(ph), inside(pw)
            if ih == iw or from_area_km(pw if ih else ph) > MAX_KM:
                continue
            la = home_nm.rsplit(" ", 1)[0]
            if ISLAND in (la, work_nm.rsplit(" ", 1)[0]):
                island += int(count)
                continue
            km = math.dist(ph, pw) / 1000
            car = share.get((la, band(km)))
            if car is None:
                missing.add(la)
                continue
            rows.append({"home": home, "work": work, "home_la": la,
                         "work_la": work_nm.rsplit(" ", 1)[0], "hx": ph[0], "hy": ph[1],
                         "wx": pw[0], "wy": pw[1], "n": int(count), "car": round(car, 4),
                         "inbound": iw})
    if missing:
        log(f"census: no car-driver share for {sorted(missing)}; their flows are left out")
    log(f"census: {island} Isle of Wight commuters left out "
        "(ferry to Town Quay, not a road gateway)")
    data = {"source": CENSUS_SOURCE, "collected": collected(CENSUS / "odwp01ew.zip"),
            "max_km": MAX_KM, "rows": rows}
    out.write_text(json.dumps(data), encoding="utf-8")
    log(f"census: {len(rows)} MSOA flows cross the edge of the study area -> {out}")
    return data


def msoa_totals(log=print) -> dict:
    """Census 2021 residents aged 16 and over and workplace counts for every MSOA whose
    population-weighted centroid lies in the study area (ODWP01EW): where trips start and end.

    Residents are every ODWP01EW row of the home MSOA (in work or not); jobs are people who travel
    to a workplace in the MSOA (indicator 3, not working mainly at or from home)."""
    out = CENSUS / "msoa_totals.json"
    if out.exists():
        return json.loads(out.read_text(encoding="utf-8"))
    fetch(log)
    x0, y1, W, H, t = frame_origin()
    xy = {}
    for off in range(0, 8000, 2000):
        for f in json.loads((CENSUS / f"msoa_pwc_{off}.json").read_text())["features"]:
            e, n = t.transform(f["geometry"]["x"], f["geometry"]["y"])
            xy[f["attributes"]["MSOA21CD"]] = (round(e - x0), round(y1 - n))
    inside = {c for c, (x, y) in xy.items() if 0 <= x <= W and 0 <= y <= H}
    residents: dict[str, int] = {}
    jobs: dict[str, int] = {}
    with zipfile.ZipFile(CENSUS / "odwp01ew.zip") as z:
        f = io.TextIOWrapper(z.open("ODWP01EW_MSOA.csv"), encoding="utf-8-sig")
        r = csv.reader(f)
        next(r)
        for home, _, work, _, kind, _, count in r:
            if home in inside:
                residents[home] = residents.get(home, 0) + int(count)
            if kind == "3" and work in inside:
                jobs[work] = jobs.get(work, 0) + int(count)
    rows = [{"msoa": c, "x": xy[c][0], "y": xy[c][1], "residents": residents.get(c, 0),
             "jobs": jobs.get(c, 0)} for c in sorted(inside)]
    data = {"source": CENSUS_SOURCE, "collected": collected(CENSUS / "odwp01ew.zip"),
            "rows": rows}
    out.write_text(json.dumps(data), encoding="utf-8")
    log(f"census: {len(rows)} MSOAs in the study area, {sum(residents.values())} residents aged "
        f"16+, {sum(jobs.values())} workplace jobs -> {out}")
    return data


def collected(path: Path) -> str:
    return date.fromtimestamp(path.stat().st_mtime).isoformat()


def count_points(log=print) -> dict:
    """Latest AADF at each DFT_SITES count point ("sites") and at every count point within
    CORDON_M of the study area since CORDON_SINCE ("cordon"), on the page grid."""
    out = DFT / "count_points.json"
    if out.exists():
        return json.loads(out.read_text(encoding="utf-8"))
    fetch(log)
    x0, y1, W, H, _ = frame_origin()
    want = {cp for cp, *_ in DFT_SITES}
    latest: dict[int, dict] = {}
    raw = DFT / "dft_traffic_counts_aadf.zip"
    with zipfile.ZipFile(raw) as z:
        f = io.TextIOWrapper(z.open("dft_traffic_counts_aadf.csv"), encoding="utf-8-sig")
        for row in csv.DictReader(f):
            cp, year = int(row["count_point_id"]), int(row["year"])
            x, y = float(row["easting"]) - x0, y1 - float(row["northing"])
            near = -CORDON_M < x < W + CORDON_M and -CORDON_M < y < H + CORDON_M
            if (cp in want or (near and year >= CORDON_SINCE)) and (
                    cp not in latest or year > latest[cp]["year"]):
                latest[cp] = {
                    "count_point": cp, "road": row["road_name"],
                    "link": f"{row['start_junction_road_name']} to {row['end_junction_road_name']}",
                    "year": year, "method": row["estimation_method"],
                    "aadf": int(row["all_motor_vehicles"]), "hgv": int(row["all_HGVs"]),
                    "x": round(x), "y": round(y),
                }
    sites = [{**latest[cp], "label": label, "names": names, "fit": fit}
             for cp, label, names, fit in DFT_SITES if cp in latest]
    lost = [cp for cp, *_ in DFT_SITES if cp not in latest]
    if lost:
        log(f"DfT: count points not found: {lost}")
    cordon = list(latest.values())
    data = {"source": DFT_SOURCE, "collected": collected(raw), "sites": sites, "cordon": cordon}
    out.write_text(json.dumps(data, indent=1), encoding="utf-8")
    log(f"DfT: {len(sites)} count points to fit, {len(cordon)} around the area -> {out}")
    return data


if __name__ == "__main__":
    flows = commute_flows()
    n_in = sum(r["n"] * r["car"] for r in flows["rows"] if r["inbound"])
    n_out = sum(r["n"] * r["car"] for r in flows["rows"] if not r["inbound"])
    print(f"car-driver commuters into the area {n_in:.0f}, out of it {n_out:.0f}")
    for s in count_points()["sites"]:
        print(f"{s['count_point']:6d} {s['label']:42s} {s['year']} {s['method']:9s} "
              f"AADF {s['aadf']:7d}")
