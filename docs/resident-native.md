# Native resident execution on devbox or workstation

The resident has a native OpenCode launcher, a fixed model gateway, and an
opt-in [NixOS deployment module](../contrib/resident/nixos/README.md). These are
source implementations. No target service has been activated or qualified by
adding them. The [episode contract](resident-episodes.md) continues to own
admission, durable wake identity, context validation and recovery.

## Two explicit inference choices

| Route | Harness | Selected upstream | Aggregate usage policy |
|---|---|---|---|
| `opencode-go/deepseek-v4.1-flash` | Native standalone OpenCode | Exact Go subscription API, `deepseek-v4.1-flash` | Explicit durable rolling request allowance |
| `local/worker-fast` | Native standalone OpenCode | Existing workstation TLS model peer, `worker-fast` | No aggregate request allowance by default |

The executor may live on devbox or under an isolated workstation service UID.
Devbox plus the remote model peer keeps durable work available when the
workstation is off. Workstation placement runs the whole executor there; it does
not use the regular login's HOME, runtime directory, credentials or group grants.
Neither placement needs direct GPU access for tools. The existing inference
owner retains the GPU; no competing llama.cpp or llama-swap service is created.

There is no provider fallback, model switch, user auth-cache import, generic
Internet proxy or implicit availability queue. A route change means a new
protected recipe and generation after the old episode has stopped. This
resident adapter does not call a workstation-local inference lock helper from
devbox. The existing [local provider adapter](local-provider.md) remains a
different composition; the model peer and GPU owner arbitrate their own callers.

## Protected composition

The root-owned admission service starts `lanectl resident run`. Its qualified
launcher creates a systemd service under `resident-worker`. Native OpenCode and
its arbitrary filesystem/shell tools run there. `resident-model` is a different
UID holding only the selected upstream credential. The worker gets a private
network namespace, private runtime filesystem and writable project area. Its
network namespace supports native OpenCode's private server and Unix IPC without
exposing the workstation's localhost or abstract Unix sockets.

Only the host's fixed model Unix socket is explicitly bound into the worker's
otherwise hidden `/run`. PID1 creates that socket with the gateway service UID,
worker group and mode `0660`. A bounded worker-local relay turns this capability
into `http://127.0.0.1:18021/v1` inside the private namespace. This is not the
host's loopback interface. The host gateway obtains its listening descriptor
through systemd socket activation; it verifies the exact socket family, path,
listening state and activation identity before accepting requests.

The worker cannot use that capability to select an arbitrary destination, read
upstream credentials, change gateway policy or modify admission receipts. The
host module supplies these protections; they must still be observed on the
target. A different HOME or a native permission rule alone is insufficient.

The Nix module binds the native package, generated config and route through
immutable store references in the launcher, whose hash is part of the outer
recipe. Python module invocations use isolated mode so a package or
`sitecustomize.py` planted in the writable workspace cannot become root bridge
code. Secrets use systemd credentials and never enter the Nix store, native
arguments or worker environment.

The transient tool cgroup has an explicit cleanup owner. Both ordinary return
and interruption invoke it before artifact capture. It stops the unit and
verifies inactivity plus an empty/gone cgroup. Failure produces an unknown
episode and retains the slot. Recovery repeats cleanup using the same protected
profile; it does not infer cleanup of a service from a dead wrapper PID.

## Configure the native harness and gateway

The native and gateway examples are pure source templates:

```sh
python -m lanectl.resident_native render-config \
  --config contrib/resident/native-go.example.json
python -m lanectl.resident_gateway check-config \
  --config contrib/resident/gateway-go.example.json
python -m lanectl.resident_native render-config \
  --config contrib/resident/native-local.example.json
python -m lanectl.resident_gateway check-config \
  --config contrib/resident/gateway-local.example.json
```

These checks do not grant execution. The local hostname/CA and all-zero
binary/config digests are placeholders. The Nix module generates actual static
config and hashes from pinned packages. Its profile remains disabled until the
protected host qualification is supplied.

The native launcher requires OpenCode 2.2.3 or newer, one exact configured
provider, and a root-protected static config on a read-only mount. It clears
ambient auth, proxy, plugin and project configuration; refuses inherited managed
`/etc/opencode` settings; and supplies fresh private HOME/XDG paths. The native
executable and static config must match their SHA-256 hashes. A version floor
only establishes the schema floor: qualify the exact binary's native IPC, tool
and model behavior.

