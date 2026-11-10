"""Static HTML view of the lane log: management sections, items, report, capacity, triage.

``render`` is pure and self-contained (no external assets); every value taken
from governance, the releases and the log is HTML-escaped.  Governance and
backlog inputs are optional: ``None`` makes the matching section say it is
unavailable, so the page still renders on a checkout without them.
Shadow-agreement tables appear only when the report carries those optional keys.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path

from .backlog import backlog_rows
from .capacity import AllocationPolicy, format_ts, project
from .config import load_releases, load_repos
from .contracts import ITEM_STATES, ContractError
from .events import EventLog, project_items
from .lanes import CAPS, rows as lane_rows
from .report import build_report

_STYLE = (
    "body { font-family: system-ui, sans-serif; margin: 2rem; color: #1b1b1b; }"
    "h2 { margin-top: 2rem; border-bottom: 1px solid #ccc; } h3 { margin-top: 1.2rem; }"
    "table { border-collapse: collapse; margin: .5rem 0; }"
    "th, td { border: 1px solid #ccc; padding: .25rem .5rem; text-align: left; }"
    "th { background: #f0f0f0; } .muted { color: #666; }"
)


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _num(value: object) -> str:
    return "-" if value is None else (f"{value:.3f}" if isinstance(value, float) else str(value))


def _table(headers: tuple[str, ...], rows: list[list], empty: str = "none") -> str:
    if not rows:
        return f'<p class="muted">{_esc(empty)}</p>'
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in row) + "</tr>"
                   for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _counts(events: list[dict]) -> dict[str, int]:
    counts = {state: 0 for state in ITEM_STATES}
    for view in project_items(events).values():
        counts[view.state] = counts.get(view.state, 0) + 1
    return counts


def _groups(groups: dict) -> list[list]:
    return [[name, g["attempts"], g["gate_accepted"], g["ruled"], g["landed_clean"],
             _num(g["precision"]), _num(g["model_precision"]),
             "below" if g["below_bar"] else "ok", f"{g['mean_elapsed_s']:.1f}",
             ",".join(f"{k}={v}" for k, v in sorted(g["usage"].items())) or "-"]
            for name, g in sorted(groups.items())]


def _triage(events: list[dict]) -> list[dict]:
    out: dict[str, dict] = {}
    for ev in events:
        if ev.get("type") != "triage.proposed" or not (fp := ev["data"].get("fingerprint")):
            continue
        d, ts = ev["data"], ev.get("ts")
        p = out.setdefault(fp, {"fingerprint": fp, "source": d.get("source", ""),
                                "summary": d.get("summary", ""), "count": 0,
                                "first_ts": ts, "last_ts": ts})
        p["count"] += 1
        p["last_ts"] = ts or p["last_ts"]
    return [out[fp] for fp in sorted(out)]


def _shadow_html(report: dict) -> str:
    out = []
    if s := report.get("shadow_admission"):
        out.append("<h3>Shadow admission</h3>" + _table(
            ("RECORDED", "AGREED", "AGREEMENT"),
            [[s.get("recorded"), s.get("agreed"), _num(s.get("agreement"))]]))
    if e := report.get("evaluator"):
        out.append("<h3>Evaluator</h3>" + _table(
            ("CLASS", "RULED", "AGREED", "AGREEMENT"),
            [[c, g.get("evaluated_ruled"), g.get("agreed"), _num(g.get("agreement"))]
             for c, g in sorted(e.items())]))
    if l := report.get("landing_shadow"):
        out.append("<h3>Shadow landing</h3>" + _table(
            ("TRAINS", "MATCHED", "AGREEMENT"),
            [[l.get("trains"), l.get("matched"), _num(l.get("agreement"))]]))
    return "".join(out)


def _capacity_html(events: list[dict], now: datetime) -> str:
    policy = AllocationPolicy.load()
    if policy is None:
        return '<p class="muted">no allocation policy (governance/allocation.toml)</p>'
    rows = [[provider, name, w["window_start"], w["window_end"], w["used"],
             w["remaining"], w["reserved_effective"], w["burnable"],
             "allowed" if w["burn_down_allowed"] else "held"]
            for provider, windows in project(events, policy, now).items()
            for name, w in windows.items()]
    return (f'<p class="muted">allocation revision {_esc(policy.revision)}</p>'
            + _table(("PROVIDER", "WINDOW", "START", "END", "USED", "REMAINING",
                      "RESERVED", "BURNABLE", "BURN-DOWN"), rows))


def _unavailable(what: str) -> str:
    return f'<p class="muted">unavailable (no {_esc(what)} input)</p>'


def _backlog_html(releases, events: list[dict]) -> str:
    if releases is None:
        return _unavailable("releases")
    rows = backlog_rows(releases, events)
    open_rows = [r for r in rows if r["state"] != "landed"]
    table = _table(
        ("STATE", "ID", "REPO", "REV", "TRIES", "TITLE"),
        [[r["state"], r["id"], r["repo"], r["revision"], r["tries"], r["title"]]
         for r in open_rows],
        empty="no open releases")
    return table + f'<p class="muted">{len(rows) - len(open_rows)} landed</p>'


def _attention_html(releases, events: list[dict]) -> str:
    if releases is None:
        return _unavailable("releases")
    rows: list[list] = []
    for item_id, item in project_items(events).items():
        if item.state == "parked":
            rows.append(["parked", item_id, item.last_reason])
        elif item.state == "candidate":
            rows.append(["candidate", item_id, "awaiting a train"])
    for rel in releases:
        if rel.draft:
            rows.append(["draft", rel.id, rel.title])
    rows.sort(key=lambda row: (row[1], row[0]))
    return _table(("KIND", "ID", "DETAIL"), rows, empty="nothing needs attention")


def _weight(value: float) -> str:
    return f"{value:g}"


def _lanes_html(lanes) -> str:
    if lanes is None:
        return _unavailable("lanes")
    rows = []
    for lane in lanes:
        routing = " ".join(f"{model}={_weight(weight)}"
                           for model, weight in sorted(lane["routing"].items())) or "-"
        rows.append([lane["lane"], lane["revision"], routing,
                     *[f"{lane['caps'][cap]['used']}/{lane['caps'][cap]['limit']}"
                       for cap in CAPS]])
    headers = ("LANE", "REVISION", "ROUTING") + tuple(cap.upper() for cap in CAPS)
    return _table(headers, rows, empty="no lanes")


def _governance_html(repos) -> str:
    if repos is None:
        return _unavailable("repos")
    rows = [[spec.name, spec.path, spec.main, len(spec.protected_paths),
             spec.data_class_floor] for _, spec in sorted(repos.items())]
    return _table(("NAME", "PATH", "MAIN", "PROTECTED", "DATA_CLASS_FLOOR"), rows,
                  empty="no repos")


#: Section ids in page order, with their nav labels.
SECTIONS = (
    ("backlog", "Backlog"), ("attention", "Attention"), ("lanes", "Lanes"),
    ("governance", "Governance"), ("items", "Items by state"), ("report", "Report"),
    ("capacity", "Capacity"), ("triage", "Triage"),
)


def _nav() -> str:
    links = " ".join(f'<a href="#{sid}">{_esc(label)}</a>' for sid, label in SECTIONS)
    return f"<nav>{links}</nav>"


def render(events: list[dict], now: datetime, *, releases=None, lanes=None,
           repos=None) -> str:
    """Render the complete HTML document for *events* as of *now* (pure).

    ``releases`` (``WorkRelease`` rows), ``lanes`` (``lanes.rows``) and
    ``repos`` (``config.load_repos``) are loaded by the command; when one is
    ``None`` its section says it is unavailable.
    """
    now = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    report = build_report(events)
    headers = ("ATT", "GATE", "RULED", "CLEAN", "PREC", "MPREC", "FLAG", "MEAN_S", "USAGE")
    report_html = (
        "<h3>By task class</h3>" + _table(("CLASS",) + headers, _groups(report["by_class"]))
        + "<h3>By model</h3>" + _table(("MODEL",) + headers, _groups(report["by_model"]))
        + _shadow_html(report))
    triage = _table(
        ("FINGERPRINT", "SOURCE", "SUMMARY", "COUNT", "FIRST", "LAST"),
        [[p["fingerprint"], p["source"], p["summary"], p["count"],
          p["first_ts"], p["last_ts"]] for p in _triage(events)],
        empty="no open triage proposals")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>lanectl view</title>
<style>{_STYLE}</style>
</head>
<body>
<h1>lanectl</h1>
<p class="muted">as of {_esc(format_ts(now))}</p>
{_nav()}
<section id="backlog"><h2>Backlog</h2>{_backlog_html(releases, events)}</section>
<section id="attention"><h2>Needs attention</h2>{_attention_html(releases, events)}</section>
<section id="lanes"><h2>Lanes</h2>{_lanes_html(lanes)}</section>
<section id="governance"><h2>Governance</h2>{_governance_html(repos)}</section>
<section id="items"><h2>Items by state</h2>{_table(("STATE", "ITEMS"), [[s, n] for s, n in _counts(events).items()])}</section>
<section id="report"><h2>Report</h2>{report_html}</section>
<section id="capacity"><h2>Capacity</h2>{_capacity_html(events, now)}</section>
<section id="triage"><h2>Triage</h2>{triage}</section>
</body>
</html>
"""


def register(sub) -> dict:
    p = sub.add_parser("view", help="render a static HTML view of the lane log")
    p.add_argument("--html", metavar="PATH", help="write the page to PATH (otherwise stdout)")
    return {"view": _cmd}


def _try(load, *args, **kwargs):
    """Load governance/backlog input, returning ``None`` when it is unreadable."""
    try:
        return load(*args, **kwargs)
    except (OSError, ContractError):
        return None


def _cmd(args, log: EventLog) -> int:
    events = log.read()
    now = datetime.now(timezone.utc)
    page = render(events, now,
                  releases=_try(load_releases),
                  lanes=_try(lane_rows, events, today=now.strftime("%Y-%m-%d")),
                  repos=_try(load_repos))
    if not args.html:
        print(page)
        return 0
    path = Path(args.html)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page)
    print(path)
    return 0
