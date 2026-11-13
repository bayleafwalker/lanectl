from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from pydantic import create_model
from apps.api.main import build_app
from apps.api.routes.report_routes import (
    TRANSACTION_ANOMALIES_ROW_MODEL,
    UPCOMING_FIXED_COSTS_ROW_MODEL,
    CONTRACT_REVIEW_CANDIDATES_ROW_MODEL,
    CONTRACT_RENEWAL_WATCHLIST_ROW_MODEL,
)
from packages.shared.settings import AppSettings

ROOT = Path('/tmp/hla-contract-sizing-9cf')
routes = [
    ('/reports/transaction-anomalies/{item_id}', 'AnomalyRecordResponse', TRANSACTION_ANOMALIES_ROW_MODEL),
    ('/reports/upcoming-fixed-costs/{item_id}', 'UpcomingRecordResponse', UPCOMING_FIXED_COSTS_ROW_MODEL),
    ('/reports/contract-review-candidates/{item_id}', 'ContractReviewRecordResponse', CONTRACT_REVIEW_CANDIDATES_ROW_MODEL),
    ('/reports/contract-renewal-watchlist/{item_id}', 'ContractRenewalRecordResponse', CONTRACT_RENEWAL_WATCHLIST_ROW_MODEL),
]
with TemporaryDirectory(prefix='hla-contract-sizing-', dir='/tmp') as temp:
    p = Path(temp)
    settings = AppSettings(data_dir=p, landing_root=p/'landing', metadata_database_path=p/'metadata/runs.db',
        account_transactions_inbox_dir=p/'inbox', processed_files_dir=p/'processed', failed_files_dir=p/'failed',
        api_host='127.0.0.1', api_port=8080, web_host='127.0.0.1', web_port=8081,
        worker_poll_interval_seconds=60, identity_mode='disabled', enable_unsafe_admin=True,
        control_plane_backend='sqlite', reporting_backend='duckdb', blob_backend='filesystem')
    app = build_app(settings)
    def save(name: str) -> None:
        app.openapi_schema = None
        path = ROOT/name/'generated'/'openapi.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True)+'\n')
    save('baseline')
    for index, (path, model_name, row_type) in enumerate(routes):
        model = create_model(model_name, item_id=(str, ...), rows=(list[row_type], ...))
        async def placeholder(item_id: str):
            return {'item_id': item_id, 'rows': []}
        placeholder.__name__ = f'prototype_record_{index}'
        app.add_api_route(path, placeholder, methods=['GET'], response_model=model)
        if index == 0:
            save('one')
    save('four')
