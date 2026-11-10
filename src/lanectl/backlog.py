"""Backlog DX: list, inspect, scaffold and rebase WorkReleases.

``backlog_rows`` is a pure join of ``release.toml`` fields with the item
projection, so the operator no longer needs ``status``, ``events --item`` and
the release file side by side to see what is open.

``backlog new`` scaffolds a draft release at the repo's current main,
``backlog publish`` lifts the draft flag once the human edits are in and the
acceptance test fails on base for the right reason, and ``backlog rebase``
moves pending releases to a moved main. All three write only under
``<home>/backlog/`` and edit ``release.toml`` as text, so comments and layout
survive.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from .config import home, load_release, load_releases, load_repos
from .contracts import ContractError, check_id
from .events import EventLog, project_items
from .lint_release import lint_release

STUB_MESSAGE = "write the acceptance test"

# Item states a pending release can be in; anything landed or in flight is left
# alone by ``rebase --pending``.
PENDING_STATES = ("new", "ready", "requeued", "parked", "rejected")
IN_FLIGHT_STATES = ("claimed", "implemented", "gated", "candidate", "in-train")

_BASE_RE = re.compile(r"^[ \t]*base_sha[ \t]*=.*$", re.MULTILINE)
_REV_RE = re.compile(r"^[ \t]*revision[ \t]*=[ \t]*\d+[ \t]*$", re.MULTILINE)
_DRAFT_RE = re.compile(r"^[ \t]*draft[ \t]*=[ \t]*true[ \t]*\n?", re.MULTILINE)

RELEASE_TEMPLATE = """\
id = {id}
repo = {repo}
base_sha = {base_sha}
revision = 1
draft = true
title = {title}
task_class = {task_class}
size = {size}
data_class = {data_class}

outcome = \"\"\"
TODO: describe the outcome; replace this line with what the release delivers.
\"\"\"

[scope]
paths = [{paths}]

[acceptance]
files = [{files}]
exec = [{exec_cmd}]
"""

STUB_TEMPLATE = '''\
"""Acceptance test for {id}: replace this stub with the real test."""


def test_acceptance():
    raise AssertionError("{message} for {id}")
'''


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


def _main_sha(repo) -> str:
    """The repo's current commit on its main branch (RepoSpec.main)."""
    p = subprocess.run(["git", "-C", str(repo.path), "rev-parse", repo.main],
                       capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"git rev-parse {repo.main}: {p.stderr.strip()}")
    return p.stdout.strip()


def _quote(value: str) -> str:
    return json.dumps(value)


def _exec_cmd(test_cmd: str, path: str) -> str:
    if "{files}" in test_cmd:
        return test_cmd.replace("{files}", path)
    return f"{test_cmd} {path}"


def _release_dir(release_id: str) -> Path:
    return home() / "backlog" / release_id


def _set_base_sha(text: str, sha: str) -> str:
    if _BASE_RE.search(text):
        return _BASE_RE.sub(f'base_sha = "{sha}"', text, count=1)
    return text


def _bump_revision(text: str, revision: int) -> str:
    if _REV_RE.search(text):
        return _REV_RE.sub(f"revision = {revision}", text, count=1)
    # Add the line right after base_sha, matching the layout of existing files.
    if _BASE_RE.search(text):
        return _BASE_RE.sub(lambda m: f"{m.group(0)}\nrevision = {revision}", text, count=1)
    return text


def _drop_draft(text: str) -> str:
    return _DRAFT_RE.sub("", text, count=1)


def _new(args) -> int:
    try:
        check_id("id", args.id)
    except ContractError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    repos = load_repos()
    repo = repos.get(args.repo)
    if repo is None:
        print(f"unknown repo {args.repo}", file=sys.stderr)
        return 2
    release_dir = _release_dir(args.id)
    if release_dir.exists():
        print(f"{release_dir} already exists", file=sys.stderr)
        return 2
    try:
        base_sha = _main_sha(repo)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"cannot resolve {repo.name} {repo.main}: {exc}", file=sys.stderr)
        return 2

    test = args.test or f"tests/test_acc_{args.id.replace('-', '_')}.py"
    toml = RELEASE_TEMPLATE.format(
        id=_quote(args.id), repo=_quote(repo.name), base_sha=_quote(base_sha),
        title=_quote(args.title), task_class=_quote(args.task_class),
        size=_quote(args.size), data_class=_quote(args.data_class),
        paths=", ".join(_quote(p) for p in args.scope),
        files=_quote(test), exec_cmd=_quote(_exec_cmd(repo.test_cmd, test)))
    stub = STUB_TEMPLATE.format(id=args.id, message=STUB_MESSAGE)

    try:
        (release_dir / "files" / test).parent.mkdir(parents=True, exist_ok=True)
        (release_dir / "files" / test).write_text(stub)
        (release_dir / "release.toml").write_text(toml)
        load_release(release_dir)
    except (OSError, ContractError, ValueError) as exc:
        print(f"cannot scaffold {release_dir}: {exc}", file=sys.stderr)
        return 2
    print(release_dir)
    return 0


