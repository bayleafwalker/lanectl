"""Fail-closed validation of the JSON Schema subset used by owner catalogs.

Only draft 2020-12, the keywords below, and their documented JSON value
semantics are supported. Unrecognized constraints invalidate the entire schema,
including unused branches. Patterns are restricted to ASCII literals with optional
anchors and five exact catalog expressions; other patterns fail closed. Bounded
recursion rejects excessively deep data.
"""
import math
import re

_MAX_DEPTH = 64
_DRAFT = "https://json-schema.org/draft/2020-12/schema"
_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}
_CATALOG_PATTERNS = {
    r"^run_[0-9A-HJKMNP-TV-Z]{26}$",
    r"^lease_[0-9A-HJKMNP-TV-Z]{26}$",
    r"^outcome_[0-9A-HJKMNP-TV-Z]{26}$",
    r"^[0-9a-f]{64}$",
    r"^item:[0-9a-fA-F-]{36}@description:v[0-9]+@sha256:[0-9a-f]{64}@revise:[0-9]+$",
    r"^(self-reported|checked|role-separated|identity-separated|human-authorized)(\+(self-reported|checked|role-separated|identity-separated|human-authorized))*$",
}
_ANNOTATIONS = {"title", "description", "default", "examples", "deprecated", "readOnly", "writeOnly"}
_KEYWORDS = {"$schema", "type", "const", "enum", "anyOf", "properties", "required",
             "additionalProperties", "items", "minLength", "maxLength", "pattern",
             "minimum", "maximum", "minItems", "maxItems"} | _ANNOTATIONS


def _json(value, depth=0):
    if depth > _MAX_DEPTH:
        return False
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_json(x, depth + 1) for x in value)
    if type(value) is dict:
        return all(type(k) is str and _json(v, depth + 1) for k, v in value.items())
    return False


def _equal(a, b):
    if type(a) is bool or type(b) is bool:
        return type(a) is type(b) and a == b
    if type(a) in (int, float) and type(b) in (int, float):
        return a == b
    if type(a) is list and type(b) is list:
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    if type(a) is dict and type(b) is dict:
        return a.keys() == b.keys() and all(_equal(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _supported(schema, depth=0):
    if depth > _MAX_DEPTH or type(schema) is not dict or schema.keys() - _KEYWORDS:
        return False
    if "$schema" in schema and schema["$schema"] != _DRAFT:
        return False
    if "type" in schema:
        types = schema["type"]
        if type(types) is str:
            types = [types]
        if (type(types) is not list or not types or any(type(t) is not str or t not in _TYPES for t in types)
                or len(set(types)) != len(types)):
            return False
    if "const" in schema and not _json(schema["const"]):
        return False
    if "enum" in schema:
        options = schema["enum"]
        if type(options) is not list or not options or not all(_json(x) for x in options):
            return False
        if any(_equal(x, y) for i, x in enumerate(options) for y in options[:i]):
            return False
    if "anyOf" in schema:
        branches = schema["anyOf"]
        if type(branches) is not list or not branches or not all(_supported(x, depth + 1) for x in branches):
            return False
    if "properties" in schema:
        props = schema["properties"]
        if type(props) is not dict or not all(type(k) is str and _supported(v, depth + 1) for k, v in props.items()):
            return False
    if "required" in schema:
        req = schema["required"]
        if type(req) is not list or not all(type(x) is str for x in req) or len(set(req)) != len(req):
            return False
    if "additionalProperties" in schema and type(schema["additionalProperties"]) is not bool:
        return False
    if "items" in schema and not _supported(schema["items"], depth + 1):
        return False
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in schema and (type(schema[key]) is not int or schema[key] < 0):
            return False
    for key in ("minimum", "maximum"):
        if key in schema and (type(schema[key]) not in (int, float) or not _json(schema[key])):
            return False
    if "pattern" in schema:
        pattern = schema["pattern"]
        # Only literal ASCII patterns (with optional anchors) and these exact
        # owner catalog expressions are known to have matching ECMA/Python
        # behavior and bounded execution. Other regex syntax fails closed.
        if (type(pattern) is not str or len(pattern) > 256
                or (pattern not in _CATALOG_PATTERNS
                    and re.fullmatch(r"\^?[A-Za-z0-9_-]+\$?", pattern) is None)):
            return False
        try:
            re.compile(pattern)
        except (re.error, OverflowError, RecursionError):
            return False
    for key in _ANNOTATIONS & schema.keys():
        value = schema[key]
        if not _json(value):
            return False
        if key in ("title", "description") and type(value) is not str:
            return False
        if key in ("deprecated", "readOnly", "writeOnly") and type(value) is not bool:
            return False
        if key == "examples" and type(value) is not list:
            return False
    return True


def _matches_type(value, kind):
    if kind == "null": return value is None
    if kind == "boolean": return type(value) is bool
    if kind == "object": return type(value) is dict
    if kind == "array": return type(value) is list
    if kind == "string": return type(value) is str
    if kind == "number": return type(value) in (int, float)
    return type(value) is int or (type(value) is float and value.is_integer())


def _matches(value, schema):
    if "type" in schema:
        kinds = schema["type"]
        if type(kinds) is str: kinds = [kinds]
        if not any(_matches_type(value, kind) for kind in kinds): return False
    if "const" in schema and not _equal(value, schema["const"]): return False
    if "enum" in schema and not any(_equal(value, x) for x in schema["enum"]): return False
    if "anyOf" in schema and not any(_matches(value, x) for x in schema["anyOf"]): return False
    if type(value) is dict:
        props = schema.get("properties", {})
        if any(k not in value for k in schema.get("required", [])): return False
        if schema.get("additionalProperties") is False and any(k not in props for k in value): return False
        if any(not _matches(v, props[k]) for k, v in value.items() if k in props): return False
    if type(value) is list:
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", math.inf): return False
        if "items" in schema and any(not _matches(v, schema["items"]) for v in value): return False
    if type(value) is str:
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", math.inf): return False
        if "pattern" in schema:
            pattern = schema["pattern"]
            # Without multiline mode, ECMA's $ requires the actual end;
            # Python's $ also matches before a final newline.
            if pattern.endswith("$"): pattern = pattern[:-1] + r"\Z"
            if re.search(pattern, value) is None: return False
    if type(value) in (int, float):
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf): return False
    return True


def valid(value, schema):
    """Return whether a JSON value matches a fully supported catalog schema."""
    return _supported(schema) and _json(value) and _matches(value, schema)


def supported(schema):
    """Check the whole schema even when no input values are present."""
    return _supported(schema)
