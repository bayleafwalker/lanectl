"""Independent assertions over browser-observed label/value associations."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

LABELS = {
    'counterparty_name': ('counterparty', 'merchant', 'payee', 'counterparty name'),
    'booking_date': ('booking date', 'booked', 'booked on', 'transaction date'),
    'amount': ('amount',), 'direction': ('direction', 'money flow'),
    'anomaly_reason': ('reason',),
    'contract_name': ('contract', 'name', 'plan'), 'provider': ('provider', 'supplier', 'company'),
    'expected_amount': ('expected amount', 'expected cost', 'amount due', 'amount'),
    'frequency': ('frequency', 'billing cycle', 'interval'),
    'expected_date': ('expected date', 'due date', 'date'),
    'confidence': ('confidence',),
    'utility_type': ('utility type', 'utility', 'type'),
    'reason': ('reason',), 'current_price': ('current price', 'price'),
    'market_reference': ('market reference', 'market price', 'market average', 'reference'),
    'renewal_date': ('renewal date', 'renews', 'date'),
    'days_until_renewal': ('days until renewal', 'days remaining', 'days until', 'days'),
}
FIELDS = {
    'anomaly': ('counterparty_name', 'booking_date', 'amount', 'direction', 'anomaly_reason'),
    'upcoming_cost': ('contract_name', 'provider', 'expected_amount', 'frequency', 'expected_date', 'confidence'),
    'contract_review': ('provider', 'utility_type', 'reason', 'current_price', 'market_reference'),
    'contract_renewal': ('contract_name', 'provider', 'renewal_date', 'days_until_renewal', 'current_price'),
}
PRICE_FIELDS = {'expected_amount', 'current_price', 'market_reference'}
NUMBER_FIELDS = PRICE_FIELDS | {'amount', 'days_until_renewal'}
CURRENCY_SYMBOL = {'EUR': '€', 'GBP': '£', 'USD': '$'}


def normal(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()


def label_matches(field: str, label: str) -> bool:
    value = normal(label)
    return any(value == alias or value.startswith(alias + ' ') for alias in LABELS[field])


def value_matches(field: str, expected, actual: str, currency: str | None) -> bool:
    text = actual.strip()
    if expected is None:
        return 'unknown' in text.lower()
    if field.endswith('_date'):
        try:
            day = date.fromisoformat(str(expected)[:10])
            formats = (day.isoformat(), day.strftime('%d %b %Y').lstrip('0'),
                       day.strftime('%B %d, %Y').replace(' 0', ' '))
            return any(v.lower() in text.lower() for v in formats)
        except ValueError:
            return str(expected).lower() in text.lower()
    if field in NUMBER_FIELDS:
        try:
            wanted = Decimal(str(expected))
            nums = (Decimal(n.replace(',', '')) for n in re.findall(r'(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?![\w.])', text))
            found = any(n == wanted for n in nums)
        except InvalidOperation:
            return False
        if not found:
            return False
        if field in PRICE_FIELDS and currency:
            return currency.lower() in text.lower() or CURRENCY_SYMBOL.get(currency, '\0') in text
        return True
    return normal(str(expected)) == normal(text)


def assert_group(kind: str, row: dict, group: dict) -> None:
    pairs = group['pairs']
    for field in FIELDS[kind]:
        candidates = [value for label, value in pairs if label_matches(field, label)]
        assert candidates, f'{kind}: missing semantic label {field}; got {pairs!r}'
        assert any(value_matches(field, row.get(field), value, None) for value in candidates), (
            f'{kind}: incorrect {field} value under its label: expected {row.get(field)!r}; got {candidates!r}'
        )
        currency = row.get('currency')
        if field in {'expected_amount', 'current_price'} and row.get(field) is not None and currency:
            currency_values = [value for label, value in pairs if normal(label) in {'currency', 'currency code'}]
            assert any(currency.lower() in value.lower() or CURRENCY_SYMBOL.get(currency, '\0') in value
                       for value in candidates + currency_values + [group.get('text', '')]), f'{kind}: currency missing for {field}'


def assert_no_fabricated(group: dict) -> None:
    for label, value in group['pairs']:
        normalized = normal(label)
        words = set(normalized.split())
        refers_to_component = bool(words & {'component', 'components', 'part', 'parts'})
        identity_words = {'name', 'names', 'type', 'types', 'kind', 'kinds', 'category', 'categories', 'classification', 'label', 'labels', 'description', 'descriptions', 'identity', 'identities', 'id', 'ids', 'identifier', 'identifiers', 'key', 'keys', 'number', 'numbers', 'index', 'indices', 'role', 'roles'}
        is_component_identity = normalized in {'component', 'part', 'price component'} or (
            refers_to_component and bool(words & identity_words)
        )
        if is_component_identity:
            assert value.strip().lower() in {'', 'unknown'}, f'invented component label: {label}={value}'
    for heading in group['headings']:
        match = re.fullmatch(r'\s*(?:component|part)\s+(.+?)\s*', heading, re.I)
        if match:
            assert normal(match.group(1)) in {'details', 'rows', 'items', 'information'}, (
                f'invented component heading: {heading}'
            )


def assert_rows(kind: str, rows: list[dict], groups: list[dict]) -> None:
    for group in groups:
        assert_no_fabricated(group)
    matches = []
    for row in rows:
        candidates = []
        for index, group in enumerate(groups):
            try:
                assert_group(kind, row, group)
            except AssertionError:
                continue
            candidates.append((index, group.get('path', f'isolated-{index}')))
        matches.append(candidates)

    def disjoint(first: str, second: str) -> bool:
        return first != second and not first.startswith(second + '.') and not second.startswith(first + '.')

    def assign(position: int, used: list[str]) -> bool:
        if position == len(matches):
            return True
        return any(all(disjoint(path, prior) for prior in used) and assign(position + 1, [*used, path])
                   for _, path in matches[position])

    assert assign(0, []), f'{kind}: no structurally disjoint groups match all rows {rows!r}; groups={groups!r}'
