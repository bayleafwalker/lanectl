# Appservice LANECTL pilot runtime evidence

Observed on 2026-11-21 in the `lanectl` namespace. The scheduler runs the public implementation lane against the scoped `lanectl-pilot/lanectl` Vuoro Work binding.

| Check | Observed result |
| --- | --- |
| Anthropic inference | The deployed smoke Job sent one request from OpenCode through the LANECTL gateway to Claude Haiku and returned the expected completed response. [Appservice #2191](https://github.com/bayleafwalker/appservice/pull/2191) |
| Off-node state recovery | Longhorn backup `lanectl-pilot-recovery-20261121` restored to a separate volume. The read-only probe found the pilot governance, 156 events, seven gateway request records and a valid SQLite database. The restored coordination journal contained one matching claim and six recorded owner results. |
| Scoped train deployment | `lanectl deploy run train-20261119191729` served the exact checked `lanectl#2` train at commit `e444afe558ff6bbdfafc6d116670fae49227455b`. HTTP readiness passed. Foreground teardown left zero Deployments, ReplicaSets and Pods. The scoped identity was denied Secret reads and deployment creates outside the train namespace. [LANECTL #48](https://github.com/bayleafwalker/lanectl/pull/48) |
| Runner replacement | In `pilot-takeover-recovery-fixed`, Vuoro refused a second runner process while generation one was fresh. After expiry, LANECTL verified generation two using the same scoped runner identity. Vuoro recorded the predecessor as `replaced-by-holder` and refused its late outcome as `lease-ended`. The replacement reported an outcome and the disposable item and sprint were closed. [LANECTL #49](https://github.com/bayleafwalker/lanectl/pull/49) |
| Scheduled rollout | Flux applied appservice revision `b55bdaf28c6ed0476a73616ed8953a0f16f4c447`. Scheduled job `pilot-29921190` completed on the recovery image at 14:30:50 UTC. Admission reported `items_per_day 1/1`. [Appservice #2194](https://github.com/bayleafwalker/appservice/pull/2194) |

The train deployment was an on-demand replay. The scheduled tick reached
admission, and the disposable Job exercised live coordination. A scheduled
product release through claim, execution, train deployment, cleanup and owner
settlement remains to be observed. The scheduled coordinator currently has
the Work runner mount. A train deployment also requires an image binding for
its exact checked commit and a client authorized in the train namespace.

The detailed probe outputs and owner receipts are host-persistent under
`/projects/dev/_artifacts/lanectl-appservice-20261121-qualification`,
`/projects/dev/_artifacts/lanectl-work2-train-image`, and
`/projects/dev/_artifacts/lanectl-same-holder-fixed-20261121`.
