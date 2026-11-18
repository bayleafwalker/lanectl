"""lanectl: autonomous lane runner (stage-0 seed)."""
from __future__ import annotations

import argparse
import importlib
import json
import pkgutil
import sys

from . import render, runner
from .config import home
from .events import open_log, project_items
from .render import CliError
from .status import release_rows

def discover_plugins(package_name: str) -> list:
    """Return direct submodules of *package_name* exposing a callable ``register``.

    Ordering is by submodule name so parsing is deterministic regardless of
    filesystem order. Adding a command plugin only requires adding its module.
    """
    package = importlib.import_module(package_name)
    found = []
    for info in pkgutil.iter_modules(package.__path__, package_name + "."):
        if info.name.endswith(".__main__"):   # the entry point holds no commands
            continue
        module = importlib.import_module(info.name)
        if callable(getattr(module, "register", None)):
            found.append(module)
    return sorted(found, key=lambda module: module.__name__.rsplit(".", 1)[-1])



# Top-level help: task groups, in reading order. Every registered command must be listed.
GROUPS = (
    ("Start here", (("status", "what needs you, what is blocked, what next"),
                    ("doctor", "health checks for home, repos, log and policy"),
                    ("ready", "Definition-of-Ready report for every release"),
                    ("tui", "read-only operator TUI"))),
    ("Plan work", (("backlog", "list, show, create, publish, rebase releases"),
                   ("lint-release", "check acceptance fails on base_sha"),
                   ("spec", "author and review a draft intent"),
                   ("triage", "turn failures into work proposals"),
                   ("closure", "turn owner flags into maintenance drafts"))),
    ("Run lanes", (("run", "claim and execute attempts (records events)"),
                   ("tick", "one unattended step: doctor, reap, run"),
                   ("reap", "close abandoned attempts (records events)"),
                   ("claim-hold", "advanced claim-only hold"),
                   ("claim-run", "preview or execute one coordinated claim"),
                   ("review-progress", "record judgment after a failed attempt"),
                   ("windows", "detect provider window exhaustion"))),
    ("Land to main", (("candidates", "attempts waiting for a train"),
                      ("train", "build a candidate train and run the check"),
                      ("land", "fast-forward main to a passed train"),
                      ("approve", "accept a review-required parked attempt"),
                      ("reject", "reject a candidate: requeue or --park"),
                      ("recheck", "requalify a train after fixes"),
                      ("integrate", "policy-bounded headless integration"),
                      ("plan-landing", "plan the landing of one train"),
                      ("deploy", "run, list or tear down a train deploy"),
                      ("work", "reconcile tracker completion"))),
    ("Observe", (("events", "print the event log tail"),
                 ("report", "precision, cost and stop conditions"),
                 ("lanes", "lane routing, limits and cap usage"),
                 ("capacity", "capacity headroom and burnable allocation"),
                 ("accounting", "lifecycle accounting and unknown costs"),
                 ("lifecycle", "joined owner and local lifecycle rows"),
                 ("verify", "lifecycle evidence bundles"),
                 ("learn", "posterior evidence and routing weights"),
                 ("evaluate", "rules-evaluate gate-accepted attempts"),
                 ("probe", "compare provider usage with the ledger"),
                 ("view", "static HTML view of the lane log"),
                 ("lifecycle-web", "static HTML lifecycle permalinks"),
                 ("otel", "export the log as OpenTelemetry spans"))),
    ("Admin", (("burn", "plan or execute a burn of expiring capacity"),
               ("focus", "attribute interactive usage to a release"),
               ("coordinate", "inspect the Vuoro coordination owner"),
               ("stream", "owner migration and authority config"),
               ("hook", "Claude Code hook entry points"))),
)
EXAMPLES = """Examples:
  lanectl status                 # what needs you and what to run next
  lanectl ready                  # which releases a lane can take
  lanectl candidates && lanectl train <repo> && lanectl land <train_id>

Run `lanectl <command> --help` for a command's options.
Exit codes: 0 ok, 1 failed, 2 usage, 3 not found, 5 precondition failed,
75 temporary (worker infrastructure failed; retry later)."""


def _version() -> str:
    """The checkout's pyproject version when running from one, else the installed wheel's.

    Install metadata in a dev venv goes stale between releases, so a checkout wins.
    """
    try:
        import tomllib
        from pathlib import Path
        text = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()
        data = tomllib.loads(text)
        if data["project"]["name"] == "lanectl":
            return data["project"]["version"]
    except Exception:
        pass
    try:
        from importlib.metadata import version
        return version("lanectl")
    except Exception:
        return "0.0.0+unknown"


