"""Road network for the SUMO microsimulation (demo/sumo_demand.py, demo/sumo_compare.py).

The microsimulation is a check on the macroscopic model in traffic_model.py: individual cars with
car-following, lanes, junctions and signals on the same roads. This builds its network from
OpenStreetMap (© OpenStreetMap contributors, ODbL) for the same box (synthetic_demo.BBOX) and the
same road classes the macro model routes on (motorway to unclassified, with their slip roads),
keeping OSM's lanes, one-ways, speed limits and traffic signals. UK traffic drives on the left.

    fetch   download the roads from Overpass (needs internet: a login node on Iridis)
            -> data/cache/sumo/southampton.osm.xml + osm.source.json (OSM data timestamp)
    build   netconvert -> data/cache/sumo/southampton.net.xml.gz + net.summary.json
    no-ring-signals   the same network without the signals on roundabouts (a sensitivity test)
    --residential     any step for the network with residential streets too (files *_res*),
                      a test of whether the main-road-only network is why SUMO jams

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
NET_NO_RING_SIGNALS = OUT / "southampton_no_ring_signals.net.xml.gz"
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
# Added by --residential (not in the macro model's network). 30 mph and 10 mph are assumed.
RESIDENTIAL_TYPES = {"residential": (1, 30, 4, False), "living_street": (1, 10, 3, False)}
ALLOW = ("private emergency authority army vip passenger hov taxi bus coach delivery truck "
         "trailer motorcycle evehicle custom1 custom2")
NETCONVERT_OPTIONS = [
    "--lefthand", "true",
    # UK roads have no give-way-to-the-right rule: an unsignalled junction gives way to its major
    # road. By default netconvert makes every junction of equally ranked roads under 49 km/h
    # right-before-left (535 of 2,642 here, Calmore Road and Ringwood Road among them), where
    # every approach yields and the junction jams and deadlocks.
    "--junctions.right-before-left.speed-threshold", "0",
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


# --- files per variant ------------------------------------------------------------------------

def files(residential: bool = False) -> dict[str, Path]:
    """Paths for the main-road network or, with ``residential``, the one with side streets."""
    t = "_res" if residential else ""
    return {"osm": OUT / f"southampton{t}.osm.xml", "source": OUT / f"osm{t}.source.json",
            "net": OUT / f"southampton{t}.net.xml.gz", "summary": OUT / f"net{t}.summary.json",
            "log": OUT / f"netconvert{t}.log", "types": OUT / f"uk_roads{t}.typ.xml",
            "ring": OUT / f"southampton{t}_no_ring_signals.net.xml.gz",
            "ring_summary": OUT / f"net{t}_no_ring_signals.summary.json",
            "ring_log": OUT / f"netconvert{t}_no_ring_signals.log"}


def road_types(residential: bool = False) -> dict:
    return {**ROAD_TYPES, **(RESIDENTIAL_TYPES if residential else {})}


# --- fetch -----------------------------------------------------------------------------------

def overpass_query(residential: bool = False) -> str:
    w, s, e, n = BBOX
    kinds = "|".join(road_types(residential))
    return (f"[out:xml][timeout:900][maxsize:1073741824][bbox:{s},{w},{n},{e}];\n"
            f'way["highway"~"^({kinds})$"]->.roads;\n'
            "(.roads; .roads >;)->.all;\n"
            'rel(bw.roads)["type"="restriction"]->.restr;\n'
            "(.all; .restr;);\nout body;\n")


def fetch(residential: bool = False, log=print) -> dict:
    """Download the roads once; the response's osm_base timestamp is the OSM data date."""
    OUT.mkdir(parents=True, exist_ok=True)
    f_ = files(residential)
    osm = f_["osm"]
    query = overpass_query(residential)
    body = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for url in OVERPASS:
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
                tmp = osm.with_suffix(".part")
                with urllib.request.urlopen(req, timeout=1200) as r, open(tmp, "wb") as f:
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
                head = tmp.read_bytes()[:2000].decode("utf-8", "replace")
                if "<osm" not in head:
                    raise RuntimeError(f"not OSM XML: {head[:200]!r}")
                tmp.replace(osm)
                stamp = re.search(r'osm_base="([^"]+)"', head)
                info = {"url": url, "query": query, "osm_base": stamp.group(1) if stamp else None,
                        "fetched": datetime.now(UTC).isoformat(timespec="seconds"),
                        "bytes": osm.stat().st_size, "bbox": BBOX,
                        "licence": "© OpenStreetMap contributors, ODbL 1.0"}
                f_["source"].write_text(json.dumps(info, indent=1), encoding="utf-8")
                log(f"wrote {osm} ({info['bytes'] / 1e6:.1f} MB), "
                    f"OSM data as of {info['osm_base']}")
                return info
            except Exception as exc:  # noqa: BLE001  (busy servers: back off, then the next one)
                last = exc
                log(f"{url}: {exc}; retrying")
                time.sleep(20 * (attempt + 1))
    raise SystemExit(f"Overpass failed: {last}")


