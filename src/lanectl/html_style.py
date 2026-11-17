"""One stylesheet and badge helper for the generated HTML pages.

``view`` and ``lifecycle-web`` both embed ``STYLE``.  Colours are defined once
as tokens per scheme; ``prefers-color-scheme`` switches them.  Text/background
pairs in ``TOKENS`` are checked against WCAG AA in the tests.
"""
from __future__ import annotations

import html

from .vocab import SYMBOLS, classify

TOKENS = {
    "light": {"bg": "#f4f7fb", "surface": "#ffffff", "text": "#14263a", "muted": "#4a5d70",
              "border": "#b4c0cd", "accent": "#1d5a99", "ok": "#17653b", "needs": "#8a4a00",
              "failed": "#a4262c", "running": "#1d5a99", "idle": "#4a5d70", "unknown": "#5b6573"},
    "dark": {"bg": "#0f1a26", "surface": "#172636", "text": "#e6edf5", "muted": "#a9b8c8",
             "border": "#3b4f64", "accent": "#7db4ee", "ok": "#6fd39a", "needs": "#f0b05c",
             "failed": "#ff9a9a", "running": "#7db4ee", "idle": "#a9b8c8", "unknown": "#b4bdc8"},
}


def _vars(scheme: str) -> str:
    return " ".join(f"--{name}:{value};" for name, value in TOKENS[scheme].items())


STYLE = f"""
:root {{ color-scheme:light dark; {_vars("light")} }}
@media (prefers-color-scheme: dark) {{ :root {{ {_vars("dark")} }} }}
html {{ background:var(--bg); }}
body {{ margin:0; padding:1.25rem 1rem 3rem; background:var(--bg); color:var(--text);
       font-family:system-ui,-apple-system,"Segoe UI",sans-serif; line-height:1.45; }}
main {{ max-width:72rem; margin:0 auto; }}
header {{ background:var(--surface); border:1px solid var(--border);
         border-top:4px solid var(--accent); padding:1rem 1.25rem; }}
h1 {{ margin:0 0 .25rem; font-size:1.5rem; }}
h2 {{ margin:2rem 0 .5rem; padding-bottom:.25rem; border-bottom:1px solid var(--border); }}
h3 {{ margin:1.2rem 0 .25rem; }}
nav {{ display:flex; flex-wrap:wrap; gap:.25rem 1rem; margin:.5rem 0; }}
a {{ color:var(--accent); }}
a:focus-visible, summary:focus-visible {{ outline:2px solid var(--accent); outline-offset:2px; }}
code, pre {{ font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace; }}
.muted {{ color:var(--muted); }}
.warning, .unavailable {{ color:var(--needs); }}
.tag {{ font-size:.8rem; color:var(--surface); background:var(--muted); padding:.05rem .4rem; }}
.tag.local {{ background:var(--accent); }}
dl {{ margin:.5rem 0; }}
dt {{ font-weight:700; }}
.identifiers {{ display:grid; grid-template-columns:auto 1fr; gap:.2rem .75rem; margin:.75rem 0; }}
.identifiers dt {{ color:var(--muted); }}
.identifiers dd {{ margin:0; }}
.provenance {{ display:flex; flex-wrap:wrap; gap:.75rem 1.75rem; margin:.75rem 0; padding:.5rem 0;
              border-top:1px solid var(--border); border-bottom:1px solid var(--border); }}
.provenance div {{ display:flex; gap:.35rem; }}
.provenance dt {{ color:var(--muted); font-weight:400; }}
.provenance dd {{ margin:0; }}
.table-wrap {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; margin:.5rem 0; }}
caption {{ text-align:left; padding:.25rem 0; color:var(--muted); }}
th, td {{ border:1px solid var(--border); padding:.35rem .5rem; text-align:left; vertical-align:top; }}
th {{ background:var(--surface); }}
tr:nth-child(even) td {{ background:var(--surface); }}
details summary {{ cursor:pointer; }}
.badge {{ font-weight:700; white-space:nowrap; }}
.badge.b-ok, .state-observed {{ color:var(--ok); }}
.badge.b-needs, .state-missing {{ color:var(--needs); }}
.badge.b-failed, .state-rejected {{ color:var(--failed); }}
.badge.b-running {{ color:var(--running); }}
.badge.b-idle {{ color:var(--idle); }}
.badge.b-unknown, .state-unknown, .state-stale {{ color:var(--unknown); }}
.state {{ font-weight:700; }}
.reasons {{ padding-left:1.25rem; }}
.reasons li {{ margin:.35rem 0; }}
.jump {{ margin:.35rem 0; overflow-wrap:anywhere; }}
"""

#: Metas every generated page carries (mobile width, both colour schemes).
HEAD_META = ('<meta charset="utf-8">\n'
             '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
             '<meta name="color-scheme" content="light dark">')


def badge(state) -> str:
    """HTML badge: symbol plus the state word, so colour is never the only cue."""
    kind = classify(state)
    word = html.escape("-" if state is None else str(state), quote=True)
    return (f'<span class="badge b-{kind} state state-{word.lower() if word.isalnum() else kind}">'
            f'<span class="sym">{SYMBOLS[kind]}</span> {word}</span>')
