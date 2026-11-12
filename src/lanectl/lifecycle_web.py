"""Read-only lifecycle permalinks and a self-contained shareable review page.

A locator is a deterministic, percent-encoded identity under ``/lifecycle/``,
never an authority.  The review page renders the existing lifecycle fact schema
and attention reason codes, escapes every untrusted value, and never emits
bodies, logs, credentials, local absolute paths, active markup, inline event
handlers, browser file fetches, or external assets.
"""
from __future__ import annotations

import html
import shlex
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from .lifecycle import REASON_RULES, attention_reasons, lifecycle_rows

#: Query keys a locator may carry; both are optional, each at most once.
_LINKED_IDS = ("run_id", "train_id")

#: Optional numeric work id a locator may carry, at most once.
_WORK_ID = "work_id"

#: Explicit reference fields that may be shared, never arbitrary bodies/logs.
_REF_KEYS = ("ref", "reference")

#: Runtime payload keys that are never searched for references.
_RUNTIME_KEYS = ("body", "log", "transcript", "detail", "claims")

#: Accounting phases, in display order (mirrors accounting.render_timeline).
_ACCOUNTING_PHASES = ("queued", "execution", "integration", "verification")

#: Flat, semantic colour palette (paper blue / navy / white / slate / blue /
#: warning).  No shadows, rounded corners, transitions or animation.
_STYLE = """
:root { --paper:#f3f7fb; --navy:#19344d; --white:#ffffff; --slate:#526779;
        --blue:#255e9a; --warning:#8b4b14; }
html { background:var(--paper); }
body { margin:0; padding:1.25rem 1rem 3rem; background:var(--paper);
       color:var(--navy); font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
       line-height:1.45; }
main { max-width:70rem; margin:0 auto; }
header { background:var(--white); border:1px solid var(--slate);
         border-top:4px solid var(--blue); padding:1rem 1.25rem; }
h1 { margin:0 0 .25rem; font-size:1.5rem; }
h2 { margin:2rem 0 .5rem; padding-bottom:.25rem; border-bottom:1px solid var(--slate); }
a { color:var(--blue); }
a:focus, a:hover { outline:2px solid var(--blue); outline-offset:2px; }
code, pre { font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace; }
.muted { color:var(--slate); }
.warning { color:var(--warning); }
.unavailable { color:var(--warning); }
.tag { font-size:.8rem; color:var(--white); background:var(--slate);
       padding:.05rem .4rem; }
.tag.local { background:var(--blue); }
dl { margin:.5rem 0; }
dt { font-weight:700; }
.identifiers { display:grid; grid-template-columns:auto 1fr; gap:.2rem .75rem;
               margin:.75rem 0; }
.identifiers dt { color:var(--slate); }
.identifiers dd { margin:0; }
.provenance { display:flex; flex-wrap:wrap; gap:.75rem 1.75rem; margin:.75rem 0;
              padding:.5rem 0; border-top:1px solid var(--slate);
              border-bottom:1px solid var(--slate); }
.provenance div { display:flex; gap:.35rem; }
.provenance dt { color:var(--slate); font-weight:400; }
.provenance dd { margin:0; }
.table-wrap { overflow-x:auto; }
table { border-collapse:collapse; width:100%; margin:.5rem 0; }
caption { text-align:left; padding:.25rem 0; color:var(--slate); }
th, td { border:1px solid var(--slate); padding:.35rem .5rem; text-align:left;
         vertical-align:top; }
th { background:var(--white); color:var(--navy); }
tr:nth-child(even) td { background:var(--white); }
.state { font-weight:700; }
.state-observed { color:var(--blue); }
.state-unknown { color:var(--warning); }
.state-missing { color:var(--warning); }
.state-rejected { color:var(--warning); }
.state-stale { color:var(--warning); }
.reasons { padding-left:1.25rem; }
.reasons li { margin:.35rem 0; }
.jump { margin:.35rem 0; overflow-wrap:anywhere; }
"""


def _esc(value: object) -> str:
    """HTML-escape an untrusted value for text or attribute content."""
    return html.escape("-" if value is None else str(value), quote=True)