The native result must match the admitted episode/generation, name bounded safe
artifacts, and use the existing result contract. Nonzero native exit is a failure
even when a plausible result file exists. Memory arrives in the admitted exact
context packet; dynamic MCP/plugin memory is not silently enabled.

The systemd gateway entry point is:

```sh
python -I -m lanectl.resident_gateway run \
  --config /etc/lanectl/resident/gateway.json
```

Systemd supplies `CREDENTIALS_DIRECTORY/upstream-token` only to the gateway UID.
The credential is read once from a private regular file. Native OpenCode uses a
dummy gateway key; namespace/socket permissions authorize its access. Do not
expose the internal listener to a LAN or mistake the dummy key for authentication.
An explicitly configured TCP-only deployment is also supported by the gateway,
but is a different host composition and must restrict its listener independently.

The capability permits:

- `POST /v1/chat/completions` for the selected model, text and native function
  calls, at most one completion and 8,192 requested output tokens.
- `GET /v1/models`, returning the configured model. This is a policy catalog.
- `GET /healthz`, explicitly reporting `inference_readiness: not-probed`.

It cannot provide embeddings, hosted tool execution, a caller-selected URL,
redirect following, proxy discovery, raw backend administration or another
provider. It replaces client authorization/session headers with its own fixed
upstream identity. Go uses the documented subscription-only endpoint, identifying
User-Agent and stable logical-resident session ID. Upstream errors do not return
credentials, error bodies or an alternate Location to the caller.

There is one request in flight per gateway and at most eight connections reading
bounded headers/bodies. The body/header phase has an absolute ten-second bound.
Generation uses a configured 900-second deadline for connected reads; DNS and
initial TCP/TLS behavior also need bounded resolver/connection settings on the
host. Midstream failure/oversize leaves an incomplete HTTP chunk stream. SSE
completion additionally requires a terminal `[DONE]` event. Truncated output is
not reported as successful EOF.

## Budgets and durability

Go's configured rolling counter reserves each attempt in SQLite before upstream
network I/O. Retries, failures and unknown completion consume their reservation;
a gateway restart does not reset it. Clock rollback does not erase future-dated
reservations. This is a request-count policy, not a token ledger, monthly currency
promise or proof of subscription entitlement. The example's 120 requests per
3,600 seconds is a configuration choice, not a provider quota.

The local example has no aggregate request quota. It still has serial generation,
request/output byte limits, output token bounds, a finite native episode, and
host CPU/RAM/task controls. Filesystem quota/sizing is a host responsibility;
polling size is not a disk quota. No daily task-count or approval rule is added.

The gateway keeps no prompts or replies in its ledger. Preserve its current
database/WAL across restarts and upgrades. Use SQLite's backup API or a stopped
consistent snapshot. Do not restore an older allowance during runtime rollback.
Reconciliation of uncertain spend belongs to the capacity/provider owner.

## Verification and rollback

```sh
uv run pytest -q tests/resident
uv run pytest -q
```

The focused suite exercises actual local sockets, malformed inputs, credential
header replacement, streaming failures, persistent quotas, native fixture
execution, duplicate/fenced episodes, and cleanup uncertainty. Fixture OpenCode
and mocked systemd calls do not prove a native target's sandbox or GPU quality.
The full suite's existing systemd-user-bus failures in the development container
remain a landing gate; no tests were weakened to turn that environment green.

Run the Nix checks and target probes in the module README before activation:
native IPC inside the private namespace, denied regular-user paths/sockets and
direct networking, all descendants after cancellation, and a real cold-load
model/tool round trip. Health and catalog endpoints do not qualify a route.

To roll back, deny new admissions; stop and prove the tool cgroup empty; preserve
the newest workspace, correction, request and effect receipts; fence the logical
generation; switch the pinned host generation; and qualify its recipe before
readmission. Revoke the resident's peer grant independently of other clients.

Provider contracts:
[native automation](https://opencode.ai/docs/cli/commands/),
[custom providers](https://opencode.ai/docs/providers/),
[policies](https://opencode.ai/docs/policies/),
[Go API and sessions](https://opencode.ai/docs/console/harnesses/).
