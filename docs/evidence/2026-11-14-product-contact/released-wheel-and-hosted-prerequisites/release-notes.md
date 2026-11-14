Namespace train checks now fail when interrupted, including when a child handles termination by exiting zero. The train-only guard also covers startup termination and keeps a bounded stop deadline. Worker harness shims and the separate-UID receipt backend are unchanged.

Validation: 1,120 passing tests, independent Claude Sonnet 5.5 review, real startup/stop/timeout and TERM-ignoring-child controls, and all 62 installed runtime source files matching the release. Two clean offline wheel builds were byte-identical to each other and to the installed wheel.

Wheel SHA-256: `934f03933acbe2548752cdb9a25799669504921df51ce9b5bbb438a59dd0ac30`.

The artifact manifest binds the wheel to source commit `b56f9cf4a7d9741069436f83e298f5dbde7e687b`. [Qualification evidence](https://github.com/bayleafwalker/lanectl/tree/v0.2.12/docs/evidence/2026-11-14-product-contact/namespace-completion) records the checks and their limits. Hosted composition, deployment and event-authority cutover remain separate qualification steps.