def _origin(base_url: str) -> str:
    """Validate an https origin and return it without a trailing slash."""
    if base_url == "":
        return ""
    try:
        parts = urlsplit(base_url)
    except ValueError as exc:
        raise ValueError(f"invalid base URL: {base_url!r}") from exc
    if parts.scheme != "https":
        raise ValueError("base URL must use https")
    if not parts.netloc or "@" in parts.netloc:
        raise ValueError("base URL must not carry userinfo")
    if parts.query or parts.fragment:
        raise ValueError("base URL must not carry a query or fragment")
    if parts.path not in ("", "/"):
        raise ValueError("base URL must be an origin without a path")
    return base_url.rstrip("/")


def locator(repo: str, row: dict, *, base_url: str = "") -> str:
    """Deterministic, percent-encoded lifecycle identity URL.

    The path is ``/lifecycle/<repo>/<item>/<attempt>`` and the query carries
    ``run_id`` and ``train_id`` only when known, plus the numeric ``work_id``
    when the row resolves one.  ``base_url``, when given, is an https origin
    prepended verbatim; otherwise the result is relative.
    """
    origin = _origin(base_url)
    segments = (repo, row.get("item_id"), row.get("attempt_id"))
    path = "/lifecycle/" + "/".join(quote(str(segment), safe="") for segment in segments)
    query = []
    for key in _LINKED_IDS:
        value = row.get(key)
        if value is not None and str(value) != "":
            query.append(f"{key}={quote(str(value), safe='')}")
    work_id = row.get(_WORK_ID)
    if isinstance(work_id, int) and not isinstance(work_id, bool) and work_id > 0:
        query.append(f"{_WORK_ID}={work_id}")
    url = path + ("?" + "&".join(query) if query else "")
    return origin + url


def _decode_identity(path: str) -> tuple[str, str, str]:
    """Decode and validate the three ``/lifecycle/`` path segments.

    Empty segments, ``.``/``..``, decoded slashes/backslashes/NUL, and
    non-canonically encoded segments are all refused, so the filesystem path
    derived from a locator can never escape its root.
    """
    if not path.startswith("/lifecycle/"):
        raise ValueError("locator path must live under /lifecycle/")
    raw_segments = path[len("/lifecycle/"):].split("/")
    if len(raw_segments) != 3:
        raise ValueError("locator must identify repo, item and attempt")
    decoded = []
    for raw in raw_segments:
        if raw == "":
            raise ValueError("locator has an empty identity segment")
        segment = unquote(raw)
        if segment in ("", ".", "..") or "/" in segment or "\\" in segment or "\x00" in segment:
            raise ValueError("locator contains path traversal")
        if quote(segment, safe="") != raw:
            raise ValueError("locator identity is not canonically percent-encoded")
        decoded.append(segment)
    return decoded[0], decoded[1], decoded[2]


def resolve_locator(url: str) -> dict:
    """Parse a locator back into its identifiers, or refuse it.

    Purely local: this never contacts a network.  Only https (or relative)
    locators are accepted, without userinfo, fragment, duplicate or unknown
    query keys, empty path segments, or path traversal (``..``, ``.``, slashes)
    after decoding.  Over- or under-encoded segments are rejected too, so the
    round-trip is exact.
    """
    if not isinstance(url, str):
        raise ValueError("locator must be a string")
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise ValueError(f"malformed locator: {url!r}") from exc
    if parts.scheme not in ("", "https"):
        raise ValueError(f"unsupported locator scheme: {parts.scheme!r}")
    if parts.scheme == "https" and not parts.netloc:
        raise ValueError("https locator is missing a host")
    if "@" in parts.netloc:
        raise ValueError("locator must not carry userinfo")
    if parts.fragment:
        raise ValueError("locator must not carry a fragment")
    repo, item_id, attempt_id = _decode_identity(parts.path)
    query = {}
    if parts.query:
        pairs = parts.query.split("&")
        for pair in pairs:
            if "=" in pair:
                key, value = pair.split("=", 1)
            else:
                key, value = pair, ""
            key = unquote(key)
            if key not in _LINKED_IDS and key != _WORK_ID:
                raise ValueError(f"unsupported locator query key: {key!r}")
            if key in query:
                raise ValueError(f"duplicate locator query key: {key!r}")
            query[key] = unquote(value)
    resolved = {"repo": repo, "item_id": item_id, "attempt_id": attempt_id,
                "run_id": query.get("run_id"), "train_id": query.get("train_id")}
    if _WORK_ID in query:
        raw = query[_WORK_ID]
        try:
            work_id = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"work_id must be a numeric query value: {raw!r}") from None
        if str(work_id) != raw or work_id <= 0:
            raise ValueError(f"work_id must be a canonical positive integer: {raw!r}")
        resolved[_WORK_ID] = work_id
    return resolved


