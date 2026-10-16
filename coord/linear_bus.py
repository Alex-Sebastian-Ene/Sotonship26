"""Linear as the message bus between the team's Claude Code sessions.

Each human runs one Claude. Every Claude posts with a marker like ``[keanu-claude]`` so the
others can tell agents apart even though Linear credits the human's account. ``watch`` polls the
team's Linear activity and exits as soon as something new arrives, so a Claude can run it in the
background and get woken up (pull-based notifications, no webhooks or servers).

Stdlib only, so it runs on any laptop without ``uv sync`` (``uv run --no-project`` works too).
Settings come from the environment, or from the untracked file ``.coord/linear.env``:

    LINEAR_API_KEY=lin_api_...   # linear.app > Settings > Security & access > Personal API keys
    COORD_AGENT=keanu            # keanu | edward | seb

    python coord/linear_bus.py whoami
    python coord/linear_bus.py watch                 # blocks until new activity, prints it, exits
    python coord/linear_bus.py inbox                 # open issues for this agent + recent chatter
    python coord/linear_bus.py comment SOT-12 "text"
    python coord/linear_bus.py create "title" --body "..." --label agent:edward
    python coord/linear_bus.py setup                 # create the shared labels once
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

API_URL = "https://api.linear.app/graphql"
STATE_DIR = Path(__file__).resolve().parent.parent / ".coord"
ENV_FILE = STATE_DIR / "linear.env"
AGENTS = ("keanu", "edward", "seb")
LABELS = {
    "agent:keanu": "#4EA7FC",
    "agent:edward": "#F2994A",
    "agent:seb": "#BB87FC",
    "human-needed": "#EB5757",
    "blocked": "#95A2B3",
    "handoff": "#4CB782",
}

WATCH_QUERY = """
query Watch($team: String!, $since: DateTimeOrDuration!) {
  comments(first: 50, filter: {createdAt: {gt: $since}, issue: {team: {key: {eq: $team}}}}) {
    nodes { createdAt body user { name } issue { identifier title url } }
  }
  newIssues: issues(first: 50, filter: {team: {key: {eq: $team}}, createdAt: {gt: $since}}) {
    nodes { createdAt identifier title url description creator { name }
            assignee { name } labels { nodes { name } } }
  }
  moved: issues(first: 50, filter: {team: {key: {eq: $team}}, updatedAt: {gt: $since}}) {
    nodes { identifier title
            history(first: 10) { nodes { createdAt actor { name }
                                         fromState { name } toState { name }
                                         fromAssignee { name } toAssignee { name } } } }
  }
}
"""


class LinearError(RuntimeError):
    pass


def load_env_file(path: Path = ENV_FILE) -> None:
    """Fill unset variables from KEY=VALUE lines; real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def gql(query: str, variables: dict | None = None) -> dict:
    key = os.environ.get("LINEAR_API_KEY")
    if not key:
        raise LinearError(f"LINEAR_API_KEY is not set: export it or put it in {ENV_FILE}")
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        API_URL, data=payload, headers={"Content-Type": "application/json", "Authorization": key}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as err:
        raise LinearError(f"Linear HTTP {err.code}: {err.read()[:300]!r}") from err
    if body.get("errors"):
        raise LinearError(f"Linear GraphQL error: {body['errors'][0].get('message')}")
    return body["data"]


def marker(agent: str) -> str:
    return f"[{agent}-claude]"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def name_of(node: dict | None, default: str) -> str:
    return (node or {}).get("name", default)


