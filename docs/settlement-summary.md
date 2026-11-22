# Read-only settlement summary

Run the worker in a Pod with a projected Vuoro identity and the Claude
federation gateway listening on loopback. Supply an explicit batch of newly
completed LANECTL work IDs.

The original one-shot mode remains available:

```sh
lanectl-settlement-summary \
  --vuoro-token-file /run/vuoro-identity/token 4 8
```

It takes one to 32 distinct positive IDs, reads each item through
`work.public.item-v1` in `lanectl`, sends one bounded request to the gateway,
prints one plain-text summary, and exits. It writes no receipt and does not
advance a checkpoint.

The worker reads only the public item fields it needs, including the ID, title
and resolution. It rejects the whole batch if the owner response is unavailable
or any item is unsettled. It performs no owner writes. The gateway owns the
provider credential and request allowance; the worker uses only the scoped
Vuoro identity supplied by `--vuoro-token-file` and the loopback gateway.

Before scheduling this worker, qualify the Vuoro TokenReview binding for
the lane's exact ServiceAccount UID, audience, repository and workspace.
Use a separate Claude federation rule for the lane, a provider workspace
with an operator-verified spend cap, and a gateway request allowance.
The scheduler must supply new, distinct completed IDs. The one-shot mode
reads explicit IDs and does not discover work or track previous summaries.

## Durable request receipts

To retain a replayable result, save a batch as a request document and supply
a receipt directory:

```sh
lanectl-settlement-summary \
  --request /path/to/request.json \
  --receipt-dir /path/to/receipts \
  --vuoro-token-file /run/vuoro-identity/token
```

`--request` replaces positional work IDs and requires `--receipt-dir`. The
request document is the exact JSON emitted by `lanectl-settlement-batch`:
`work_ids` plus a `checkpoint`. A non-empty request also needs the scoped
Vuoro token file. The receipt directory is created with `0700` permissions
if needed.

The request digest is the SHA-256 of its canonical JSON, so unimportant
whitespace or indentation in the request file does not change its identity.
A completed receipt is stored as `<digest>.json` in the receipt directory and
contains the request fields, the digest and the summary. Its canonical bytes
are written to stdout.

If that completed receipt exists, a later invocation replays and prints its
exact stored bytes without reading the owner and without another model call.
Changing the work IDs or checkpoint changes the digest and is a new request.

## Uncertain model calls

Before making an inference, the worker durably writes a `<digest>.pending`
marker. After a successful summary it writes the completed receipt and then
removes the marker.

If the model call or receipt publication is uncertain, the marker remains.
A retry first checks for a valid completed receipt and replays it if present.
If only the marker remains, the retry makes no owner read or model call.
The gateway has no idempotency key, so an uncertain call is not retried automatically.

Investigate the marker and the gateway ledger before doing anything else.
Only clear the marker after confirming that no inference ran. If an inference
did run, restore a verified completed receipt bound to the same request, then
replay it. Never clear the marker merely to force a retry. A failure while
reading owner facts happens before the marker is written, so that failure can
be retried normally.

## Source-side batch selection

Run `lanectl-settlement-batch /path/to/events.jsonl --checkpoint /path/to/ack.json`
from the trusted scheduler side. On the first run omit `--checkpoint`.
The command reads the ledger without changing it and emits only a request of
work IDs plus a proposed checkpoint. It selects successful, closed
`work.synced` events that record an owner confirmation for `lanectl`.
Save that output as the request file and pass it unchanged with `--request`.

The owner checkpoint advances only after the batch's receipt is retained in
the receipt directory. An empty batch is an idle run: it writes an
acknowledgeable receipt with a null summary, makes no owner or Claude call,
and can be acknowledged immediately. On any failure or pending marker, keep
the previous checkpoint and investigate before retrying. Retry a failed batch
from the previous checkpoint. A checkpoint counts validated events and binds
the last one by digest, so a ledger replacement at that position fails closed.
The scheduler must serialize selections and acknowledgements for a ledger.
