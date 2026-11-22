# Appservice LANECTL pilot runtime evidence

Observed on 2026-11-21 in the `lanectl` namespace. The scheduler runs the public implementation lane against the scoped `lanectl-pilot/lanectl` Vuoro Work binding.

| Check | Observed result |
| --- | --- |
| Anthropic inference | The deployed smoke Job sent one request from OpenCode through the LANECTL gateway to Claude Haiku and returned the expected completed response. [Appservice #2191](https://github.com/bayleafwalker/appservice/pull/2191) |
| Off-node state recovery | Longhorn backup `lanectl-pilot-recovery-20261121` restored to a separate volume. The read-only probe found the pilot governance, 156 events, seven gateway request records and a valid SQLite database. The restored coordination journal contained one matching claim and six recorded owner results. |
| Scoped train deployment | `lanectl deploy run train-20261119191729` served the exact checked `lanectl#2` train at commit `e444afe558ff6bbdfafc6d116670fae49227455b`. HTTP readiness passed. Foreground teardown left zero Deployments, ReplicaSets and Pods. The scoped identity was denied Secret reads and deployment creates outside the train namespace. [LANECTL #48](https://github.com/bayleafwalker/lanectl/pull/48) |
| Runner replacement | In `pilot-takeover-recovery-fixed`, Vuoro refused a second runner process while generation one was fresh. After expiry, LANECTL verified generation two using the same scoped runner identity. Vuoro recorded the predecessor as `replaced-by-holder` and refused its late outcome as `lease-ended`. The replacement reported an outcome and the disposable item and sprint were closed. [LANECTL #49](https://github.com/bayleafwalker/lanectl/pull/49) |
| Scheduled rollout | Flux applied appservice revision `b55bdaf28c6ed0476a73616ed8953a0f16f4c447`. Scheduled job `pilot-29921190` completed on the recovery image at 14:30:50 UTC. Admission reported `items_per_day 1/1`. [Appservice #2194](https://github.com/bayleafwalker/appservice/pull/2194) |
| Projected handoff writer | A disposable Job used the scheduled coordinator's projected Kubernetes identity to submit the checked-train request. Admission rejected an unrelated ConfigMap. The model gateway container has no writer token mount. [Appservice #2202](https://github.com/bayleafwalker/appservice/pull/2202) [Appservice #2203](https://github.com/bayleafwalker/appservice/pull/2203) |
| Standing owner publisher | Flux applied revision `da7e7c6ee83e708d08b2fbe55f0b0ccc41e807ea`. The unprivileged owner built disposable checked commit `1fdddbabf2105c0d67c98ca1348e485fdf2a203a`, pushed the image, and returned an immutable binding for digest `sha256:19734eda293384c5a43cf9da62483396197545ca4bbd067570c755a5dabbe64f`. Scheduled job `train-owner-publisher-29921305` succeeded at 16:25:54 UTC. A fresh owner also recovered the exact existing binding for the historical checked train. [Appservice #2205](https://github.com/bayleafwalker/appservice/pull/2205) [Appservice #2207](https://github.com/bayleafwalker/appservice/pull/2207) [LANECTL #64](https://github.com/bayleafwalker/lanectl/pull/64) |
| Owner-produced preview | A temporary projected identity could read the new fixture binding and create a Deployment in its dedicated preview namespace. It was denied Deployment creation in the default namespace and listing of handoff ConfigMaps. The image passed readiness. Foreground teardown completed, and the temporary namespace, grants and fixture handoff records were removed. |

## Scheduled release on 2026-11-22

- Scheduled Job `lanectl/pilot-29922585` claimed Work #1 in
  `lanectl-pilot/lanectl` (`vuoro-cloud-ws-01m7tgwk6gyg`) and ran candidate
  `hosted-pilot-settlement-receipts-a1` through the gateway using
  `opencode-go/deepseek-v4.1-flash`. Diff policy, fail-on-base and acceptance passed.
- An operator-reviewed correction clarified receipt replay before pending-marker
  refusal. Train `train-20261122134803` passed the required test on exact commit
  `a512c057882a012a4d8489c0ee8a365ad843ee8c`, deployed from its immutable
  binding into `lanectl-train-preview`, and tore down its preview Deployment.
  [Required CI check](https://github.com/bayleafwalker/lanectl/actions/runs/45030268138/job/137232115065)
- The owner resumed the same train using the reviewed publication path. The
  first publisher attempt held while CI was pending. Standing publisher Job
  `lanectl-train-publication/train-publication-owner-29922603` verified
  canonical ancestry after the credential broker merged at
  `4f74ab06b0277c2f5f5d7fd8eb0febe3268a26ac`. The owner reported the train
  settled. A separate scoped Work read returned `done`, resolution
  `accepted`, terminal decision 4.
  [LANECTL #83](https://github.com/bayleafwalker/lanectl/pull/83)
  [LANECTL #84](https://github.com/bayleafwalker/lanectl/pull/84)
  [Appservice #2230](https://github.com/bayleafwalker/appservice/pull/2230)

This run establishes the hosted claim-to-outcome path with a reviewed owner
handoff. It fills that part of rung 5. The independent-user pilot, autonomous
class landing and any broader lane-history authority cutover have separate
evidence requirements.

The detailed probe outputs and owner receipts are host-persistent under
`/projects/dev/_artifacts/lanectl-appservice-20261121-qualification`,
`/projects/dev/_artifacts/lanectl-work2-train-image`, and
`/projects/dev/_artifacts/lanectl-same-holder-fixed-20261121`.
