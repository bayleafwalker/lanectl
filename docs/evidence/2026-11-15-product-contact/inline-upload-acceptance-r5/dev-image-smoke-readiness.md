# Prepared dev-image smoke seams

Read-only preparation against canonical HLA `b2d0fe393ac0971e906cce275e91f45e94422593`, by the independent acceptance reviewer. No deployment, credential value, active implementation source or running service was accessed. Execute only after a real candidate and checked train exist. This does not establish image or product health.

Use the normal checked train's owned `lane-dev-<actual-train-id>` deployment. The declared stack uses Postgres control/run metadata and S3, whereas the frozen acceptance's local fixture uses SQLite and filesystem storage. Never run its local API/build/stub or SQLite seed as deployed proof.

From the checked train checkout, use the actual train namespace and these compose files:

```bash
export LANE_NAMESPACE='lane-dev-<actual-train-id>'
dc=(docker compose --project-name "$LANE_NAMESPACE"
    -f infra/examples/compose.yaml
    -f infra/examples/compose-smoke.override.yaml
    -f infra/examples/compose-lane-dev.override.yaml)
"${dc[@]}" port api 8080
"${dc[@]}" port web 8081
"${dc[@]}" ps --format json
```

These are prepared commands, not commands executed in this review. Verify actual ephemeral loopback bindings, declared health endpoints and API `/ready`. Record container/image IDs against checked train build receipts; prior PR85 IDs and URLs are historical. Inspect only configuration presence and authentication results, never environment values, cookies or session tokens. Use one hostname, normally `localhost`, consistently for browser login.

The example profile uses `local_single_user` bootstrap auth; existing bootstrap settings do not rotate an existing account. In a fresh owned API container, `python -m apps.worker.main create-local-admin-user` supports a synthetic acceptance admin using the public fixture password. Then actual `/auth/login` supplies the session and CSRF cookie/header, and authenticated `POST /auth/users` creates synthetic operator/reader controls. Confirm the real stack's configuration and login before relying on either path.

Create the configured catalog through actual authenticated API endpoints, with the frozen seed's public JSON definitions and shared mapping: source systems, dataset contracts, column mappings, then source assets A/B/C and disabled control. There is no existing freshness-config write API. Inside the owned API image, the supported seam is `settings = AppSettings.from_env()` followed by `PostgresIngestionConfigRepository(settings.control_plane_dsn, schema=settings.control_schema).create_source_freshness_config(...)`. Use the existing `SourceFreshnessConfigCreate` for C's monthly day-1, window-0 schedule. Do not print the DSN or add an API endpoint.

For loaded-overdue C, first ingest its distinct baseline through the actual API and verify the returned run context identifies C. Only in the fresh owned Postgres, parameter-bind an update of that exact synthetic receipt's `ingestion_runs.created_at`, constrained by its run ID and actual status, with a safely quoted configured schema. Require exactly one returned row and commit. Reread actual `/runs/{id}` and `/control/source-freshness`; historical age alone does not establish overdue, especially near a schedule boundary. Never target `/data/config.db` in this deployment.

Reuse the frozen format bytes, multipart/read/assertion helpers, receipt-ID assertions and browser script against deployed API/web URLs. Keep the deployed image as subject. The later real smoke must observe distinct CSV/XLSX/JSON uploads, C's old-to-new receipt and actual freshness, A/B isolation, the same `/sources` document, duplicate/invalid outcomes, no-JS safety and actual roles. Local malformed-upstream fault fixtures remain separate BFF qualification; a live smoke does not inherit those proofs.

Actual example auth/session readiness and TTL, catalog collisions, S3/promotion behavior, browser availability and C's overdue observation remain unresolved until execution. Guard ownership with the exact checked train namespace, compose labels and recorded images before any fixture mutation. No cluster or production effect is included.

Source references at the fixed HLA base:

- `scripts/lane-dev-deploy.sh` and `infra/examples/compose-lane-dev.override.yaml`: namespace, ephemeral ports and declared health.
- `docs/runbooks/configuration.md`, `apps/worker/command_handlers/admin_commands.py`, `apps/api/routes/auth_session_routes.py`: bootstrap caveat, supported admin CLI and login/CSRF.
- `apps/api/models.py`, `source_contract_routes.py`, `source_mapping_routes.py`: catalog request shapes and API seams.
- `packages/storage/postgres_ingestion_config.py`, `postgres_source_freshness_catalog.py`: existing Postgres configuration repository.
- `packages/storage/runtime.py`: configured Postgres run metadata selection.
- Prior `../api-a7-delivery` under the 2026-11-14 evidence folder proves its own earlier scope only, not this inline feature.
