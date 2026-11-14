"""Falsify the semantic oracle without making any UI or service claim."""
from copy import deepcopy

import pytest
from semantic_oracle import FIELDS, LABELS, PRICE_FIELDS, assert_rows
from test_semantic_records import source_rows


def groups_for(kind):
    groups = []
    for row in source_rows(kind):
        pairs = []
        for field in FIELDS[kind]:
            value = row.get(field)
            text = 'Unknown' if value is None else str(value)
            if field in PRICE_FIELDS and value is not None:
                text += ' ' + row['currency']
            pairs.append([LABELS[field][0], text])
        groups.append({'pairs': pairs, 'headings': [], 'text': ''})
    return groups


@pytest.mark.parametrize('kind', ['anomaly', 'upcoming_cost', 'contract_review', 'contract_renewal'])
def test_correct_all_kinds_and_two_rows_pass(kind):
    assert_rows(kind, source_rows(kind), groups_for(kind))


def test_wrong_missing_and_rounded_market_reference_fail():
    kind = 'contract_review'
    rows = source_rows(kind)
    for mutation in ('wrong', 'missing', 'rounded'):
        groups = deepcopy(groups_for(kind))
        pairs = groups[0]['pairs']
        i = next(i for i, pair in enumerate(pairs) if pair[0] == 'market reference')
        if mutation == 'wrong':
            pairs[i][1] = '31.4159 EUR'
        elif mutation == 'missing':
            pairs.pop(i)
        elif mutation == 'rounded':
            pairs[i][1] = '17.35 EUR'
        with pytest.raises(AssertionError):
            assert_rows(kind, rows, groups)


def test_null_is_unknown_not_zero_or_omitted():
    kind = 'contract_review'
    rows = source_rows(kind)
    for mutation in ('zero', 'missing'):
        groups = deepcopy(groups_for(kind))
        pairs = groups[1]['pairs']
        i = next(i for i, pair in enumerate(pairs) if pair[0] == 'market reference')
        if mutation == 'zero':
            pairs[i][1] = '0 EUR'
        else:
            pairs.pop(i)
        with pytest.raises(AssertionError):
            assert_rows(kind, rows, groups)


@pytest.mark.parametrize('kind', ['anomaly', 'upcoming_cost', 'contract_review', 'contract_renewal'])
def test_swapping_two_label_values_fails(kind):
    groups = deepcopy(groups_for(kind))
    groups[0]['pairs'][0][1], groups[0]['pairs'][1][1] = groups[0]['pairs'][1][1], groups[0]['pairs'][0][1]
    with pytest.raises(AssertionError):
        assert_rows(kind, source_rows(kind), groups)


def test_fabricated_component_labels_and_omitted_row_fail():
    kind = 'contract_review'
    for mutation in ('pair', 'heading', 'named_heading', 'missing_row'):
        groups = deepcopy(groups_for(kind))
        if mutation == 'pair':
            groups[0]['pairs'].append(['Component name', 'Made up tax'])
        elif mutation == 'heading':
            groups[0]['headings'].append('Component 1')
        elif mutation == 'named_heading':
            groups[0]['headings'].append('Component Tax')
        else:
            groups.pop()
        with pytest.raises(AssertionError):
            assert_rows(kind, source_rows(kind), groups)


def test_currency_may_be_a_separately_labeled_fact():
    kind = 'contract_review'
    groups = deepcopy(groups_for(kind))
    for group in groups:
        for pair in group['pairs']:
            if pair[0] in {'current price', 'market reference'} and pair[1] != 'Unknown':
                pair[1] = pair[1].replace(' EUR', '')
        group['pairs'].append(['Currency', 'EUR'])
    assert_rows(kind, source_rows(kind), groups)


def test_fabricated_component_in_unmatched_extra_group_fails():
    kind = 'contract_review'
    groups = groups_for(kind)
    groups.append({'pairs': [['Component name', 'Made up charge']], 'headings': [], 'text': ''})
    with pytest.raises(AssertionError):
        assert_rows(kind, source_rows(kind), groups)


def test_value_suffix_and_unmatched_named_component_do_not_pass():
    kind = 'contract_review'
    groups = deepcopy(groups_for(kind))
    groups[0]['pairs'][0][1] += ' fabricated suffix'
    with pytest.raises(AssertionError):
        assert_rows(kind, source_rows(kind), groups)
    groups = groups_for(kind)
    groups.append({'pairs': [], 'headings': ['Component Tax'], 'text': ''})
    with pytest.raises(AssertionError):
        assert_rows(kind, source_rows(kind), groups)


def test_market_reference_needs_exact_value_but_no_extra_currency_label():
    kind = 'contract_review'
    groups = deepcopy(groups_for(kind))
    for pair in groups[0]['pairs']:
        if pair[0] == 'market reference':
            pair[1] = '17.3456'
    assert_rows(kind, source_rows(kind), groups)


def test_missing_current_price_currency_still_fails():
    kind = 'contract_review'
    groups = deepcopy(groups_for(kind))
    for pair in groups[0]['pairs']:
        if pair[0] == 'current price':
            pair[1] = '7.1234'
    with pytest.raises(AssertionError):
        assert_rows(kind, source_rows(kind), groups)


def test_nested_aliases_cannot_count_as_two_rows():
    kind = 'contract_review'
    one = source_rows(kind)[0]
    group = groups_for(kind)[0]
    with pytest.raises(AssertionError):
        assert_rows(kind, [one, one], [{**group, 'path': 'root.0'}, {**group, 'path': 'root.0.0'}])
    assert_rows(kind, [one, one], [{**group, 'path': 'root.0'}, {**group, 'path': 'root.1'}])


@pytest.mark.parametrize('label,value', [
    ('Component type', 'Solar'),
    ('Price component label', 'Energy'),
    ('Part identity', 'Grid'),
    ('Component identifier', 'tax-1'),
    ('Price part name', 'delivery'),
    ('Part kind', 'solar'),
    ('Component category', 'tax'),
    ('Part description', 'invented'),
    ('Component labels', 'invented'),
    ('Part classification', 'invented'),
    ('Components labels', 'invented'),
])
def test_invented_component_identity_family_fails(label, value):
    kind = 'contract_review'
    groups = groups_for(kind)
    groups[0]['pairs'].append([label, value])
    with pytest.raises(AssertionError):
        assert_rows(kind, source_rows(kind), groups)


def test_legitimate_provided_component_price_date_provider_and_generic_headings_pass():
    kind = 'contract_review'
    groups = groups_for(kind)
    groups[0]['pairs'].extend([
        ['Component price', '7.1234 EUR'],
        ['Part date', '2026-01-02'],
        ['Component provider', 'Oak Provider'],
    ])
    groups[0]['headings'].extend(['Component details', 'Component rows', 'Part information'])
    assert_rows(kind, source_rows(kind), groups)
