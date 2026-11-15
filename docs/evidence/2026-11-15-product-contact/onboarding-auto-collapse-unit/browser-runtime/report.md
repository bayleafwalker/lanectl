# HLA1597 visual runtime diagnosis

Scope: read-only diagnosis for candidate `57a7785c17ae76ba2169ca6af5bd4af62564a188`, with unchanged canonical base `b2d0fe393ac0971e906cce275e91f45e94422593` used for the controlled two-screenshot comparisons. No product, test, baseline, tolerance, global font, browser installation, or global cache was intentionally modified. This report does not assert a full visual or Make gate pass.

## Observations

- Parent's corrected-library run launched Chromium and produced 53/55 passing; app-shell and retro-shell snapshots differed by 49 and 71 pixels respectively. The same two failures and exact pixel counts were reproduced against an owned copy of the unchanged base under installed `lanectl.sandbox.for_train` using both default host Fontconfig and explicit `FONTCONFIG_FILE=/etc/fonts/fonts.conf`/`FONTCONFIG_PATH=/etc/fonts`. Raw `default-visual.stdout` and `system-visual.stdout` retain the comparison. The two base screenshot SHA-256 values were and remain `d0db1bbb25864a3a8dd38e2a88e6f78803b797f12788eb5bf584d622eea2db11` and `d3e7d239c76731e42b361dd741ecbb137ed6eccbee7a4c04c3cd9c0b942a0972`, also matching the candidate files. These failures cannot be attributed to the candidate's two new test files.
- Chromium CDP reported Liberation Sans, Liberation Serif and Liberation Mono for the page's font stacks in both the host and the pre-existing Playwright Noble image. However the host's and Noble image's Liberation 2.1.5 regular font files have different byte hashes. Same family/version labels alone did not establish same font bytes or rendering rules.
- The existing image `sha256:b0ab6f3cb99aa7803adbc14d9027ec1785fc6e433b97e134e0f8fe61683b6b53` ran the same unchanged base's two checks successfully, with Node 20.20.1 and the exact same Chromium headless-shell binary SHA-256 `22d72b589f908111fa29ff4e61ead8a0601e925177f59c70e2e851c22e9b1886`. This is evidence of a working baseline-compatible runtime, not by itself a train-fenced host gate.
- A minimal custom Fontconfig pointing only at the image's same-version Liberation fonts did not pass (5,482 and 67,815 pixels); adding host Fontconfig rules returned the original 49/71 mismatch. Neither experiment is a solution.
- The passing host control used the existing Noble image's complete font set and all 25 enabled Fontconfig rule files copied into owned scratch, with the image's base `fonts.conf` modified only to point its font, rule and cache locations at scratch. All 211 copied font files match the immutable image by SHA-256 (`image-font-integrity.json`); all 25 enabled rules and the unmodified copied base config match it (`image-rule-integrity.json`). The generated redirected config's SHA-256 is `ea49f137ad5f411a8f576b3a3cfa30e016bde0898ba957e8c9190e70baa6083e`.
- The exact installed train fence then ran the two unchanged base screenshot tests **2 passed**, exit 0 (`nobleimage-visual.stdout`, `visual-control-nobleimage-results.json`). A separate train-fenced Chromium CDP/strace probe shows actual opens of the copied Noble Liberation font paths and reports the expected three font families (`trace-image.stdout`, `font-open-image.trace`). The cached browser binary SHA remained unchanged; candidate tracked status and head remained unchanged.

## Runtime settings for the parent's next gate

Set these **inside the command passed to `for_train`**, with the scratch directory writable; the clean outer transport does not carry the Fontconfig or loader variables. The successful base control also isolated its temporary and cache directories.

```sh
export LD_LIBRARY_PATH="$(cat /tmp/hla1597-browser-runtime-20261115/browser-libraries.txt)"
export FONTCONFIG_FILE=/tmp/hla1597-browser-runtime-20261115/fonts/noble-image-rules.conf
export FONTCONFIG_PATH=/tmp/hla1597-browser-runtime-20261115/fonts/noble-etc-fonts
export XDG_CACHE_HOME=/tmp/hla1597-browser-runtime-20261115/fonts/nobleimage-visual/cache
export PLAYWRIGHT_BROWSERS_PATH=/home/bayleaf/.cache/ms-playwright
```

The parent must preserve these scratch fonts, rules and cache paths until its own 55-check and full Make executions finish. No `--update-snapshots`, skips or altered tolerances were used. The owned list of Nix browser libraries is host-specific and session-local; Make prepends its normal GCC library. The browser cache override is needed because changing `XDG_CACHE_HOME` otherwise changes Playwright's default browser lookup. These variables reproduced the two base checks; they do not by themselves establish the remaining 53 checks or candidate gate.

## Process and evidence

The initial font-probe experiment isolated `XDG_CACHE_HOME` without setting `PLAYWRIGHT_BROWSERS_PATH`, so Playwright could not locate the cached browser; `default.stderr`/`system.stderr` retain that setup failure. The corrected probes set the existing browser path explicitly. Every image-inspection and extraction container used a unique owner label and exact-ID removal, with absence recorded in the corresponding `*-cleanup.json`; no image was pulled. Scratch contains private copies of the base source and frontend dependencies for the two-test controls. All actual baseline images, raw screenshot diffs, stdout/stderr, scripts, config provenance and hash manifests are retained here for independent inspection. No result was inferred from a sandbox denial.
