"""Road network for the SUMO microsimulation (demo/sumo_demand.py, demo/sumo_compare.py).

The microsimulation is a check on the macroscopic model in traffic_model.py: individual cars with
car-following, lanes, junctions and signals on the same roads. This builds its network from
OpenStreetMap (© OpenStreetMap contributors, ODbL) for the same box (synthetic_demo.BBOX) and the
same road classes the macro model routes on (motorway to unclassified, with their slip roads),
keeping OSM's lanes, one-ways, speed limits and traffic signals. UK traffic drives on the left.

    fetch   download the roads from Overpass (needs internet: a login node on Iridis)
            -> data/cache/sumo/southampton.osm.xml + osm.source.json (OSM data timestamp)
    build   netconvert -> data/cache/sumo/southampton.net.xml.gz + net.summary.json

SUMO's tools run from the official container on Iridis (the eclipse-sumo wheels crash on its
RHEL 8 nodes): set SUMO_CONTAINER to an Apptainer image or sandbox, or SUMO_HOME, or have them
on PATH. See cluster/iridis/sumo.slurm.

    python demo/sumo_net.py fetch
    SUMO_CONTAINER=/scratch/$USER/sumo-sif/sumo_sandbox python demo/sumo_net.py build
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "cache" / "sumo"
OSM = OUT / "southampton.osm.xml"
NET = OUT / "southampton.net.xml.gz"
TYPES = OUT / "uk_roads.typ.xml"
BBOX = (-1.53, 50.855, -1.29, 50.975)  # synthetic_demo.BBOX: west, south, east, north
UA = "sotonship26-sumo/0.1 (SotonShip 2026 hackathon, non-commercial research)"
# overpass-api.de first; the mail.ru mirror answers when it is full (and from the venue's IP)
OVERPASS = [u for u in (os.environ.get("OVERPASS_URL"),
                        "https://overpass-api.de/api/interpreter",
                        "https://maps.mail.ru/osm/tools/overpass/api/interpreter") if u]
MPH = 0.44704
# OSM highway type -> (lanes per direction, speed limit in mph, SUMO priority, one-way) used where
# OSM gives no lanes or maxspeed. Lanes follow osm_base.MAJOR (2 on motorways, 1 elsewhere);
# limits are the usual UK ones for the class in a city (assumed). Priorities as SUMO's own typemap.
ROAD_TYPES = {
    "motorway": (2, 70, 14, True), "motorway_link": (1, 40, 9, True),
    "trunk": (1, 50, 13, False), "trunk_link": (1, 40, 8, False),
    "primary": (1, 30, 12, False), "primary_link": (1, 30, 7, False),
    "secondary": (1, 30, 11, False), "secondary_link": (1, 30, 6, False),
    "tertiary": (1, 30, 10, False), "tertiary_link": (1, 30, 5, False),
    "unclassified": (1, 30, 5, False),
}
ALLOW = ("private emergency authority army vip passenger hov taxi bus coach delivery truck "
         "trailer motorcycle evehicle custom1 custom2")
NETCONVERT_OPTIONS = [
    "--lefthand", "true",
    "--geometry.remove", "true",
    "--roundabouts.guess", "true",
    "--ramps.guess", "true",
    "--junctions.join", "true",
    "--junctions.corner-detail", "5",
    "--junctions.limit-turn-speed", "5.5",
    "--tls.guess-signals", "true",
    "--tls.discard-simple", "true",
    "--tls.join", "true",
    "--tls.default-type", "actuated",
    "--remove-edges.isolated", "true",
    "--keep-edges.components", "1",
    "--output.street-names", "true",
    "--output.original-names", "true",
    "--osm.sidewalks", "false",
    "--osm.bike-access", "false",
]


def tool(name: str) -> list[str]:
    """Command prefix for a SUMO binary: the Apptainer image in SUMO_CONTAINER, else SUMO_HOME,
    else PATH."""
    box = os.environ.get("SUMO_CONTAINER")
    if box:
        binds = [p for p in ("/scratch", "/iridisfs", str(ROOT)) if Path(p).exists()]
        return ["apptainer", "exec", "-B", ",".join(binds), box, name]
    home = os.environ.get("SUMO_HOME")
    if home and (Path(home) / "bin" / name).exists():
        return [str(Path(home) / "bin" / name)]
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"{name} not found: set SUMO_CONTAINER or SUMO_HOME")
    return [found]


def run(cmd: list[str], log=print) -> None:
    log("$ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


# --- fetch -----------------------------------------------------------------------------------

def overpass_query() -> str:
    w, s, e, n = BBOX
    kinds = "|".join(ROAD_TYPES)
    return (f"[out:xml][timeout:900][maxsize:1073741824][bbox:{s},{w},{n},{e}];\n"
            f'way["highway"~"^({kinds})$"]->.roads;\n'
            "(.roads; .roads >;)->.all;\n"
            'rel(bw.roads)["type"="restriction"]->.restr;\n'
            "(.all; .restr;);\nout body;\n")


def fetch(log=print) -> dict:
    """Download the roads once; the response's osm_base timestamp is the OSM data date."""
    OUT.mkdir(parents=True, exist_ok=True)
    query = overpass_query()
    body = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for url in OVERPASS:
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
                tmp = OSM.with_suffix(".part")
                with urllib.request.urlopen(req, timeout=1200) as r, open(tmp, "wb") as f:
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
                head = tmp.read_bytes()[:2000].decode("utf-8", "replace")
                if "<osm" not in head:
                    raise RuntimeError(f"not OSM XML: {head[:200]!r}")
                tmp.replace(OSM)
                stamp = re.search(r'osm_base="([^"]+)"', head)
                info = {"url": url, "query": query, "osm_base": stamp.group(1) if stamp else None,
                        "fetched": datetime.now(UTC).isoformat(timespec="seconds"),
                        "bytes": OSM.stat().st_size, "bbox": BBOX,
                        "licence": "© OpenStreetMap contributors, ODbL 1.0"}
                (OUT / "osm.source.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
                log(f"wrote {OSM} ({info['bytes'] / 1e6:.1f} MB), "
                    f"OSM data as of {info['osm_base']}")
                return info
            except Exception as exc:  # noqa: BLE001  (busy servers: back off, then the next one)
                last = exc
                log(f"{url}: {exc}; retrying")
                time.sleep(20 * (attempt + 1))
    raise SystemExit(f"Overpass failed: {last}")


# --- build -----------------------------------------------------------------------------------

def write_types(path: Path = TYPES) -> Path:
    rows = []
    for kind, (lanes, mph, prio, oneway) in ROAD_TYPES.items():
        rows.append(f'    <type id="highway.{kind}" priority="{prio}" numLanes="{lanes}" '
                    f'speed="{mph * MPH:.2f}" allow="{ALLOW}" oneway="{int(oneway)}"/>')
    path.write_text("<types>\n" + "\n".join(rows) + "\n</types>\n", encoding="utf-8", newline="\n")
    return path


def summary(net_path: Path) -> dict:
    import sumolib

    net = sumolib.net.readNet(str(net_path), withInternal=False)
    edges = [e for e in net.getEdges() if e.getFunction() != "internal"]
    by_type: dict[str, float] = {}
    for e in edges:
        km = e.getLength() * e.getLaneNumber() / 1000
        by_type[e.getType()] = by_type.get(e.getType(), 0.0) + km
    return {"edges": len(edges), "junctions": len(net.getNodes()),
            "traffic_lights": len(net.getTrafficLights()),
            "lane_km": {k: round(v, 1) for k, v in sorted(by_type.items())},
            "lane_km_total": round(sum(by_type.values()), 1)}


def build(log=print) -> dict:
    if not OSM.exists():
        raise SystemExit(f"{OSM} missing: run `python demo/sumo_net.py fetch` on a login node")
    types = write_types()
    run(tool("netconvert") + ["--osm-files", str(OSM), "--type-files", str(types),
                              "-o", str(NET), "--log", str(OUT / "netconvert.log"),
                              *NETCONVERT_OPTIONS], log)
    info = summary(NET)
    src = OUT / "osm.source.json"
    info["osm"] = json.loads(src.read_text(encoding="utf-8")) if src.exists() else None
    info["netconvert_options"] = NETCONVERT_OPTIONS
    info["built"] = datetime.now(UTC).isoformat(timespec="seconds")
    (OUT / "net.summary.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    log(f"wrote {NET}: {info['edges']} edges, {info['junctions']} junctions, "
        f"{info['traffic_lights']} signals, {info['lane_km_total']} lane-km")
    return info


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("step", choices=["fetch", "build"])
    args = ap.parse_args(argv)
    fetch() if args.step == "fetch" else build()


if __name__ == "__main__":
    main()
