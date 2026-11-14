"""Publish once only after external ownership preflight. A failure forbids retry."""
import importlib.util, json, os, sys
from pathlib import Path
import psycopg
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.ingestion_config import IngestionConfigRepository
from packages.storage.postgres_reporting import PostgresReportingStore
root,helper=sys.argv[1:]
assert root.startswith('/tmp/hla-source-qualification-') and os.path.isfile(root+'/warehouse.duckdb')
marker=root+'/PUBLISH_ATTEMPTED'
fd=os.open(marker,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); os.close(fd)
dsn='postgresql://homelab:homelab@postgres:5432/homelab'
with psycopg.connect(dsn) as c:
 assert c.execute('select current_database(),current_user').fetchone()==('homelab','homelab')
 assert not c.execute("select c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='reporting'").fetchall(), 'nonempty schema; refuse publication'
spec=importlib.util.spec_from_file_location('synthetic_helper',helper); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
assert module.PUBLICATIONS==['mart_subscription_summary','mart_upcoming_fixed_costs_30d','mart_contract_price_current','mart_contract_review_candidates','mart_contract_renewal_watchlist','mart_transaction_anomalies_current','mart_open_attention_items']
warehouse=DuckDBStore.open(root+'/warehouse.duckdb')
service=TransformationService(warehouse,control_plane_store=IngestionConfigRepository(Path(root) / 'control.db'))
reporting=ReportingService(service,publication_store=PostgresReportingStore(dsn,schema='reporting'),access_mode=ReportingAccessMode.PUBLISHED)
assert reporting.publish_publications(module.PUBLICATIONS)==module.PUBLICATIONS
print(json.dumps({'publish':'complete','relations':module.PUBLICATIONS}))
