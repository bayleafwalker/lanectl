# Scratch acceptance-observer repair

This is a first-party scratch proposal, not a publication, revision, approval, retry reset, or acceptance of the failed a1 candidate. The published R1 acceptance SHA remains `57c9e9eef945a90d133a7a0f2b29194b1d9df7cd6a0007c52a50672b1fc02bf5`. The proposal preserves the original outcome and all four kinds, M700 and the existing attempt policy. It changes only the acceptance observer bytes in `/tmp`.

The old keyboard and click observer could reload before client navigation completed. The repair waits for the exact expected URL and network completion after the actual keyboard activation or click; it does not reload the page. The status for these click results is null because client-side navigation has no new document status; direct-load status checks remain unchanged.

The second repair accepts the existing safe Next generic error boundary for an unexpected backend 500 even when the browser document status is 200. It still rejects 404/503 status or copy, not-found/unavailable/all-clear/deleted copy, prior source facts and raw synthetic error body, and it requires only the exact source record request with no fallback. `error-controls.log` records pure comparator positive and negative cases; `navigation-controls.log` records actual matched-browser controls for correct, wrong and missing navigation with keyboard and click. These controls are not a product implementation or review verdict.

The exact rejected a1 source snapshot was archived twice. Across all 1,313 tracked files, the original and repaired snapshots differ only in `tests/test_attention_current_ui_acceptance.py`. The original two-test replay gave two failures: keyboard `ERR_ABORTED` and, on that replay, a stray report request. The previously recorded independent `/tmp/hla-a1-diagnosis.log` separately shows the original 500 generic-boundary mismatch. On the repaired snapshot, direct pytest and JUnit show nine passed and zero skipped. The literal declared acceptance command also passed separately and emitted its all-nine/no-skip gate message:

```bash
source /projects/dev/homelab-analytics/tools/project-env.sh
PYTHONPATH="$PWD" /projects/dev/homelab-analytics/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_attention_current_ui_acceptance.py --junitxml=/tmp/hla-ui-acceptance-observer-repair/updated-final.xml
PATH=/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin:"$PATH" PYTHONPATH="$PWD" uv run --no-sync python tests/test_attention_current_ui_acceptance.py
```

Both commands ran from `/tmp/hla-ui-acceptance-observer-repair/updated`, an isolated a1 archive with a symlink to the existing Python environment. This outcome does not change the actual native a1 exit 124, failed state or 776 worker lines, and must not be used to adopt it. Repaired acceptance on isolated canonical b2 still produced six named missing-UI failures and three passes, without skips or setup errors. The unchanged official `_base_lint(..., 600)` returned `[]` against a separate scratch-only temporary draft; nothing was published.

The repaired test and unchanged outcome form `proposal.json`. Any later attempt to change a published acceptance requires a new properly reviewed publication and actual fresh native independent review; this file does not perform either. The current active a2 and published R1 packet were not edited. All `/tmp` files and logs are session-local. Individual successful browser fixtures verify deletion of their own exact container IDs; other concurrently running containers with similar names were not attributed or touched.

## Comparator follow-up

A subsequent independent audit found that banning the raw numbers 404 and 503 anywhere in a generic error body rejected valid unrelated technical references. The current scratch repair removes that raw-number ban while retaining rejection of actual HTTP 404/503 statuses, semantic not-found/unavailable/all-clear/deleted states, prior source facts, raw error markers and fallback reads. `error-controls-final.log` accepts generic error boundaries containing `Reference: 404` or `Reference: 503` and rejects the actual and semantically mislabeled status controls. The original full outcome remains unchanged. The exact current test SHA is `72d1f08fe54a33873dca030deb597ea9dd2689768f4b52f6f494e9dd30428d4f`; proposal SHA is `c6f799e8096e475b077ebed708bd6afd19453dab14e9a189ccac033c0a8dc736`. The literal CLI result is `updated-cli-72d1.log` and the official temporary-draft base-lint result is `temp-draft-base-lint-72d1.log`.
