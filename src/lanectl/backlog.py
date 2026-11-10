"""Backlog DX: list and inspect WorkReleases with their state from the log.

``backlog_rows`` is a pure join of ``release.toml`` fields with the item
projection, so the operator no longer needs ``status``, ``events --item`` and
the release file side by side to see what is open.
"""
from __future__ import annotations

import json
import sys

from .config import load_releases
from .events import EventLog, project_items


def backlog_rows(releases, events: list[dict]) -> list[dict]:
    """Return one row per WorkRelease, sorted by id (pure).

    ``published`` is the highest ``release.published`` revision in the log
    (0 when never published), while ``revision`` is the release.toml revision.
    """
    items = project_items(events)
    published: dict[str, int] = {}
    for ev in events:
        if ev.get("type") != "release.published":
            continue
        data = ev.get("data") or {}
        revision = int(data.get("revision", 0))
        for key in (ev.get("item_id"), data.get("release_id")):
            if key:
                published[key] = max(published.get(key, 0), revision)
    rows = []
    for rel in sorted(releases, key=lambda r: r.id):
        view = items.get(rel.id)
        rows.append({
            "id": rel.id,
            "repo": rel.repo,
            "title": rel.title,
            "task_class": rel.task_class,
            "size": rel.size,
            "revision": rel.revision,
            "published": published.get(rel.id, 0),
            "state": view.state if view else "new",
            "tries": len(view.attempts) if view else 0,
            "last_reason": view.last_reason if view else "",
        })
    return rows


def _filtered(rows: list[dict], states: list[str], repo: str | None,
              open_only: bool) -> list[dict]:
    out = rows
    if states:
        wanted = set(states)
        out = [r for r in out if r["state"] in wanted]
    if repo:
        out = [r for r in out if r["repo"] == repo]
    if open_only:
        out = [r for r in out if r["state"] != "landed"]
    return out


def _print_table(rows: list[dict]) -> None:
    headers = ("STATE", "ID", "REPO", "REV", "TRIES", "TITLE")
    cells = [[r["state"], r["id"], r["repo"], str(r["revision"]), str(r["tries"]),
              r["title"]] for r in rows]
    widths = [len(h) for h in headers]
    for row in cells:
        widths = [max(w, len(c)) for w, c in zip(widths, row)]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)).rstrip())
    for row in cells:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip())
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    summary = " ".join(f"{state}={counts[state]}" for state in sorted(counts))
    print(f"{len(rows)} releases" + (f": {summary}" if summary else ""))


def _attempt_reasons(events: list[dict]) -> dict[str, list[str]]:
    reasons: dict[str, list[str]] = {}
    for ev in events:
        if ev.get("type") == "decision.recorded":
            data = ev["data"]
            reasons[data["attempt_id"]] = list(data.get("reasons") or ())
    return reasons


def _show(release_id: str, log: EventLog) -> int:
    rel = next((r for r in load_releases() if r.id == release_id), None)
    if rel is None:
        print(f"unknown release {release_id}", file=sys.stderr)
        return 2
    events = log.read()
    view = project_items(events).get(rel.id)
    reasons = _attempt_reasons(events)
    print(f"id: {rel.id}")
    print(f"repo: {rel.repo}")
    print(f"title: {rel.title}")
    print(f"task_class: {rel.task_class}")
    print(f"size: {rel.size}")
    print(f"data_class: {rel.data_class}")
    print(f"revision: {rel.revision}")
    print(f"base_sha: {rel.base_sha}")
    print(f"scope paths: {' '.join(rel.scope_paths)}")
    print(f"acceptance files: {' '.join(rel.acceptance.files)}")
    print(f"state: {view.state if view else 'new'}")
    if view and view.last_reason:
        print(f"reason: {view.last_reason}")
    print("attempts:")
    attempts = view.attempts if view else []
    open_attempt = view.open_attempt if view else None
    for attempt in attempts:
        aid = attempt.get("attempt_id", "-")
        model = attempt.get("model", "-")
        decision = attempt.get("decision")
        if decision is None:
            decision = view.state if attempt is open_attempt else "-"
        reason = "; ".join(reasons.get(aid, ()))
        if not reason and view and attempt is attempts[-1]:
            reason = view.last_reason
        print(f"  {aid}  {model}  {decision}  {reason}".rstrip())
    if not attempts:
        print("  none")
    print("outcome:")
    print(rel.outcome)
    return 0


def register(sub) -> dict:
    p = sub.add_parser("backlog", help="list releases with state, or show one in detail")
    sp = p.add_subparsers(dest="backlog_cmd", required=True)
    ls = sp.add_parser("list", help="one row per release, then a per-state summary")
    ls.add_argument("--state", action="append", default=[], dest="states", metavar="STATE",
                    help="only rows in this state (repeatable)")
    ls.add_argument("--repo", help="only rows for this repo")
    ls.add_argument("--open", action="store_true", help="drop landed rows")
    ls.add_argument("--json", action="store_true", help="print the filtered rows as JSON")
    show = sp.add_parser("show", help="release fields, state, attempts and outcome")
    show.add_argument("id")
    return {"backlog": _cmd}


def _cmd(args, log: EventLog) -> int:
    if args.backlog_cmd == "show":
        return _show(args.id, log)
    rows = _filtered(backlog_rows(load_releases(), log.read()), args.states,
                     args.repo, args.open)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        _print_table(rows)
    return 0
