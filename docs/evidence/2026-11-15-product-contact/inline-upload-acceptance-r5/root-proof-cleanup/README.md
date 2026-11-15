# Root proof scratch cleanup

Only the three exact completed pytest trees were inspected: first official/tmp/pytest-of-bayleaf/pytest-15291, official-r5/pytest-official-base-v2 and official-r5/pytest-publication-base. Their144recorded process groups and60recorded owner-labeled container names were absent before cleanup. Nine exact reproducible dependency/build/cache paths were removed and checked absent; each tree reduced from about1GB to72MB/72MB/71MB. Raw logs, scripts, fixtures, synthetic databases and run data remain.

Generated build manifest copies and any signing/encryption material remain host-local under mode700/tmp/hla-inline-upload-official-r5-20261115/root-proof-cleanup. Only path/hash/ownership cleanup metadata is retained here. No other pytest sibling, active source worker, canonical source or dependency tree was touched.
