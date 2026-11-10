"""Per-lane routing, limits and live cap usage.

Lane policy lives in ``governance/lanes/<lane>.toml``; how much of each cap is
in use lives only in the append-only log. This view joins the two: it loads
every lane with ``config.load_lane`` and folds the log with
``events.project_items`` to count claims, attempts and accepted-but-unlanded
work per lane.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import home, load_lane
from .events import EventLog, project_items

#: Cap names, in the order they are rendered.
CAPS = ("concurrency", "items_per_day", "accepted_unlanded_max")
#: Item states that occupy the accepted-but-unlanded cap.
UNLANDED = ("candidate", "in-train")


def lane_paths(root: Path | None = None) -> list[Path]:
    """Every ``governance/lanes/<name>.toml`` under the checkout, sorted by name."""
    return sorted((root or home()).glob("governance/lanes/*.toml"))


def usage(events: list[dict], lane: str, today: str) -> dict[str, int]:
    """Live usage of each lane cap, folded from the log (pure).

    ``concurrency`` counts claimed items whose open attempt is on this lane;
    ``items_per_day`` counts this lane's ``item.claimed`` rows dated ``today``
    (UTC ``YYYY-MM-DD``); ``accepted_unlanded_max`` counts candidate/in-train
    items whose last attempt was on this lane.
    """
    items = project_items(events)
    claimed = sum(1 for v in items.values()
                  if v.open_attempt is not None and v.open_attempt.get("lane") == lane)
    per_day = sum(1 for ev in events
                  if ev["type"] == "item.claimed"
                  and ev["data"].get("lane") == lane
                  and str(ev["ts"])[:10] == today)
    unlanded = sum(1 for v in items.values()
                   if v.state in UNLANDED and v.attempts
                   and v.attempts[-1].get("lane") == lane)
    return {"concurrency": claimed, "items_per_day": per_day,
            "accepted_unlanded_max": unlanded}


def rows(events: list[dict], root: Path | None = None,
         today: str | None = None) -> list[dict]:
    """One row per governed lane: policy limits joined with live usage."""
    day = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = []
    for path in lane_paths(root):
        lane = load_lane(path.stem, root=root)
        used = usage(events, lane.lane, day)
        out.append({
            "lane": lane.lane,
            "revision": lane.revision,
            "size_max": lane.size_max,
            "max_attempts": lane.max_attempts,
            "timeout_s": lane.timeout_s,
            "routing": dict(lane.routing),
            "caps": {cap: {"used": used.get(cap, 0), "limit": lane.caps.get(cap, 0)}
                     for cap in CAPS},
        })
    return out


def _weight(value: float) -> str:
    return f"{value:g}" if value != int(value) else f"{value:.1f}"


def render(row: dict) -> list[str]:
    """The three display lines for one lane."""
    routing = " ".join(f"{model}={_weight(weight)}"
                       for model, weight in sorted(row["routing"].items()))
    caps = "  ".join(f"{cap} {row['caps'][cap]['used']}/{row['caps'][cap]['limit']}"
                     for cap in CAPS)
    return [
        f"{row['lane']}  r{row['revision']}  size_max={row['size_max']}  "
        f"max_attempts={row['max_attempts']}  timeout_s={row['timeout_s']}",
        f"  routing: {routing}",
        f"  caps: {caps}",
    ]


def register(sub) -> dict:
    p = sub.add_parser("lanes", help="per-lane routing, limits and live cap usage")
    p.add_argument("--json", action="store_true", help="emit the lane rows as JSON")
    return {"lanes": _cmd}


def _cmd(args, log: EventLog) -> int:
    views = rows(log.read())
    if args.json:
        print(json.dumps(views, indent=1, sort_keys=True))
        return 0
    if not views:
        print("no lanes (governance/lanes/*.toml); nothing to show")
        return 0
    for row in views:
        for line in render(row):
            print(line)
    return 0
