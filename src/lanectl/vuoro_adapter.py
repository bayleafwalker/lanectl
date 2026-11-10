"""Lanectl's optional Vuoro owner adapter. Domain state remains in lanectl."""
from __future__ import annotations

from .stream_store import StreamError, StreamStore

READ = 'lane.stream.read-v1'
APPEND = 'lane.stream.append-v1'


def register_lane_catalog(registry, store):
    """Compose into an immutable service catalog; registration never migrates."""
    from vuoro_adapter_kit import object_schema, operation_spec
    from vuoro_service.catalog import OperationRejectedError
    from vuoro_service.contracts import OperationDefinition
    if not isinstance(store, StreamStore):
        raise TypeError('a migrated lanectl StreamStore is required')
    integer = {'type': 'integer', 'minimum': 0}
    stream = {'type': 'string', 'minLength': 1, 'maxLength': 256}
    schemas = {
        READ: object_schema({'stream': stream, 'after': integer,
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 256},
            'through': integer}, required=('stream',)),
        APPEND: object_schema({'stream': stream, 'expected_revision': integer,
            'events': {'type': 'array', 'minItems': 1, 'maxItems': 256, 'items': {'type': 'object'}},
            'idempotency_key': {'type': 'string', 'minLength': 8, 'maxLength': 128}},
            required=('stream', 'expected_revision', 'events', 'idempotency_key')),
    }
    results = {
        READ: object_schema({'revision': integer, 'head_revision': integer,
            'events': {'type': 'array', 'items': {'type': 'object'}}, 'next_after': integer,
            'has_more': {'type': 'boolean'}}, required=('revision','head_revision','events','next_after','has_more')),
        APPEND: object_schema({'previous_revision': integer, 'revision': integer,
            'count': integer, 'replayed': {'type': 'boolean'}},
            required=('previous_revision','revision','count','replayed')),
    }
    for operation in (READ, APPEND):
        authority = 'work:read' if operation == READ else 'work:evidence'
        def handler(arguments, context, *, operation=operation, authority=authority):
            identity = context.identity
            repo = context.repo_id
            # Do not infer repository/workspace/principal from caller arguments.
            if (not repo or not identity.authorizes_repo(repo) or authority not in identity.authorities
                    or not identity.workspace_id or not identity.principal_id):
                raise OperationRejectedError('lane-scope-required', 'authorized repository, workspace and principal required', http_status=403)
            try:
                if operation == READ:
                    return store.read(identity.workspace_id, repo, arguments['stream'],
                        arguments.get('after', 0), arguments.get('limit', 256), arguments.get('through'))
                return store.append(identity.workspace_id, repo, arguments['stream'],
                    identity.principal_id, arguments['idempotency_key'],
                    arguments['expected_revision'], arguments['events'])
            except StreamError as exc:
                raise OperationRejectedError(exc.code, str(exc), http_status=409) from exc
        raw = operation_spec(operation, owning_domain='lane', input_schema=schemas[operation],
            result_schema=results[operation], required_authority=authority,
            execution_semantics='read' if operation == READ else 'write',
            idempotency='not-allowed', repo_scoped=True)
        registry.register(OperationDefinition(**raw), handler)