class _Parser(argparse.ArgumentParser):
    """Suggests the nearest command for a misspelling instead of listing every verb."""

    def error(self, message):
        import difflib
        names = [c for a in self._actions if isinstance(a, argparse._SubParsersAction) for c in a.choices]
        if "invalid choice" in message and names:   # only a parser that owns commands guesses
            bad = message.split("'")[1] if "'" in message else ""
            near = difflib.get_close_matches(bad, names, n=1, cutoff=0.5)
            self.print_usage(sys.stderr)
            hint = f"did you mean {near[0]}?" if near else "see `lanectl --help`"
            self.exit(2, f"error: unknown command '{bad}'; {hint}\n")
        super().error(message)


class _Root(_Parser):
    def format_help(self) -> str:
        known = {c for a in self._actions if isinstance(a, argparse._SubParsersAction) for c in a.choices}
        out = ["lanectl: autonomous implementation lanes around cheap workers.", "",
               "Usage: lanectl [--version] [--debug] [--no-color] <command> [options]", ""]
        listed = set()
        for title, cmds in GROUPS:
            out.append(f"{title}:")
            out += [f"  {name:<16}{desc}" for name, desc in cmds if name in known]
            listed |= {n for n, _ in cmds}
            out.append("")
        rest = sorted(known - listed)
        if rest:
            out += ["Other:", *(f"  {n}" for n in rest), ""]
        return "\n".join(out) + "\n" + EXAMPLES + "\n"


# Help for plugin options that register without it, keyed by "<command path>:<dest>".
_MISSING_HELP = {
    "backlog show:id": "release id", "backlog new:id": "new release id (directory name)",
    "backlog new:title": "one-line release title", "backlog new:task_class": "task class (default glue)",
    "backlog new:size": "size class (default S)", "backlog new:data_class": "data class (default public)",
    "backlog publish:id": "release id to publish", "backlog rebase:ids": "release ids to move to main",
    "burn:lane": "lane to burn capacity for", "closure scan:record": "record the scan as an event",
    "closure draft:fingerprint": "recurring-flag fingerprint from `closure list`",
    "closure draft:author_model": "model that authors the draft", "closure draft:reviewer_model": "model that reviews it",
    "closure draft:scope": "write-scope glob (repeatable)", "closure draft:lane": "lane the draft targets",
    "deploy run:train_id": "train id to deploy", "deploy down:train_id": "train id to tear down",
    "focus:role": "role the session plays (default planner)", "integrate:max_trains": "most trains to integrate (default 3)",
    "recheck:train_id": "train id to requalify", "plan-landing:train_id": "train id to plan",
    "learn:lane": "lane to learn from", "lint-release:release_dirs": "release directories to check",
    "spec:id": "new release id", "spec:repo": "repo name from governance/repos.toml", "spec:title": "release title",
    "spec:intent_file": "file holding the intent text", "spec:scope": "write-scope glob (repeatable)",
    "spec:author_model": "model that authors the spec", "spec:reviewer_model": "model that reviews it",
    "spec:lane": "lane the release targets", "spec:task_class": "task class", "spec:size": "size class",
    "spec:data_class": "data class", "spec:work": "tracker item as <repo>#<id>",
    "spec:work_complete": "landing closes the tracker item", "spec:timeout": "seconds allowed per model call",
    "stream init:database": "database to initialise", "stream configure:repo": "repo the stream belongs to",
    "stream configure:home": "lanectl home to record", "stream configure:stream": "stream name",
    "stream import:repo": "repo the stream belongs to", "stream import:home": "lanectl home to record",
    "stream import:stream": "stream name", "stream import:source": "local event log to import",
    "stream backup:database": "database to back up", "stream backup:artifact": "backup file to write",
    "stream restore:artifact": "backup file to read", "stream restore:destination": "database to restore into",
    "tick:lane": "lane to run (default implement)", "tui:view": "view to open: ready, active or verification",
}


def _fill_help(parser, path=()) -> None:
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            for name, sp in a.choices.items():
                _fill_help(sp, (*path, name))
        elif a.help is None and a.dest != "help":
            a.help = _MISSING_HELP.get(f"{' '.join(path)}:{a.dest}")


def _needs_home(cmd: str) -> bool:
    return cmd in {"status", "ready", "candidates", "backlog", "lanes", "run"}


def _check_home() -> None:
    root = home()
    if not (root / "governance" / "repos.toml").is_file():
        raise CliError(f"no lanectl governance found at {root}",
                       why="governance/repos.toml is missing (LANECTL_HOME unset or wrong, "
                           "and no checkout above the working directory)",
                       fix="export LANECTL_HOME=<lanectl checkout>   # or cd into it; check with: lanectl doctor",
                       code=3, slug="home_not_found")


