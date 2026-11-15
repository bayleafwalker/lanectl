# HLA1597 unit-coverage closeout

The existing automatic core-source collapse rule now has meaningful unit coverage. PR86 is merged at82dbd94; all four CI jobs and the full local gate passed at candidate57a7785. The two new files add159lines under S250, with no production changes. See closeout.json and delivery.json for exact bindings.

Two actual native Sonnet implementations and eleven read-only native review sessions are retained, including original incomplete findings, later scoped supplements and coordinator disposition. Root independently verified10green cases,3 semantic mutant failures with7 controls passing, and all4 Python wrapper failure paths.

Earlier local gate failures remain visible: an inappropriate coordinator command-line Python override affected an existing refusal test; missing browser libraries and differing host font bytes/rules affected unchanged-base snapshots. Existing immutable Noble image fonts/rules plus existing Nix libraries resolved the runtime without source, baseline or tolerance changes. Full normal Make then passed. Runtime binaries and generated build outputs are omitted; image/font/rule/browser hashes and selected metadata are retained.

This closes only served HLA1597. It does not adopt the exhausted Expand, inline-upload or attention-UI packets, and contributes no new lanectl ruled product-feature result. Ownership was root session01a1d0d7-890b-7cd0-931f-0a9994d9308b, reservation508.