# --- build -----------------------------------------------------------------------------------

def write_types(path: Path = TYPES, residential: bool = False) -> Path:
    rows = []
    for kind, (lanes, mph, prio, oneway) in road_types(residential).items():
        rows.append(f'    <type id="highway.{kind}" priority="{prio}" numLanes="{lanes}" '
                    f'speed="{mph * MPH:.2f}" allow="{ALLOW}" oneway="{int(oneway)}"/>')
    path.write_text("<types>\n" + "\n".join(rows) + "\n</types>\n", encoding="utf-8",
                    newline="\n")
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


def build(residential: bool = False, log=print) -> dict:
    f_ = files(residential)
    if not f_["osm"].exists():
        flag = " --residential" if residential else ""
        raise SystemExit(f"{f_['osm']} missing: run `python demo/sumo_net.py fetch{flag}` "
                         "on a login node")
    types = write_types(f_["types"], residential)
    run(tool("netconvert") + ["--osm-files", str(f_["osm"]), "--type-files", str(types),
                              "-o", str(f_["net"]), "--log", str(f_["log"]),
                              *NETCONVERT_OPTIONS], log)
    info = summary(f_["net"])
    src = f_["source"]
    info["osm"] = json.loads(src.read_text(encoding="utf-8")) if src.exists() else None
    info["netconvert_options"] = NETCONVERT_OPTIONS
    info["built"] = datetime.now(UTC).isoformat(timespec="seconds")
    f_["summary"].write_text(json.dumps(info, indent=1), encoding="utf-8")
    log(f"wrote {f_['net']}: {info['edges']} edges, {info['junctions']} junctions, "
        f"{info['traffic_lights']} signals, {info['lane_km_total']} lane-km")
    return info


def roundabout_signals(net_path: Path) -> list[str]:
    """Junctions run by traffic lights that control only roundabout junctions. OSM marks some big
    interchanges (M27 junction 3 at Rownhams, for one) as signalised roundabouts; netconvert gives
    each entry its own signal with SUMO's default plan, unlinked to the others, and the ring
    jams, which the real linked signals do not do."""
    import sumolib

    net = sumolib.net.readNet(str(net_path), withInternal=False)
    ring = {n for r in net.getRoundabouts() for n in r.getNodes()}
    out = []
    for tls in net.getTrafficLights():
        nodes = {c[0].getEdge().getToNode().getID() for c in tls.getConnections()}
        if nodes and nodes <= ring:
            out += nodes
    return sorted(set(out))


def build_without_roundabout_signals(residential: bool = False, log=print) -> Path:
    """A variant network with the roundabout signals removed (give way to the ring instead),
    to see how much of SUMO's congestion comes from those unlinked default signal plans."""
    f_ = files(residential)
    if not f_["net"].exists():
        build(residential, log)
    ids = roundabout_signals(f_["net"])
    out = f_["ring"]
    run(tool("netconvert") + ["-s", str(f_["net"]), "--tls.unset", ",".join(ids), "-o",
                              str(out), "--log", str(f_["ring_log"])], log)
    log(f"wrote {out}: {len(ids)} roundabout signals removed")
    info = json.loads(f_["summary"].read_text(encoding="utf-8"))
    info["variant"] = {"roundabout_signals_removed": ids, **summary(out)}
    f_["ring_summary"].write_text(json.dumps(info, indent=1), encoding="utf-8")
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("step", choices=["fetch", "build", "no-ring-signals"])
    ap.add_argument("--residential", action="store_true",
                    help="the network with residential streets as well")
    args = ap.parse_args(argv)
    step = {"fetch": fetch, "build": build, "no-ring-signals": build_without_roundabout_signals}
    step[args.step](args.residential)


if __name__ == "__main__":
    main()