def _effect(args, what: str, plan: str, act) -> int:
    """Shared tail for effectful commands: preview, confirm, act, receipt and next step.

    ``act`` returns ``(exit_code, message)``: 0 done, 3 not found, 5 refused. The code is never
    derived from the message text.
    """
    if args.dry_run:
        print(f"would {plan}\nnext: rerun without --dry-run")
        return 0
    if not render.confirm(f"{what}?", yes=args.yes):
        print("cancelled; nothing changed")
        return 1
    code, result = act()
    print(f"{render.sym(render.OK if code == 0 else render.FAILED)} {result}")
    print("next: lanectl status")
    return code


def _not_found(kind: str, ident: str, listing: str) -> CliError:
    return CliError(f"unknown {kind} {ident}", why=f"no such {kind} in the event log",
                    fix=listing, code=3, slug=f"{kind}_not_found")


def _landed(result: str) -> tuple[int, str]:
    return (0 if result.startswith("landed") else 5), result   # "landed [...] (already recorded)" is a landing


def _reject(log, attempt_id: str, reason: str, park: bool) -> tuple[int, str]:
    if not any(x["attempt_id"] == attempt_id for v in project_items(log.read()).values()
               for x in v.attempts):
        return 3, f"unknown attempt {attempt_id}; list them with `lanectl candidates`"
    result = runner.integrator_reject(log, attempt_id, reason, park)
    return (0 if result.endswith((": parked", ": requeued")) else 5), result


def _add_effect_flags(p) -> None:
    p.add_argument("--dry-run", action="store_true", help="print what would happen; change nothing")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation on a terminal")


def _build_parser():
    p = _Root(prog="lanectl", description=__doc__, add_help=True)
    p.add_argument("--version", action="version", version=f"lanectl {_version()}")
    p.add_argument("--debug", action="store_true", help="show tracebacks instead of one-line errors")
    p.add_argument("--no-color", action="store_true", help="never colour output")
    sub = p.add_subparsers(dest="cmd", metavar="<command>", parser_class=_Parser)
    r = sub.add_parser("run", help="admit and execute attempts until caps or the queue stop it")
    r.add_argument("--lane", default="implement", help="lane to claim from (default implement)")
    r.add_argument("--item", help="only claim this release id")
    r.add_argument("--max", type=int, default=1, help="attempts to run sequentially (default 1)")
    rd = sub.add_parser("ready", help="Definition-of-Ready report for every release")
    rd.add_argument("--lane", default="implement", help="lane to check against (default implement)")
    rd.add_argument("--all", action="store_true", help="include landed releases")
    rd.add_argument("--json", action="store_true", help='one object (schema "lanectl.ready/v1")')
    cd = sub.add_parser("candidates", help="attempts waiting for a train or landing")
    cd.add_argument("--json", action="store_true", help='one object (schema "lanectl.candidates/v1")')
    t = sub.add_parser("train", help="build a candidate train on top of main and run the repo check")
    t.add_argument("repo", help="repo name from governance/repos.toml")
    t.add_argument("--only", nargs="*", metavar="ATTEMPT_ID", help="train only these attempts")
    l = sub.add_parser("land", help="fast-forward main to a passed train (records events, moves main)")
    l.add_argument("train_id", help="train id from `lanectl train`")
    l.add_argument("--resume-owner", action="store_true", help="resume the existing lease for a single coordinated attempt")
    _add_effect_flags(l)
    rj = sub.add_parser("reject", help="integrator rejects a candidate: requeue, or --park (records events)")
    rj.add_argument("attempt_id", help="attempt id from `lanectl candidates`")
    rj.add_argument("reason", help="why; recorded on the item")
    rj.add_argument("--park", action="store_true", help="park the item instead of requeueing it")
    _add_effect_flags(rj)
    pr = sub.add_parser("review-progress", help="record agent judgment after a failed attempt")
    pr.add_argument("attempt_id", help="the failed attempt")
    pr.add_argument("judgment", choices=("continue", "stop"), help="continue with a new attempt, or stop")
    pr.add_argument("--progress", required=True, help="what the attempt achieved")
    pr.add_argument("--remaining", required=True, help="what is left")
    pr.add_argument("--reason", required=True, help="why continue or stop")
    ap = sub.add_parser("approve", help="accept a review-required parked attempt (records events)")
    ap.add_argument("attempt_id", help="the parked attempt")
    ap.add_argument("note", help="review note recorded with the approval")
    ev = sub.add_parser("events", help="print the log tail")
    ev.add_argument("-n", type=int, default=30, help="number of events (default 30)")
    ev.add_argument("--item", help="only events for this release id")
    ev.add_argument("--type", action="append", dest="types", metavar="EVENT_TYPE",
                    help="only print events of this type (repeatable)")
    ev.add_argument("--json", action="store_true", help='one object (schema "lanectl.events/v1")')
    handlers = {}
    for plugin in discover_plugins("lanectl"):
        handlers.update(plugin.register(sub))
    _fill_help(p)
    return p, sub, handlers


