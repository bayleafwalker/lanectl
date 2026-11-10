# Local inference provider

`local/<profile>` is an explicit native OpenCode route to the workstation
inference pool. It is separate from OpenCode Go and never fails over to a
hosted provider. Set the loopback endpoint explicitly before routing work:

```sh
export LANECTL_LOCAL_BASE_URL=http://127.0.0.1:8020/v1
```

A reviewed lane/repository routing revision selects a profile such as
`local/worker-fast`. No default routing or autonomous class is changed by the
adapter. Configuring a route does not qualify a model for a task class; the
ladder's restricted-release landing evidence remains required.

The adapter runs installed OpenCode 2.2.3 or newer with a private server and a
single generated OpenAI-compatible provider. It reuses
`local-inference/scripts/lib/lane.py run` to hold the existing exclusive
inference lock for the entire attempt. `LANECTL_LOCAL_LANE_HELPER` may name an
explicit absolute installed copy of that stdlib helper. A busy lock fails the
attempt, rather than competing for or evicting the loaded model.

The attempt's original sandbox and named service are retained. Provider
configuration is mounted read-only inside it. Global/project model overrides,
plugins, MCP servers, hosted credentials, proxy configuration and telemetry
exporters are not inherited. A managed `/etc/opencode` configuration is an
unsupported composition and causes refusal. Native policies allow only the
local provider; the local relay forwards only chat/model requests to the
selected literal loopback origin, with redirects and proxy discovery disabled.
A local error or redirect never supplies a different destination.

The native schema and policy behavior are based on the official
[OpenCode provider](https://opencode.ai/docs/providers/) and
[policy](https://opencode.ai/docs/policies/) contracts. Older clients are refused
because OpenCode versions before 2.2.3 interpret integration policy differently.

Verification uses synthetic prompts and loopback HTTP servers: endpoint/model
selection, redirect refusal, project/inherited override rejection and a worker
attempting to rewrite its own provider config. This verifies the route and
configuration boundary, not model quality, VRAM headroom or qualification for
private product work. The existing tool/effect grants still govern native
worker commands.
