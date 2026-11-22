# Vuoro Shared native LANECTL runners

Verified on 2026-11-22 against `https://vuoro-shared.apps.kotona.app` after
Flux applied Appservice commit `88187d363b6efdc903b7e2516aa8efc33c78651e`
and Deployment identity revision 16 rolled out.
[Appservice #2231](https://github.com/bayleafwalker/appservice/pull/2231)

Each runner authenticated under its expected principal and received
`repo-unauthorized` when it tried the other repository. Independently,
systemd-loaded credentials passed `lanectl coordinate --require-work-read`
for both Shared repositories and the existing LANECTL Cloud binding.
The workstation timer loaded the separate Shared credential drop-in.
[LANECTL #86](https://github.com/bayleafwalker/lanectl/pull/86)

| Repository and verification Work | Vuoro run | Work outcome report | Terminal decision |
| --- | --- | --- | --- |
| `homelab-analytics#2927` | `run_JP1VWBY8T95XFCK2CTZ2HS7F9F` | `outcome_YY1WAMW1N54EBEN94PPERAJ6FE` | 504, withdrawn |
| `vuoro-cloud#2928` | `run_1997CV2794B2H4JJEHCAWXWMAP` | `outcome_S5NMC43K99A2S7DPGNRQSNYYFP` | 505, withdrawn |

Each disposable run acquired a generation-one lease, renewed it and appended
evidence. The owner recorded the intentional failure, released the lease and
left Work open. Replaying the report returned its existing receipt. A separate
planner decision withdrew each verification item, and a fresh owner read
confirmed `done` with resolution `withdrawn`. The proof exercised the live
coordination protocol without invoking a model or creating a product effect.
The release journals are host-persistent under
`/projects/dev/_artifacts/lanectl-native-coordination-20261122`.

A subsequent actual release, `hla-operating-horizon`, claimed
`homelab-analytics#1592` with the same scoped principal and acquired owner run
`run_Z9DSPF8GHPAT7P2RRZ2MJPDB01`. The owner renewed its lease while the
isolated OpenCode worker was active. Product landing and Work acceptance
require their own evidence.
