from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path
import traceback

from packages.application.use_cases.morning_brief import BriefInputs, ConfidenceEvidence, PublicationInput
from packages.application.use_cases.morning_brief_sections import ATTENTION_ITEMS_KEY, build_attention_section
from packages.domains.overview.priority import attention_priority_rank, recognized_priority, sort_overview_attention
from packages.domains.overview.pipelines.overview_models import MART_OPEN_ATTENTION_ITEMS_COLUMNS

out = Path(__file__).resolve().parent
rows = json.loads((out / 'rows.json').read_text())
original = json.loads(json.dumps(rows))
result = {'unicode': {'input': rows, 'code_points': {row['item_id']: [ord(c) for c in row['title']] for row in rows},
                      'ordered_ids': [row['item_id'] for row in sort_overview_attention(rows)],
                      'reversed_input_ordered_ids': [row['item_id'] for row in sort_overview_attention(reversed(rows))],
                      'source_values_unchanged': rows == original}, 'briefing': []}
confidence = ConfidenceEvidence(publication_key=ATTENTION_ITEMS_KEY, verdict='trustworthy', freshness_state='current',
                                completeness_pct=100, assessed_at=datetime(2026, 11, 15, tzinfo=UTC),
                                quality_flags={'validation_errors': 0, 'rejected_runs': 0},
                                contributing_run_ids=('synthetic-data-provider-run',), source_states=(('synthetic', 'current'),))
for label, severity in [('known3', 3), ('known2', 2), ('known1', 1), ('unknown7', 7), ('string3', '3'), ('string_high', 'high'), ('boolean_true', True), ('null', None)]:
    row = {'item_id': label, 'item_type': 'anomaly', 'title': 'Synthetic '+label, 'detail': 'Data-only PublicationInput probe', 'severity': severity, 'source_domain': 'finance'}
    inputs = BriefInputs(as_of=date(2026, 11, 15), generated_at=datetime(2026, 11, 15, 6, tzinfo=UTC),
                         publications={ATTENTION_ITEMS_KEY: PublicationInput(ATTENTION_ITEMS_KEY, (row,), confidence)}, policies=(), sources=())
    observed = {'label': label, 'input_severity': severity, 'input_python_type': type(severity).__name__,
                'actual_canonical_recognized_priority': recognized_priority(severity), 'actual_canonical_rank': attention_priority_rank(severity)}
    try:
        section = build_attention_section(inputs)
        observed['returned'] = {'summary': section.summary, 'items': [{'item_id': item.item_id, 'severity': str(item.severity), 'headline': item.headline, 'claim_status': str(item.claim_status)} for item in section.items]}
    except Exception as error:
        observed['exception'] = {'type': type(error).__name__, 'message': str(error)}
        observed['traceback'] = traceback.format_exc()
    result['briefing'].append(observed)
# This measures only the typed warehouse SQL seam. It is not a deployed Postgres proof.
import duckdb
connection = duckdb.connect(':memory:')
connection.execute('CREATE TABLE owned_attention ('+', '.join('"'+name+'" '+sqltype for name, sqltype in MART_OPEN_ATTENTION_ITEMS_COLUMNS)+')')
columns = [name for name, sqltype in MART_OPEN_ATTENTION_ITEMS_COLUMNS]
query = 'INSERT INTO owned_attention VALUES ('+', '.join('?' for _ in columns)+')'
for row in rows:
    connection.execute(query, [row.get(name) for name in columns])
result['typed_warehouse_sql'] = {'engine': 'DuckDB', 'version': duckdb.__version__, 'schema_from_actual_source': MART_OPEN_ATTENTION_ITEMS_COLUMNS,
                                'unicode_rows_accepted': connection.execute('SELECT item_id, title, severity FROM owned_attention ORDER BY item_id').fetchall(), 'severity_inputs': []}
for label, severity in [('string3', '3'), ('string_high', 'high'), ('boolean_true', True), ('null', None)]:
    connection.execute('DELETE FROM owned_attention')
    record = {'label': label, 'input_severity': severity, 'input_python_type': type(severity).__name__}
    row = dict(rows[0], item_id=label, severity=severity)
    try:
        connection.execute(query, [row.get(name) for name in columns])
        stored = connection.execute('SELECT severity FROM owned_attention').fetchone()[0]
        record.update(stored_severity=stored, stored_python_type=type(stored).__name__)
    except Exception as error:
        record['exception'] = {'type': type(error).__name__, 'message': str(error)}
    result['typed_warehouse_sql']['severity_inputs'].append(record)
connection.close()
print(json.dumps(result, ensure_ascii=False, indent=2))