def _latest_observed_at(facts: dict) -> str:
    stamps = [fact.get("observed_at") for fact in facts.values()
              if isinstance(fact.get("observed_at"), str)]
    return max(stamps) if stamps else "unknown"


def _local_checkpoint(facts: dict):
    checkpoints = [fact.get("checkpoint") for name, fact in facts.items()
                   if name.startswith("local.") and fact.get("checkpoint") is not None]
    return max(checkpoints) if checkpoints else None


def _ident(value, missing: str = "unavailable") -> str:
    if value is None or str(value) == "":
        return f'<span class="unavailable">{missing}</span>'
    return f"<code>{_esc(value)}</code>"


def _jump(repo, item_id, attempt_id) -> str:
    parts = ["lanectl", "tui", "--view", "active", "--repo", str(repo)]
    if item_id is not None:
        parts += ["--item", str(item_id)]
    if attempt_id is not None:
        parts += ["--attempt", str(attempt_id)]
    return " ".join(shlex.quote(part) for part in parts)


def _state_label(state: str) -> str:
    state = state if isinstance(state, str) and state else "unknown"
    cls = f"state state-{state}" if state in (
        "observed", "unknown", "missing", "rejected", "stale") else "state state-unknown"
    return f'<span class="{cls}">{_esc(state)}</span>'


def _fact_rows(facts: dict) -> list[tuple]:
    rows = []
    for name, fact in facts.items():
        if not isinstance(fact, dict):
            continue
        note = ""
        if fact.get("state") != "observed":
            note = fact.get("reason") if isinstance(fact.get("reason"), str) else ""
        rows.append((name, fact.get("state"), fact.get("source"),
                     fact.get("revision"), fact.get("checkpoint"),
                     fact.get("observed_at"), note))
    return rows


def _facts_html(facts: dict) -> str:
    if not facts:
        return '<p class="muted">no fact groups available</p>'
    rows = []
    for name, state, source, revision, checkpoint, observed_at, note in _fact_rows(facts):
        label = _esc(name)
        if name.startswith("local."):
            label += ' <span class="tag local">local-only</span>'
        note_html = f'<span class="warning">{_esc(note)}</span>' if note else ""
        rows.append("<tr>"
                    f"<td>{label}</td>"
                    f"<td>{_state_label(state)}</td>"
                    f"<td>{_esc(source)}</td>"
                    f"<td>{_esc(revision)}</td>"
                    f"<td>{_esc(checkpoint)}</td>"
                    f"<td>{_esc(observed_at)}</td>"
                    f"<td>{note_html}</td>"
                    "</tr>")
    return ("<div class=\"table-wrap\"><table>"
            "<caption>Lifecycle fact groups, observed read-only</caption>"
            "<thead><tr><th scope=\"col\">Fact group</th><th scope=\"col\">State</th>"
            "<th scope=\"col\">Source</th><th scope=\"col\">Revision</th>"
            "<th scope=\"col\">Checkpoint</th><th scope=\"col\">Observed at</th>"
            "<th scope=\"col\">Note</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table></div>")


def _reasons_html(reasons) -> str:
    reasons = reasons or []
    if not reasons:
        return '<p class="muted">no attention reasons</p>'
    items = []
    for reason in reasons:
        if not isinstance(reason, dict):
            continue
        code = reason.get("code", "unknown")
        rule = REASON_RULES.get(code, "")
        actions = reason.get("next_actions") or reason.get("next_action")
        next_text = ", ".join(actions) if isinstance(actions, (list, tuple)) else str(actions or "")
        item = f"<code>{_esc(code)}</code>"
        if rule:
            item += f" — {_esc(rule)}"
        if next_text:
            item += f' <span class="muted">(next: {_esc(next_text)})</span>'
        items.append(f"<li>{item}</li>")
    return "<ul class=\"reasons\">" + "".join(items) + "</ul>"


