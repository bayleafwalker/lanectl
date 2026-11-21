# Read-only settlement summary

Run the worker in a Pod with a projected Vuoro identity and the Claude
federation gateway listening on loopback. Supply an explicit batch of newly
completed LANECTL work IDs.

```sh
lanectl-settlement-summary \
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

## Source-side batch selection

Run `lanectl-settlement-batch /path/to/events.jsonl --checkpoint /path/to/ack.json`
from the trusted scheduler side. On the first run omit `--checkpoint`.
The command reads the ledger without changing it and emits only a batch of
work IDs plus a proposed checkpoint. It selects successful, closed
`work.synced` events that record an owner confirmation for `lanectl`.
Pass only the IDs to the summary Pod.

Record the returned checkpoint after the batch's summary is retained.
An empty batch can be acknowledged immediately. Retry a failed batch from
the previous checkpoint. A checkpoint counts validated events and binds
the last one by digest, so a ledger replacement at that position fails closed.
The scheduler must serialize selections and acknowledgements for a ledger.
