import json
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from tests.test_attention_record_api import DuckPublicationStore

for ids in [('probe-b','probe-a'),('probe-a','probe-b')]:
 ts=TransformationService(DuckDBStore.memory())
 for ident in ids:
  ts.store.execute('INSERT INTO mart_open_attention_items VALUES (?, ?, ?, ?, ?, ?)',[ident,'anomaly','Same Title','Synthetic tie',2,'finance'])
 warehouse=ReportingService(ts,access_mode=ReportingAccessMode.WAREHOUSE)
 pub=DuckPublicationStore()
 published=ReportingService(ts,publication_store=pub,access_mode=ReportingAccessMode.PUBLISHED)
 published.publish_publications(['mart_open_attention_items'])
 print(json.dumps({'insertion':ids,'warehouse':[r['item_id'] for r in warehouse.get_open_attention_items()],'published_duckdb_adapter':[r['item_id'] for r in published.get_open_attention_items()]}),flush=True)
