# Public SDK authentication comparison

Read-only comparison used the public vuoro-client0.1.1 and0.1.6 release-tag
source. Installed0.1.1 client.py matches public Git blob
999ebbbaa0160e3db1e58e8ba09504a334ec83f6. Existing transport/profile behavior
is unchanged in0.1.6; its additions are operator-request convenience methods.
Both use Bearer authorization, X-Vuoro-Client-Protocol1, the invocation/v1
envelope and top-level repo_id at /api/invoke/v1. There is no added runner
header, signing/conversion or special identity-current handshake. Lanectl's
actual coordination transport already sends that protocol header, including
the previously measured invalid/enrolled authentication controls.

Sources: [0.1.1 client](https://github.com/bayleafwalker/vuoro/blob/vuoro-client-v0.1.1/packages/vuoro-client/src/vuoro_client/client.py),
[0.1.6 client](https://github.com/bayleafwalker/vuoro/blob/vuoro-client-v0.1.6/packages/vuoro-client/src/vuoro_client/client.py),
[0.1.6 release](https://github.com/bayleafwalker/vuoro/releases/tag/vuoro-client-v0.1.6).
The release wheel digest matches Sovite's declared b2267290ed28e89e522c94616e46e1167d155334888cbe6bc0bc287b14fcb59d.
The wheel contents were not downloaded or runtime-qualified in this comparison.

This gives no evidence that a client upgrade fixes the enrolled runner's401.
It does not establish the deployed refusal's cause. No credential values, private
Cloud source, owner mutations or new service probes were involved. Existing
private-owner investigation approval remains pending. The available connected
Vuoro tools expose run registration/outcome effects but no identity/enrollment
read that closes this gap; a user/operator run would not qualify the rejected
runner identity. No substitute identity was used.
