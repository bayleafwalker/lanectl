# Read-only settlement summary

Run the worker in a Pod with a projected Vuoro identity and the Claude
federation gateway listening on loopback. Supply an explicit batch of newly
completed LANECTL work IDs.

```sh
python -I -m lanectl.settlement_summary \
  --vuoro-token-file /run/vuoro-identity/token 4 8
```

The worker reads up to 32 items through `work.public.item-v1` in
`lanectl`. It rejects the whole batch if the owner response is unavailable or
any item is unsettled. It sends only the ID, title and resolution to the
gateway and prints one summary. It performs no owner writes. The gateway
owns the provider credential and request allowance.

Before scheduling this worker, qualify the Vuoro TokenReview binding for
the lane's exact ServiceAccount UID, audience, repository and workspace.
Use a separate Claude federation rule for the lane, a provider workspace
with an operator-verified spend cap, and a gateway request allowance.
The scheduler must supply new, distinct completed IDs. This worker reads
explicit IDs and does not discover work or track previous summaries.