def _find(release_id: str):
    return next((r for r in load_releases() if r.id == release_id), None)


def _lint_override(toml: Path) -> str:
    """The planner's recorded ``[lint] override`` text, or "" when absent.

    A planner records the reason a lint problem is acceptable in the release
    itself, next to the outcome it qualifies, so publishing stays a text edit
    a person can review. An empty or non-string value records nothing.
    """
    try:
        raw = tomllib.loads(toml.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    lint = raw.get("lint")
    override = lint.get("override") if isinstance(lint, dict) else None
    return override.strip() if isinstance(override, str) else ""


def _publish(args) -> int:
    rel = _find(args.id)
    if rel is None:
        print(f"unknown release {args.id}", file=sys.stderr)
        return 2
    if not rel.draft:
        print("already published")
        return 0
    release_dir = Path(rel.release_dir)
    if rel.outcome.strip().startswith("TODO"):
        print("outcome still starts with TODO; describe the outcome first")
        return 1
    for name in rel.acceptance.files:
        path = release_dir / "files" / name
        if path.is_file() and STUB_MESSAGE in path.read_text():
            print(f"{name}: still the stub ({STUB_MESSAGE})")
            return 1
    problems = lint_release(release_dir)
    toml = release_dir / "release.toml"
    if problems:
        for problem in problems:
            print(problem)
        override = _lint_override(toml)
        if not override:
            return 1
        print(f"lint override: {override}")
    toml.write_text(_drop_draft(toml.read_text()))
    return 0


def _rebase_one(release_dir: Path, rel, sha: str) -> str:
    """Move one release onto *sha* in place; return the line to print."""
    toml = release_dir / "release.toml"
    text = toml.read_text()
    if rel.base_sha == sha:
        return f"{rel.id}: up to date"
    revision = rel.revision + 1
    text = _bump_revision(_set_base_sha(text, sha), revision)
    toml.write_text(text)
    return f"{rel.id}: {rel.base_sha[:12]} -> {sha[:12]} r{revision}"


def _rebase(args, log: EventLog) -> int:
    releases = load_releases()
    items = project_items(log.read())
    if args.pending:
        selected = [r for r in releases
                    if (items[r.id].state if r.id in items else "new") in PENDING_STATES]
        named = False
    else:
        by_id = {r.id: r for r in releases}
        missing = [i for i in args.ids if i not in by_id]
        for item in missing:
            print(f"unknown release {item}", file=sys.stderr)
        if missing:
            return 2
        selected = [by_id[i] for i in args.ids]
        named = True

    repos = load_repos()
    shas: dict[str, str | None] = {}
    failed = False
    for rel in selected:
        state = items[rel.id].state if rel.id in items else "new"
        if named and state in IN_FLIGHT_STATES:
            print(f"{rel.id}: in flight ({state})")
            failed = True
            continue
        if not named and state not in PENDING_STATES:
            continue
        repo = repos.get(rel.repo)
        if repo is None:
            print(f"{rel.id}: unknown repo {rel.repo}", file=sys.stderr)
            failed = True
            continue
        if repo.name not in shas:
            try:
                shas[repo.name] = _main_sha(repo)
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                print(f"{rel.id}: cannot resolve {repo.name} {repo.main}: {exc}",
                      file=sys.stderr)
                shas[repo.name] = None
        sha = shas[repo.name]
        if sha is None:
            failed = True
            continue
        print(_rebase_one(Path(rel.release_dir), rel, sha))
    return 1 if failed else 0


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
    new = sp.add_parser("new", help="scaffold a draft release at the repo's current main")
    new.add_argument("id")
    new.add_argument("--repo", required=True, help="repo name from governance/repos.toml")
    new.add_argument("--title", required=True)
    new.add_argument("--scope", action="append", required=True, dest="scope", metavar="GLOB",
                     help="write-scope glob (repeatable)")
    new.add_argument("--class", default="glue", dest="task_class", metavar="CLASS")
    new.add_argument("--size", default="S", choices=("S", "M"))
    new.add_argument("--data-class", default="public", dest="data_class",
                     choices=("public", "restricted"))
    new.add_argument("--test", metavar="PATH", help="acceptance test path in the release")
    pub = sp.add_parser("publish", help="lift the draft flag once the release is edited")
    pub.add_argument("id")
    rebase = sp.add_parser("rebase", help="move pending releases to the repo's current main")
    rebase.add_argument("ids", nargs="*", metavar="id")
    rebase.add_argument("--pending", action="store_true",
                        help="every release whose item is new, ready, requeued, parked or rejected")
    return {"backlog": _cmd}


def _cmd(args, log: EventLog) -> int:
    if args.backlog_cmd == "show":
        return _show(args.id, log)
    if args.backlog_cmd == "new":
        return _new(args)
    if args.backlog_cmd == "publish":
        return _publish(args)
    if args.backlog_cmd == "rebase":
        return _rebase(args, log)
    rows = _filtered(backlog_rows(load_releases(), log.read()), args.states,
                     args.repo, args.open)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        _print_table(rows)
    return 0