def collect_events(data: dict, agent: str) -> list[dict]:
    """Turn one poll into events, dropping what this agent wrote itself."""
    mine = marker(agent)
    events = []
    for c in data["comments"]["nodes"]:
        if c["body"].lstrip().startswith(mine):
            continue
        events.append({
            "at": c["createdAt"], "kind": "comment", "issue": c["issue"]["identifier"],
            "title": c["issue"]["title"], "who": (c.get("user") or {}).get("name", "?"),
            "text": c["body"], "url": c["issue"]["url"],
        })
    for i in data["newIssues"]["nodes"]:
        if mine in (i.get("description") or ""):
            continue
        labels = ", ".join(n["name"] for n in i["labels"]["nodes"])
        events.append({
            "at": i["createdAt"], "kind": "new-issue", "issue": i["identifier"],
            "title": i["title"], "who": (i.get("creator") or {}).get("name", "?"),
            "text": f"labels: {labels or '-'} | assignee: {name_of(i.get('assignee'), '-')}"
                    f"\n{(i.get('description') or '').strip()}",
            "url": i["url"],
        })
    return events


def collect_moves(data: dict, since: str, viewer: str) -> list[dict]:
    events = []
    for i in data["moved"]["nodes"]:
        for h in i["history"]["nodes"]:
            if h["createdAt"] <= since or (h.get("actor") or {}).get("name") == viewer:
                continue
            parts = []
            if h.get("toState"):
                parts.append(f"{name_of(h.get('fromState'), '?')} -> {h['toState']['name']}")
            if h.get("toAssignee") or h.get("fromAssignee"):
                parts.append(f"assignee -> {name_of(h.get('toAssignee'), 'nobody')}")
            if parts:
                events.append({
                    "at": h["createdAt"], "kind": "moved", "issue": i["identifier"],
                    "title": i["title"], "who": (h.get("actor") or {}).get("name", "?"),
                    "text": "; ".join(parts), "url": "",
                })
    return events


def is_directed(event: dict, agent: str) -> bool:
    text = event["text"].lower()
    return f"@{agent}" in text or "@all" in text or f"agent:{agent}" in text


def format_event(event: dict, agent: str) -> str:
    flag = ">>> FOR YOU " if is_directed(event, agent) else ""
    head = f"{flag}[{event['at'][11:16]}Z] {event['kind']} {event['issue']} by {event['who']}"
    body = event["text"].strip()
    if len(body) > 1500:
        body = body[:1500] + " ...(truncated, open the issue)"
    return f"{head}: {event['title']}\n    " + body.replace("\n", "\n    ")


def since_path(agent: str) -> Path:
    return STATE_DIR / f"{agent}.since"


def load_since(agent: str) -> str:
    path = since_path(agent)
    if path.exists():
        return path.read_text().strip()
    return now_iso()


def save_since(agent: str, value: str) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    since_path(agent).write_text(value)


def cmd_watch(args: argparse.Namespace) -> int:
    viewer = gql("{ viewer { name } }")["viewer"]["name"]
    since = load_since(args.agent)
    save_since(args.agent, since)
    for _ in range(args.max_checks):
        polled_at = now_iso()
        try:
            data = gql(WATCH_QUERY, {"team": args.team, "since": since})
        except (LinearError, urllib.error.URLError, TimeoutError) as err:
            print(f"poll failed, retrying: {err}", file=sys.stderr)
            time.sleep(args.interval)
            continue
        events = collect_events(data, args.agent) + collect_moves(data, since, viewer)
        if events:
            events.sort(key=lambda e: e["at"])
            print(f"LINEAR ACTIVITY ({len(events)}) since {since}")
            for e in events:
                print(format_event(e, args.agent))
            save_since(args.agent, max(polled_at, events[-1]["at"]))
            if not args.stream:
                return 0
            since = load_since(args.agent)
        else:
            since = polled_at
            save_since(args.agent, since)
        time.sleep(args.interval)
    print(f"NO LINEAR ACTIVITY after {args.max_checks} checks; re-run watch to keep listening")
    return 0


def team_info(key: str) -> dict:
    q = """query($k: String!) { teams(filter: {key: {eq: $k}}) { nodes { id key name
           labels(first: 100) { nodes { id name } } } } }"""
    nodes = gql(q, {"k": key})["teams"]["nodes"]
    if not nodes:
        raise LinearError(f"No Linear team with key {key}; set COORD_TEAM")
    return nodes[0]