def _collect_references(value, out: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _RUNTIME_KEYS:
                continue
            if key in _REF_KEYS and isinstance(child, str):
                out.append(child)
            else:
                _collect_references(child, out)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _collect_references(child, out)


def _safe_reference(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme not in ("https", "lane"):
        return None
    if parts.query or parts.fragment:
        return None
    if parts.scheme == "https" and (not parts.netloc or "@" in parts.netloc):
        return None
    if parts.scheme == "lane" and ("@" in parts.netloc or not parts.netloc):
        return None
    return value


def _references_html(facts: dict) -> str:
    collected: list[str] = []
    for fact in facts.values():
        if isinstance(fact, dict):
            _collect_references(fact.get("value"), collected)
    safe: list[str] = []
    for ref in collected:
        checked = _safe_reference(ref)
        if checked and checked not in safe:
            safe.append(checked)
    if not safe:
        return ""
    items = []
    for ref in safe:
        if ref.startswith("https://"):
            items.append(f'<li><a href="{_esc(ref)}">{_esc(ref)}</a></li>')
        else:
            items.append(f'<li><code>{_esc(ref)}</code></li>')
    return "<h2>References</h2><ul>" + "".join(items) + "</ul>"


def _evidence_html(row: dict) -> str:
    try:
        from .verification import evidence_bundle  # UI-06, may not be merged yet
    except ImportError:
        return '<p class="muted">verification evidence bundle unavailable</p>'
    try:
        bundle = evidence_bundle(row)
    except Exception:
        bundle = None
    if not isinstance(bundle, dict):
        return '<p class="muted">verification evidence bundle unavailable</p>'
    outcome = bundle.get("outcome")
    entries = bundle.get("entries") or []
    rows = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        rows.append("<tr>"
                    f"<td>{_esc(entry.get('kind'))}</td>"
                    f"<td>{_state_label(entry.get('state', 'unknown'))}</td>"
                    f"<td>{_esc(entry.get('source'))}</td>"
                    f"<td>{_esc(entry.get('revision'))}</td>"
                    f"<td>{_esc(entry.get('checkpoint'))}</td>"
                    f"<td>{_esc(entry.get('observed_at'))}</td></tr>")
    table = ("<div class=\"table-wrap\"><table>"
             "<caption>Verification evidence bundle</caption>"
             "<thead><tr><th scope=\"col\">Kind</th><th scope=\"col\">State</th>"
             "<th scope=\"col\">Source</th><th scope=\"col\">Revision</th>"
             "<th scope=\"col\">Checkpoint</th><th scope=\"col\">Observed at</th>"
             "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")
    return f"<h2>Verification</h2><p>outcome: <code>{_esc(outcome)}</code></p>{table}"


def _fmt_duration(value) -> str:
    return "unknown" if value is None else f"{value}s"


def _fmt_usd(value) -> str:
    return "unknown" if value is None else f"${value:.4f}"


def _accounting_html(accounting) -> str:
    """Render the shared accounting projection without inventing zero costs.

    Only the projection's summary fields are emitted: phase durations, usage
    units, known cost subtotals, attribution and price revision.  Raw event
    payloads never appear, and missing totals stay ``unknown`` rather than zero.
    """
    if not isinstance(accounting, dict):
        return ('<h2>Accounting timeline</h2>'
                '<p class="muted">Accounting timeline unavailable</p>')
    provenance = (
        '<p class="muted">Accounting timeline · '
        f'source <code>{_esc(accounting.get("source"))}</code> · '
        f'checkpoint <code>{_esc(accounting.get("checkpoint"))}</code> · '
        f'observed <code>{_esc(accounting.get("observed_at"))}</code></p>')
    revision_html = (
        f'<p>price revision: <code>{_esc(accounting.get("price_revision"))}</code> '
        '<span class="muted">(estimate from published prices)</span></p>')

    phases = accounting.get("phases")
    phase_rows = []
    if isinstance(phases, dict):
        for kind in _ACCOUNTING_PHASES:
            phase = phases.get(kind)
            phase = phase if isinstance(phase, dict) else {}
            phase_rows.append(
                "<tr>"
                f"<td>{_esc(kind)}</td>"
                f"<td>{_esc(_fmt_duration(phase.get('seconds')))}</td>"
                f"<td>{_esc(_fmt_duration(phase.get('known_seconds')))}</td>"
                f"<td>{_esc(phase.get('basis'))}</td>"
                "</tr>")
    phases_html = (
        '<div class="table-wrap"><table>'
        '<caption>Phases (unknown is not zero)</caption>'
        '<thead><tr><th scope="col">Phase</th><th scope="col">Seconds</th>'
        '<th scope="col">Known subtotal</th><th scope="col">Basis</th>'
        '</tr></thead><tbody>' + "".join(phase_rows) + "</tbody></table></div>")

    usage = accounting.get("usage")
    usage_rows = []
    if isinstance(usage, dict):
        for name in ("lane", "operator"):
            section = usage.get(name)
            section = section if isinstance(section, dict) else {}
            units = section.get("units") or {}
            units_text = ", ".join(f"{_esc(unit)} {_esc(amount)}"
                                   for unit, amount in units.items())
            estimate = "yes" if section.get("estimate", True) else "no"
            usage_rows.append(
                "<tr>"
                f"<td>{_esc(name)}</td>"
                f"<td>{_esc(section.get('events'))}</td>"
                f"<td>{_esc(section.get('priced_events'))}</td>"
                f"<td>{_esc(section.get('unpriced_events'))}</td>"
                f"<td>{_esc(estimate)}</td>"
                f"<td>{_esc(_fmt_usd(section.get('usd_est')))}</td>"
                f"<td>{_esc(_fmt_usd(section.get('known_usd_est')))}</td>"
                f"<td>{units_text}</td>"
                "</tr>")
    usage_html = (
        '<div class="table-wrap"><table>'
        '<caption>Usage (estimate; unknown is not zero)</caption>'
        '<thead><tr><th scope="col">Unit</th><th scope="col">Events</th>'
        '<th scope="col">Priced</th><th scope="col">Unpriced</th>'
        '<th scope="col">Estimate</th><th scope="col">Cost (USD)</th>'
        '<th scope="col">Known cost (USD)</th><th scope="col">Units</th>'
        '</tr></thead><tbody>' + "".join(usage_rows) + "</tbody></table></div>")

    attribution = accounting.get("attribution")
    attribution_html = ""
    if isinstance(attribution, dict):
        attributed = attribution.get("attributed_events", 0)
        unattributed = attribution.get("unattributed_events", 0)
        value = attribution.get("coverage")
        coverage = "unknown" if value is None else f"{value:.0%}"
        attribution_html = (
            '<p>attribution: attributed '
            f'<code>{_esc(attributed)}</code> · unattributed '
            f'<code>{_esc(unattributed)}</code> · outside scope '
            f'<code>{_esc(attribution.get("outside_scope_events", "unknown"))}</code> · coverage '
            f'<code>{_esc(coverage)}</code> '
            f'<span class="muted">{_esc(attribution.get("basis", "unavailable"))}</span></p>')

    return ("<h2>Accounting timeline</h2>" + provenance + revision_html
            + phases_html + usage_html + attribution_html)


def render_lifecycle(repo: str, row: dict, *, base_url: str = "") -> str:
    """Render a standalone, accessible HTML review page for one lifecycle row.

    Only the fact schema, attention reason codes and safe explicit references
    are rendered; arbitrary values, bodies, logs, credentials and local paths
    are never emitted, and every untrusted value and URL is escaped.
    """
    canonical = locator(repo, row, base_url=base_url)
    facts = row.get("facts") or {}
    item_id = row.get("item_id")
    attempt_id = row.get("attempt_id")
    run_id = row.get("run_id")
    train_id = row.get("train_id")
    work_id = row.get("work_id")
    observed_at = _latest_observed_at(facts)
    owner_revision = facts.get("work.public.item-v1", {}).get("revision")
    checkpoint = _local_checkpoint(facts)
    title = f"Lifecycle · {_esc(item_id or 'unknown')} · {_esc(attempt_id or 'unknown')}"
    identifiers = (
        f'<dt>release</dt><dd>{_ident(item_id)}</dd>'
        f'<dt>work</dt><dd>{_ident(work_id)}</dd>'
        f'<dt>attempt</dt><dd>{_ident(attempt_id)}</dd>'
        f'<dt>run</dt><dd>{_ident(run_id)}</dd>'
        f'<dt>train</dt><dd>{_ident(train_id)}</dd>')
    provenance = (
        f"<div><dt>Observed</dt><dd>{_esc(observed_at)}</dd></div>"
        f"<div><dt>Owner revision</dt><dd>{_ident(owner_revision)}</dd></div>"
        f"<div><dt>Local checkpoint</dt><dd>{_ident(checkpoint)}</dd></div>"
        '<div><dt>Mode</dt><dd>read-only snapshot (as observed, not live)</dd></div>')
    jump = _jump(repo, item_id, attempt_id)
    local_note = ('<p class="muted">Local facts are local-only; inspect them on the host with '
                  f'<code>{_esc("lanectl events --item " + (str(item_id) if item_id else ""))}</code>. '
                  'No browser file fetches are made.</p>')
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{_STYLE}</style>
</head>
<body>
<main>
<header>
<h1>Lifecycle review</h1>
<p class="muted">Read-only snapshot · repo <code>{_esc(repo)}</code> · observed {_esc(observed_at)}</p>
<dl class="identifiers">{identifiers}</dl>
<p class="locator">Canonical locator: <code>{_esc(canonical)}</code></p>
<p class="jump">Jump: <code>{_esc(jump)}</code></p>
</header>
<section id="provenance" aria-label="Provenance">
<h2>Provenance</h2>
<dl class="provenance">{provenance}</dl>
<p class="muted">This is an observed snapshot, not a live view. Missing, rejected, stale and unknown facts stay distinct; local success reported here remains pending until the owner verifies it.</p>
</section>
<section id="facts" aria-label="Lifecycle facts">
<h2>Facts</h2>
{_facts_html(facts)}
{local_note}
</section>
<section id="evidence" aria-label="Verification evidence">
{_evidence_html(row)}
{_references_html(facts)}
</section>
<section id="accounting" aria-label="Accounting timeline">
{_accounting_html(row.get("accounting"))}
</section>
<section id="reasons" aria-label="Attention reasons">
<h2>Attention reasons</h2>
{_reasons_html(row.get("reasons"))}
</section>
</main>
</body>
</html>
"""


def _is_within(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _refuse_symlinks(root: Path, relative_dir: Path) -> None:
    current = root
    for part in relative_dir.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"refusing symlink destination: {current}")
        if not current.exists():
            return


def export_lifecycle(root, repo: str, row: dict, *, base_url: str = "") -> Path:
    """Write the review page to a deterministic path and return it.

    The path is ``<root>/<locator path>/index.html``; the linked query IDs live
    in the page body, so serving the directory resolves the permalink.  Escape
    and symlink destinations are refused before anything is written.
    """
    page = render_lifecycle(repo, row, base_url=base_url)
    url = locator(repo, row, base_url=base_url)
    path = urlsplit(url).path
    repo_seg, item_seg, attempt_seg = _decode_identity(path)  # refuse traversal
    relative_dir = Path("lifecycle") / repo_seg / item_seg / attempt_seg
    root = Path(root)
    target = root / relative_dir / "index.html"
    if not _is_within(root.resolve(), target.parent.resolve()):
        raise ValueError("export path escapes the root directory")
    _refuse_symlinks(root, relative_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page)
    return target


def register(sub) -> dict:
    parser = sub.add_parser("lifecycle-web", help="export read-only lifecycle permalinks as static HTML")
    parser.add_argument("--repo", required=True, help="configured owner repository")
    parser.add_argument("--item", required=True, help="local work/release identifier")
    parser.add_argument("--output", required=True, help="directory to write the pages under")
    parser.add_argument("--base-url", default="", help="https origin to prefix locators with")
    return {"lifecycle-web": _cmd}


def _cmd(args, log) -> int:
    try:
        origin = _origin(args.base_url)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2
    from .coordination import configured
    from .config import load_releases
    from .lifecycle import release_work_ids
    from .accounting import accounting_timeline
    from .costs import _load_policy_raw
    from .contracts import utcnow
    coordinator = configured(args.repo)
    if coordinator is None:
        print(f"{args.repo}: Vuoro coordination is not configured")
        return 1
    events = log.read()
    work_ids = release_work_ids(load_releases())
    rows = lifecycle_rows(coordinator.client, events, item_id=args.item,
                          work_ids=work_ids, journal_path=coordinator.path)
    policy_raw = _load_policy_raw()
    checkpoint = len(events)
    observed_at = events[-1]["ts"] if events else utcnow()
    root = Path(args.output)
    for row in rows:
        row["reasons"] = attention_reasons(row)
        accounting = accounting_timeline(events, policy_raw, item_id=row["item_id"],
                                         attempt_id=row.get("attempt_id"))
        accounting["source"] = "lanectl.events"
        accounting["checkpoint"] = checkpoint
        accounting["observed_at"] = observed_at
        row["accounting"] = accounting
        print(export_lifecycle(root, args.repo, row, base_url=origin))
    return 0
