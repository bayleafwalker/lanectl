# lanectl agent guidance

- Test-first: every module ships with tests under `tests/`; `uv run pytest -q` must pass.
- Python ≥3.13, stdlib only at runtime. No new dependencies without a release that allows them.
- Governance paths (see `governance/lanes/implement.toml` `protected_paths`) are interactive-only.
  Lane workers: never edit them; escalate instead.
- Events are append-only and validated by `lanectl.contracts`; add new event types only via the contract.