def cmd_whoami(args: argparse.Namespace) -> int:
    viewer = gql("{ viewer { name email } }")["viewer"]
    team = team_info(args.team)
    print(f"{viewer['name']} as {marker(args.agent)} on team {team['key']} ({team['name']})")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    team = team_info(args.team)
    have = {n["name"] for n in team["labels"]["nodes"]}
    q = """mutation($i: IssueLabelCreateInput!) { issueLabelCreate(input: $i) { success } }"""
    for name, color in LABELS.items():
        if name in have:
            print(f"label exists: {name}")
            continue
        gql(q, {"i": {"name": name, "color": color, "teamId": team["id"]}})
        print(f"label created: {name}")
    return 0


def cmd_comment(args: argparse.Namespace) -> int:
    issue = gql("query($id: String!) { issue(id: $id) { id identifier url } }",
                {"id": args.issue})["issue"]
    body = f"{marker(args.agent)} {args.text}"
    gql("mutation($i: CommentCreateInput!) { commentCreate(input: $i) { success } }",
        {"i": {"issueId": issue["id"], "body": body}})
    print(f"commented on {issue['identifier']} {issue['url']}")
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    team = team_info(args.team)
    by_name = {n["name"]: n["id"] for n in team["labels"]["nodes"]}
    missing = [name for name in args.label if name not in by_name]
    if missing:
        raise LinearError(f"Unknown labels {missing}; run `setup` first")
    body = f"{args.body}\n\n_filed by {marker(args.agent)}_"
    q = """mutation($i: IssueCreateInput!) { issueCreate(input: $i) {
           issue { identifier url } } }"""
    issue = gql(q, {"i": {"teamId": team["id"], "title": args.title, "description": body,
                          "labelIds": [by_name[n] for n in args.label]}})["issueCreate"]["issue"]
    print(f"created {issue['identifier']} {issue['url']}")
    return 0


def cmd_inbox(args: argparse.Namespace) -> int:
    q = """query($team: String!, $label: String!) {
      issues(first: 50, filter: {team: {key: {eq: $team}}, labels: {name: {eq: $label}},
                                  state: {type: {nin: ["completed", "canceled"]}}}) {
        nodes { identifier title state { name } assignee { name } url } } }"""
    issues = gql(q, {"team": args.team, "label": f"agent:{args.agent}"})["issues"]["nodes"]
    print(f"Open issues labelled agent:{args.agent}: {len(issues)}")
    for i in issues:
        print(f"  {i['identifier']} [{i['state']['name']}] {i['title']} {i['url']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--agent", default=os.environ.get("COORD_AGENT"), choices=AGENTS)
    p.add_argument("--team", default=os.environ.get("COORD_TEAM", "SOT"))
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("watch", help="block until new team activity, print it, exit")
    w.add_argument("--interval", type=int, default=int(os.environ.get("COORD_INTERVAL", 45)))
    w.add_argument("--max-checks", type=int, default=120)
    w.add_argument("--stream", action="store_true", help="keep printing instead of exiting")
    sub.add_parser("whoami")
    sub.add_parser("setup", help="create the shared labels on the team")
    sub.add_parser("inbox", help="open issues labelled for this agent")
    c = sub.add_parser("comment")
    c.add_argument("issue")
    c.add_argument("text")
    n = sub.add_parser("create")
    n.add_argument("title")
    n.add_argument("--body", default="")
    n.add_argument("--label", action="append", default=[])
    return p


def main(argv: list[str] | None = None) -> int:
    # Windows consoles and pipes default to cp1252, which cannot print arrows or em dashes.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_env_file()
    args = build_parser().parse_args(argv)
    if not args.agent:
        print("Set COORD_AGENT (keanu | edward | seb) or pass --agent", file=sys.stderr)
        return 2
    handlers = {"watch": cmd_watch, "whoami": cmd_whoami, "setup": cmd_setup,
                "comment": cmd_comment, "create": cmd_create, "inbox": cmd_inbox}
    try:
        return handlers[args.cmd](args)
    except LinearError as err:
        print(err, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