def main(argv: list[str] | None = None) -> int:
    parser, sub, handlers = _build_parser()
    a = parser.parse_args(argv)
    if a.no_color:
        import os
        os.environ["NO_COLOR"] = "1"
    if a.cmd is None:
        print(parser.format_help(), end="")
        return 0
    try:
        return _dispatch(a, handlers)
    except CliError as e:
        if a.debug:
            raise
        print(f"error: {e.message}", file=sys.stderr)
        for key in ("why", "fix"):
            if getattr(e, key):
                print(f"  {key}: {getattr(e, key)}", file=sys.stderr)
        if getattr(a, "json", False):
            print(json.dumps(e.as_dict()))
        return e.code


def _dispatch(a, handlers) -> int:
    if a.cmd == "coordinate" and (a.require_stream_read or a.work_item is not None):
        return handlers[a.cmd](a, None)
    if a.cmd == "lifecycle" and (a.work_id is not None or a.run_id is not None):
        return handlers[a.cmd](a, None)
    if a.cmd == "stream" and a.stream_action in {"backup", "restore"}:
        return handlers[a.cmd](a, None)
    if _needs_home(a.cmd):
        _check_home()
    try:
        log = open_log()
    except ValueError as e:
        raise CliError(f"cannot open the event log: {e}",
                       why="the backend marker or LANECTL_STREAM_REPO selects an invalid authority",
                       fix="inspect <state dir>/backend.json, or unset LANECTL_STREAM_REPO",
                       code=1, slug="backend_invalid") from e
    if a.cmd in handlers:
        return handlers[a.cmd](a, log)

    if a.cmd == "run":
        for _ in range(a.max):
            c = runner.admit(a.lane, log, only=a.item)
            if isinstance(c, str):
                print(c)
                return 0
            print(f"claimed {c.attempt_id} -> {c.model}", flush=True)
            out = runner.execute(c, log)
            print(out, flush=True)
            if "-> rejected: infra:" in out or "-> rejected: infra" in out:
                print("breaker: worker infrastructure failure; stopping this run loop", flush=True)
                return 75   # EX_TEMPFAIL: retry later; 3 is reserved for not found
        return 0
    if a.cmd == "ready":
        rows = release_rows(log.read(), a.lane, include_landed=a.all)
        if a.json:
            print(json.dumps({"schema": "lanectl.ready/v1", "lane": a.lane, "releases": rows}))
            return 0
        for r in rows:
            print(f"{r['state']:8} {r['id']}" + "".join(f"\n    - {x}" for x in r["reasons"]))
        return 0
    if a.cmd == "candidates":
        rows = runner.candidates(log)
        if a.json:
            print(json.dumps({"schema": "lanectl.candidates/v1", "candidates": rows}))
            return 0
        for c in rows:
            print(f"{c['repo']:14} {c['attempt_id']:40} {c['branch']}  {c['title']}")
        if rows:
            print(f"{len(rows)} candidate(s)\nnext: lanectl train {rows[0]['repo']}")
        else:
            print("No candidates.\nnext: lanectl status")
        return 0
    if a.cmd == "train":
        print(runner.build_train(log, a.repo, a.only))
        return 0
    if a.cmd == "land":
        tb = next((e["data"] for e in reversed(log.read())
                   if e["type"] == "train.built" and e["data"]["train_id"] == a.train_id), None)
        if tb is None:
            raise _not_found("train", a.train_id, "lanectl candidates   # then: lanectl train <repo>")
        plan = f"land train {a.train_id}: fast-forward {tb['repo']} main with attempts {tb['attempts']}"
        return _effect(a, f"Land train {a.train_id} on main", plan,
                       lambda: _landed(runner.land(log, a.train_id, resume_owner=a.resume_owner)))
    if a.cmd == "approve":
        print(runner.approve(log, a.attempt_id, a.note))
        return 0
    if a.cmd == "review-progress":
        print(runner.review_progress(log, a.attempt_id, a.judgment, a.progress, a.remaining, a.reason))
        return 0
    if a.cmd == "reject":
        verb = "park" if a.park else "requeue"
        return _effect(a, f"Reject {a.attempt_id} ({verb})",
                       f"{verb} attempt {a.attempt_id}: {a.reason}",
                       lambda: _reject(log, a.attempt_id, a.reason, a.park))
    if a.cmd == "events":
        known = {e["type"] for e in log.read()}
        for t in a.types or ():
            if t not in known:
                print(f"note: no events of type {t!r} in the log", file=sys.stderr)
        evs = [e for e in log.read()
               if (not a.item or e["item_id"] == a.item)
               and (not a.types or e["type"] in a.types)][-a.n:]
        if a.json:
            print(json.dumps({"schema": "lanectl.events/v1", "events": evs}))
            return 0
        for e in evs:
            print(json.dumps(e, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
